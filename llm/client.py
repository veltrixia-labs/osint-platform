import asyncio
import logging
import os
import time
import json
from enum import Enum
from typing import Dict, Any, Optional, List
from openai import AsyncOpenAI
from config.settings import settings

logger = logging.getLogger(__name__)

# Strict Global Throttle to prevent Thundering Herd
_global_llm_semaphore = asyncio.Semaphore(1)

_deepseek_client: Optional[AsyncOpenAI] = None
if settings.deepseek_api_key:
    _deepseek_client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url="https://api.deepseek.com")

async def generate_analysis(system_prompt: str, user_prompt: str, is_batch: bool = False, **kwargs) -> str | List[Dict] | None:
    """
    Step 1: Single path DeepSeek execution. No fallback, no automatic provider hopping.
    If it fails, it fails fast.
    """
    if not _deepseek_client:
        logger.error("[LLM] DeepSeek API key not configured. Analysis failed.")
        return None

    async with _global_llm_semaphore:
        logger.info("[LLM] Sending request to DeepSeek (Fail-Fast Mode)")
        try:
            # Enforce strict 15s timeout. If DeepSeek is saturated, we fail fast instead of hanging.
            response = await asyncio.wait_for(
                _deepseek_client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7
                ), 
                timeout=15.0
            )
            
            text = response.choices[0].message.content
            
            logger.info("[LLM] DeepSeek Analysis successful. Pacing pipeline with 2.0s cooldown.")
            await asyncio.sleep(2.0)
            
            if is_batch:
                try:
                    cleaned = text.strip()
                    if cleaned.startswith("```json"):
                        cleaned = cleaned.split("```json")[1].split("```")[0].strip()
                    elif cleaned.startswith("```"):
                        cleaned = cleaned.split("```")[1].split("```")[0].strip()
                    return json.loads(cleaned)
                except Exception as e:
                    logger.error(f"[LLM] Failed to parse batch JSON from DeepSeek: {e}")
                    return None
                    
            return text
            
        except (asyncio.TimeoutError, TimeoutError):
            logger.error("[LLM] DeepSeek API timeout (15s). Failing fast.")
            return None
        except Exception as e:
            logger.error(f"[LLM] DeepSeek API Error: {e}. Failing fast.")
            return None

def get_metrics_summary() -> str:
    """Mock metrics to satisfy any UI imports without crashing."""
    return "--- DeepSeek Single-Path Pipeline ---\nStatus: Active\nModes: Fail-Fast, Throttled"
