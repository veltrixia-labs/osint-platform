import asyncio
import logging
import os
import time
import json
from typing import Dict, Any, Optional, List
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError
from anthropic import AsyncAnthropic
from config.settings import settings

logger = logging.getLogger(__name__)

# Strict Global Throttle to prevent Thundering Herd
_global_llm_semaphore = asyncio.Semaphore(1)

# DeepSeek documents 400/401/402/422 as MUST-NOT-retry: the cause is entirely
# request- or account-side, so a second attempt only reconfirms it. 429 and 5xx
# are the retryable ones.
_DEEPSEEK_NO_RETRY_STATUSES = frozenset({400, 401, 402, 422})

_deepseek_client: Optional[AsyncOpenAI] = None
if settings.deepseek_api_key:
    # max_retries=0: the SDK default is 2, so up to three HTTP attempts used to happen
    # inside one asyncio.wait_for — which made a fast 429/5xx retried internally
    # indistinguishable from a genuinely slow generation. The outer wait_for below is
    # the single authority on the time budget; no timeout= is passed here on purpose.
    _deepseek_client = AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url="https://api.deepseek.com",
        max_retries=0,
    )

# Stage 1: Anthropic Claude client constructed-but-unused (key-guarded, mirrors the
# DeepSeek idiom above). Stage 2 wires it as a fallback inside generate_analysis;
# it stays dormant unless a caller opts in via enable_fallback=True.
_anthropic_client: Optional[AsyncAnthropic] = None
if settings.anthropic_api_key:
    _anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)


def _parse_batch_or_text(text: str, is_batch: bool, provider: str) -> str | List[Dict] | None:
    """Shared post-processing for both providers. For is_batch, strip ```json /
    ``` fences and json.loads; otherwise return the raw text. Parse failure → None
    (logged). Keeps DeepSeek and Claude output handling byte-identical."""
    if not is_batch:
        return text
    try:
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1].split("```")[0].strip()
        return json.loads(cleaned)
    except Exception as e:
        logger.error(f"[LLM] Failed to parse batch JSON from {provider}: {e}")
        return None


def _retry_after(exc: Any) -> Optional[str]:
    """The provider's Retry-After header, when the SDK exposes one. None otherwise."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    return headers.get("retry-after") if headers is not None else None


async def _deepseek_attempt(system_prompt: str, user_prompt: str, is_batch: bool, temperature: float) -> tuple[str | List[Dict] | None, bool]:
    """One DeepSeek call under the strict 15s timeout.

    Returns ``(result, retryable)``:
      * ``result``    — the parsed result/text on success, else None on timeout /
                        API error / batch-parse failure.
      * ``retryable`` — whether a second attempt could plausibly succeed. False
                        only for the statuses DeepSeek documents as MUST-NOT-retry
                        (see ``_DEEPSEEK_NO_RETRY_STATUSES``); True everywhere
                        else, including unknown statuses, so an unrecognised
                        condition still gets its retry.

    A tuple rather than a sentinel on purpose: the caller's success test is
    ``if result is not None``, so any non-None sentinel would be mistaken for a
    successful result. The tuple makes that class of bug unrepresentable.

    Never raises — a None result is the signal to retry or fall back.

    Every failure path logs elapsed seconds: a 15.0s exhausted budget and a 2.1s
    fast rejection are different conditions and must not read the same."""
    started = time.monotonic()
    try:
        response = await asyncio.wait_for(
            _deepseek_client.chat.completions.create(
                # "deepseek-chat" was the pre-2026-07-24 deprecated alias; it maps
                # to deepseek-v4-flash in NON-THINKING mode (all callers use this
                # non-thinking path — no caller relies on deepseek-reasoner/thinking).
                model="deepseek-v4-flash",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=temperature
            ),
            timeout=15.0
        )
        text = response.choices[0].message.content
        return _parse_batch_or_text(text, is_batch, "DeepSeek"), True
    except (asyncio.TimeoutError, TimeoutError):
        logger.error("[LLM] DeepSeek API timeout (15s). elapsed=%.2fs", time.monotonic() - started)
        return None, True
    except RateLimitError as e:
        logger.error(
            "[LLM] DeepSeek rate limited: HTTP %s retry_after=%s elapsed=%.2fs: %s",
            getattr(e, "status_code", None),
            _retry_after(e),
            time.monotonic() - started,
            e,
        )
        return None, True
    except APIStatusError as e:
        status = getattr(e, "status_code", None)
        retryable = status not in _DEEPSEEK_NO_RETRY_STATUSES
        logger.error(
            "[LLM] DeepSeek API status error: HTTP %s retry_after=%s elapsed=%.2fs retry=%s: %s",
            status,
            _retry_after(e),
            time.monotonic() - started,
            "yes" if retryable else "no",
            e,
        )
        return None, retryable
    except APIConnectionError as e:
        logger.error(
            "[LLM] DeepSeek connection error: type=%s elapsed=%.2fs: %s",
            type(e).__name__,
            time.monotonic() - started,
            e,
        )
        return None, True
    except Exception as e:
        logger.error(
            "[LLM] DeepSeek API Error: %s. type=%s elapsed=%.2fs",
            e,
            type(e).__name__,
            time.monotonic() - started,
        )
        return None, True


async def generate_analysis(system_prompt: str, user_prompt: str, is_batch: bool = False, temperature: float = 0.7, enable_fallback: bool = False, **kwargs) -> str | List[Dict] | None:
    """
    Primary path: DeepSeek (deepseek-v4-flash) with ONE retry on transient failure
    (timeout / API error / batch-parse failure). The retry applies to ALL callers —
    it only adds an attempt on failure, so the success path is byte-identical to before.

    Optional resilience (enable_fallback=True): if DeepSeek still fails after retries,
    degrade to Anthropic Claude (claude-haiku-4-5) instead of returning None. The
    fallback is OPT-IN — default False keeps every existing caller on the DeepSeek-only
    path. The whole cascade NEVER raises: any failure at any stage → None (caller skips).

    Concurrency note: the entire cascade runs while holding the single global LLM slot
    (_global_llm_semaphore). Attempts are strictly capped to bound how long the slot is
    held — 2 DeepSeek tries (<=15s each + 1s backoff) and, if fallback fires, 1 Claude
    try (<=15s). Do NOT add more retries.
    """
    if not _deepseek_client:
        logger.error("[LLM] DeepSeek API key not configured. Analysis failed.")
        return None

    async with _global_llm_semaphore:
        # --- Primary: DeepSeek with one retry on transient failure ---
        for attempt in range(2):  # 2 attempts total = 1 retry
            if attempt == 0:
                logger.info("[LLM] Sending request to DeepSeek (Fail-Fast Mode)")
            else:
                logger.info("[LLM] DeepSeek retry (attempt %d/2) after transient failure.", attempt + 1)
                await asyncio.sleep(1.0)  # short backoff between attempts
            result, retryable = await _deepseek_attempt(system_prompt, user_prompt, is_batch, temperature)
            if result is not None:
                logger.info("[LLM] DeepSeek Analysis successful. Pacing pipeline with 2.0s cooldown.")
                await asyncio.sleep(2.0)
                return result
            if not retryable:
                # The status line above carries the HTTP code and retry=no. Breaking
                # here skips only the second DeepSeek attempt (and its 1.0s backoff,
                # which runs at the top of the next iteration) — control still
                # reaches the fallback block below unchanged.
                logger.error("[LLM] DeepSeek failure is not retryable; skipping the second attempt.")
                break

        # --- DeepSeek exhausted. Optional Claude fallback (opt-in only). ---
        if not enable_fallback or _anthropic_client is None:
            logger.error("[LLM] DeepSeek failed after retries. Failing fast (no fallback).")
            return None

        logger.warning("[LLM] DeepSeek failed after retries; ENGAGING Claude fallback (claude-haiku-4-5).")
        try:
            # Anthropic API shape differs from OpenAI: the system prompt is the
            # top-level `system=` param (NOT a messages entry), max_tokens is REQUIRED,
            # and the text lives at resp.content[0].text.
            resp = await asyncio.wait_for(
                _anthropic_client.messages.create(
                    model="claude-haiku-4-5",
                    max_tokens=512,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                ),
                timeout=15.0
            )
            text = resp.content[0].text if resp.content else ""
            result = _parse_batch_or_text(text, is_batch, "Claude")
            if result is not None:
                logger.info("[LLM] Claude fallback SUCCEEDED.")
            else:
                logger.error("[LLM] Claude fallback returned unparseable output. Failing.")
            return result
        except (asyncio.TimeoutError, TimeoutError):
            logger.error("[LLM] Claude fallback timeout (15s). Failing.")
            return None
        except Exception as e:
            logger.error(f"[LLM] Claude fallback error: {e}. Failing.")
            return None

def get_metrics_summary() -> str:
    """Mock metrics to satisfy any UI imports without crashing."""
    return "--- DeepSeek Single-Path Pipeline ---\nStatus: Active\nModes: Fail-Fast, Throttled"
