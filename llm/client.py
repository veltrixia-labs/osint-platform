import asyncio
import logging
import os
import random
import time
import json
from enum import Enum
from typing import Dict, Any, Optional, List, Type
from dataclasses import dataclass, field, asdict
from openai import AsyncOpenAI
from google import genai
from google.genai import types
from config.settings import settings
import httpx


logger = logging.getLogger(__name__)

# --- Types & Enums ---

class LLMErrorCategory(Enum):
    SUCCESS = "success"
    RATE_LIMIT = "rate_limit"
    QUOTA_EXHAUSTED = "quota_exhausted"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    AUTH_ERROR = "auth_error"
    INVALID_REQUEST = "invalid_request"
    UNKNOWN = "unknown"

class BreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
    DISABLED = "disabled"

# --- Adaptive Concurrency Control ---

class AdaptiveConcurrencyGate:
    """
    Manages concurrent requests with an adjustable limit based on performance.
    """
    def __init__(self, initial_max: int = 2, absolute_max: int = 10, min_max: int = 1):
        self.max_concurrent = initial_max
        self.absolute_max = absolute_max
        self.min_max = min_max
        self.current_running = 0
        self._condition = asyncio.Condition()

    async def __aenter__(self):
        async with self._condition:
            while self.current_running >= self.max_concurrent:
                await self._condition.wait()
            self.current_running += 1

    async def __aexit__(self, exc_type, exc, tb):
        async with self._condition:
            self.current_running -= 1
            self._condition.notify_all()

    def adjust_limit(self, success: bool, latency: float, is_rate_limit: bool):
        """AI AIMD-style adjustment (Additive Increase / Multiplicative Decrease)."""
        if is_rate_limit:
            self.max_concurrent = max(self.min_max, int(self.max_concurrent * 0.5))
            logger.warning(f"[Concurrency] Rate limit detected. Scaled down to: {self.max_concurrent}")
        elif success and latency < 2.0:
            if self.max_concurrent < self.absolute_max:
                self.max_concurrent += 1
                logger.info(f"[Concurrency] High performance. Scaled up to: {self.max_concurrent}")
        elif not success and not is_rate_limit:
            # Other failures (timeout/unknown) might suggest overload.
            self.max_concurrent = max(self.min_max, self.max_concurrent - 1)

# --- Cost Guard ---

class CostGuard:
    """Tracks estimated token usage and daily budget."""
    def __init__(self, daily_budget_usd: float = 5.0):
        self.daily_budget_usd = daily_budget_usd
        self.current_usage_usd = 0.0
        self.last_reset_date = time.strftime("%Y-%m-%d")

    def _check_reset(self):
        today = time.strftime("%Y-%m-%d")
        if today != self.last_reset_date:
            logger.info(f"[CostGuard] Daily reset. Previous usage: ${self.current_usage_usd:.4f}")
            self.current_usage_usd = 0.0
            self.last_reset_date = today

    def can_spend(self, estimated_cost: float = 0.01) -> bool:
        self._check_reset()
        return (self.current_usage_usd + estimated_cost) <= self.daily_budget_usd

    def add_cost(self, prompt_tokens: int, completion_tokens: int, model_type: str):
        self._check_reset()
        # Rough estimation (USD per 1M tokens)
        # GPT-4o-mini: ~0.15 prompt / 0.60 completion
        # Gemini 2.0 Flash: ~0.10 prompt / 0.40 completion (simplified)
        if "openai" in model_type or "deepseek" in model_type:
            cost = (prompt_tokens * 0.00000015) + (completion_tokens * 0.00000060)
        elif "ollama" in model_type:
            cost = 0.0 # Local is free
        else:
            cost = (prompt_tokens * 0.00000010) + (completion_tokens * 0.00000040)
        self.current_usage_usd += cost

# --- Provider Logic ---

@dataclass
class ProviderMetrics:
    success_count: int = 0
    failure_count: int = 0
    rate_limit_count: int = 0
    quota_count: int = 0
    timeout_count: int = 0
    total_latency: float = 0.0
    estimated_cost_usd: float = 0.0

    @property
    def avg_latency(self) -> float:
        total = self.success_count + self.failure_count
        return self.total_latency / total if total > 0 else 0.5

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 1.0

    def get_health_score(self) -> float:
        # Score = success_rate / max(avg_latency, 0.1)
        sr = self.success_rate
        lat = max(self.avg_latency, 0.1)
        return sr / lat

class CircuitBreaker:
    def __init__(self, name: str, threshold: int = 5):
        self.name = name
        self.threshold = threshold
        self.failure_count = 0
        self.state = BreakerState.CLOSED
        self.last_failure_time = 0.0
        self.current_reset_timeout = 300.0
        self._lock = asyncio.Lock()
        self.reset_map = {
            LLMErrorCategory.RATE_LIMIT: 60.0,
            LLMErrorCategory.TIMEOUT: 120.0,
            LLMErrorCategory.QUOTA_EXHAUSTED: 86400.0,
            LLMErrorCategory.INSUFFICIENT_FUNDS: 86400.0,
        }

    async def record_failure(self, error_type: LLMErrorCategory):
        async with self._lock:
            self.failure_count += 1
            if error_type in (LLMErrorCategory.QUOTA_EXHAUSTED, LLMErrorCategory.INSUFFICIENT_FUNDS):
                self.state = BreakerState.DISABLED
                self.current_reset_timeout = 86400.0
                self.last_failure_time = time.time()
                return True
            if self.failure_count >= self.threshold:
                self.state = BreakerState.OPEN
                self.current_reset_timeout = self.reset_map.get(error_type, 300.0)
                self.last_failure_time = time.time()
                return True
            return False

    async def record_success(self):
        async with self._lock:
            self.state = BreakerState.CLOSED
            self.failure_count = 0

    async def can_execute(self) -> bool:
        async with self._lock:
            if self.state == BreakerState.CLOSED: return True
            elapsed = time.time() - self.last_failure_time
            if elapsed > self.current_reset_timeout:
                if self.state != BreakerState.HALF_OPEN:
                    logger.info(f"[Breaker] {self.name} HALF-OPEN (Testing).")
                self.state = BreakerState.HALF_OPEN
                return True
            return False

@dataclass
class LLMProvider:
    name: str
    gate: AdaptiveConcurrencyGate
    breaker: CircuitBreaker
    metrics: ProviderMetrics = field(default_factory=ProviderMetrics)

# Global Manager Instances
cost_guard = CostGuard(daily_budget_usd=10.0)
providers: Dict[str, LLMProvider] = {
    "gemini": LLMProvider("gemini", AdaptiveConcurrencyGate(2, 5), CircuitBreaker("Gemini")),
    "openai": LLMProvider("openai", AdaptiveConcurrencyGate(3, 8), CircuitBreaker("OpenAI")),
    "deepseek": LLMProvider("deepseek", AdaptiveConcurrencyGate(3, 10), CircuitBreaker("DeepSeek")),
    "ollama": LLMProvider("ollama", AdaptiveConcurrencyGate(1, 2), CircuitBreaker("Ollama")),
}

model_cache: Dict[str, Any] = {}
_openai_client: Optional[AsyncOpenAI] = None
_gemini_client: Optional[genai.Client] = None
_deepseek_client: Optional[AsyncOpenAI] = None

if settings.openai_api_key:
    _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
if settings.gemini_api_key:
    _gemini_client = genai.Client(api_key=settings.gemini_api_key)
if settings.deepseek_api_key:
    _deepseek_client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url="https://api.deepseek.com")

def get_gemini_model(model_name: str, system_prompt: str) -> Dict[str, str]:
    """Thin compatibility wrapper for the new google-genai Client API."""
    return {"model": model_name, "system_instruction": system_prompt}

# --- Core Logic ---

def get_full_jitter_backoff(attempt: int, base: float = 2.0, cap: float = 30.0) -> float:
    """AWS Recommended Full Jitter: random(0, min(cap, base * 2^attempt))"""
    v = min(cap, base * 2**attempt)
    return random.uniform(0, v)

async def generate_with_retry(provider_name: str, system_prompt: str, user_prompt: str, model_name: str) -> Optional[str]:
    p = providers[provider_name]
    if not await p.breaker.can_execute(): return None
    if provider_name == "openai" and not cost_guard.can_spend():
        logger.warning("[CostGuard] OpenAI budget exceeded. Blocking request.")
        return None

    for attempt in range(4):
        start_time = time.time()
        try:
            async with p.gate:
                if provider_name == "gemini":
                    model_cfg = get_gemini_model(model_name, system_prompt)
                    response = await _gemini_client.aio.models.generate_content(
                        model=model_cfg["model"],
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=model_cfg["system_instruction"],
                            temperature=0.7
                        )
                    )
                    text = response.text
                elif provider_name == "deepseek":
                    response = await _deepseek_client.chat.completions.create(
                        model=model_name,
                        messages=[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}],
                        temperature=0.7
                    )
                    text = response.choices[0].message.content
                    cost_guard.add_cost(len(user_prompt)//4, len(text)//4, "deepseek")
                elif provider_name == "ollama":
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            f"{settings.ollama_base_url}/api/generate",
                            json={
                                "model": model_name,
                                "prompt": f"{system_prompt}\n\n{user_prompt}",
                                "stream": False,
                                "options": {"temperature": 0.7}
                            },
                            timeout=120.0
                        )
                        response.raise_for_status()
                        text = response.json().get("response", "")
                else:
                    response = await asyncio.wait_for(
                        _openai_client.chat.completions.create(
                            model=model_name,
                            messages=[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}],
                            temperature=0.7
                        ), timeout=60.0)
                    text = response.choices[0].message.content
                    cost_guard.add_cost(len(user_prompt)//4, len(text)//4, "openai") # Very rough token estimate

                latency = time.time() - start_time
                p.metrics.success_count += 1
                p.metrics.total_latency += latency
                p.gate.adjust_limit(True, latency, False)
                await p.breaker.record_success()
                return text
        except Exception as e:
            err_str = str(e).lower()
            is_rate = "429" in err_str or "rate_limit" in err_str or "resource_exhausted" in err_str
            is_quota = "quota" in err_str or "billing" in err_str
            
            p.metrics.failure_count += 1
            if is_rate: p.metrics.rate_limit_count += 1
            if is_quota: p.metrics.quota_count += 1
            
            p.gate.adjust_limit(False, time.time()-start_time, is_rate)
            cat = LLMErrorCategory.RATE_LIMIT if is_rate else (LLMErrorCategory.QUOTA_EXHAUSTED if is_quota else LLMErrorCategory.UNKNOWN)
            await p.breaker.record_failure(cat)

            if is_rate and attempt < 3:
                wait = get_full_jitter_backoff(attempt + 1)
                logger.warning(f"[{provider_name}] Retry {attempt+1} due to rate limit. Waiting {wait:.2f}s...")
                await asyncio.sleep(wait)
            else:
                return None
    return None

async def generate_batch_analysis(provider_name: str, system_prompt: str, user_prompt: str, model_name: str) -> Optional[str]:
    """Specific variant for batch processing to ensure failure doesn't block the whole pipeline if one provider fails."""
    return await generate_with_retry(provider_name, system_prompt, user_prompt, model_name)

async def generate_analysis(system_prompt: str, user_prompt: str, preferred_model: str = "deepseek", is_batch: bool = False) -> str | List[Dict]:
    # Health-based Scoring & Routing
    scored_providers = []
    for name, p in providers.items():
        if await p.breaker.can_execute():
            score = p.metrics.get_health_score()
            if name == preferred_model: score *= 1.2
            scored_providers.append((name, score))
    
    scored_providers.sort(key=lambda x: x[1], reverse=True)
    
    for p_name, score in scored_providers:
        logger.info(f"Routing to {p_name} (Health Score: {score:.3f}, Batch: {is_batch})")
        
        # Model Selection Mapping
        if p_name == "gemini": int_model = "gemini-2.0-flash"
        elif p_name == "openai": int_model = "gpt-4o-mini"
        elif p_name == "deepseek": int_model = "deepseek-chat"
        elif p_name == "ollama": int_model = "llama3" # Default local model
        else: int_model = "gpt-4o-mini"
        
        if is_batch:
            res = await generate_batch_analysis(p_name, system_prompt, user_prompt, int_model)
        else:
            res = await generate_with_retry(p_name, system_prompt, user_prompt, int_model)
            
        if res:
            if is_batch:
                try:
                    # Try to extract JSON from markdown if necessary
                    cleaned = res.strip()
                    if cleaned.startswith("```json"):
                        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
                    elif cleaned.startswith("```"):
                        cleaned = cleaned.split("```")[1].split("```")[0].strip()
                    return json.loads(cleaned)
                except Exception as e:
                    logger.error(f"Failed to parse batch JSON: {e}")
                    continue # Try next provider
            return res

    return "__DEGRADED_MODE__" if is_batch else "## Mock Analysis\nSystem busy or quota exceeded.\n"

def get_metrics_summary() -> str:
    summary = {name: asdict(p.metrics) for name, p in providers.items()}
    for name in summary:
        summary[name]["breaker_state"] = providers[name].breaker.state.value
        summary[name]["concurrency_limit"] = providers[name].gate.max_concurrent
        summary[name]["health_score"] = providers[name].metrics.get_health_score()
    
    summary["cost_guard"] = {"daily_usage_usd": cost_guard.current_usage_usd, "budget_usd": cost_guard.daily_budget_usd}
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "outputs", "health_metrics.json"), "w", encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    
    lines = ["--- Professional LLM Ops Metrics ---"]
    for n, m in summary.items():
        if n == "cost_guard": continue
        lines.append(f"[{n.upper()}] Success: {m['success_count']}, Score: {m['health_score']:.2f}, Limit: {m['concurrency_limit']}, State: {m['breaker_state']}")
    lines.append(f"[COST] Today: ${cost_guard.current_usage_usd:.4f} / ${cost_guard.daily_budget_usd:.2f}")
    return "\n".join(lines)
