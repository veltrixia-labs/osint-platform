import asyncio
import logging
import os
import time
import json
from enum import Enum
from typing import Dict, Any, Optional, List
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
from config.settings import settings

logger = logging.getLogger(__name__)

# Strict Global Throttle to prevent Thundering Herd
_global_llm_semaphore = asyncio.Semaphore(1)

_deepseek_client: Optional[AsyncOpenAI] = None
if settings.deepseek_api_key:
    _deepseek_client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url="https://api.deepseek.com")

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


async def _deepseek_attempt(system_prompt: str, user_prompt: str, is_batch: bool, temperature: float) -> str | List[Dict] | None:
    """One DeepSeek call under the strict 15s timeout. Returns the parsed
    result/text on success, or None on timeout / API error / batch-parse failure.
    Never raises — a None return is the signal to retry or fall back."""
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
        return _parse_batch_or_text(text, is_batch, "DeepSeek")
    except (asyncio.TimeoutError, TimeoutError):
        logger.error("[LLM] DeepSeek API timeout (15s).")
        return None
    except Exception as e:
        logger.error(f"[LLM] DeepSeek API Error: {e}.")
        return None


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
            result = await _deepseek_attempt(system_prompt, user_prompt, is_batch, temperature)
            if result is not None:
                logger.info("[LLM] DeepSeek Analysis successful. Pacing pipeline with 2.0s cooldown.")
                await asyncio.sleep(2.0)
                return result

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
