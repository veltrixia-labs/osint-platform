import logging
from typing import Optional, Dict, Any, List
from llm.client import generate_analysis

logger = logging.getLogger(__name__)

class GeminiWrapper:
    """
    High-level wrapper for Gemini interactions in the OSINT platform.
    Implements Gemini's recommendation for "OSINT Persona Injection".
    """
    
    DEFAULT_PERSONA = (
        "You are a Senior Intelligence Analyst specializing in OSINT and geopolitical risk. "
        "Your goal is to extract not just primary facts, but secondary and third-order effects "
        "and strategic context from the provided information."
    )

    @staticmethod
    async def analyze_with_context(
        prompt: str, 
        context: str, 
        persona: Optional[str] = None,
        is_batch: bool = False
    ) -> Any:
        """
        Performs analysis with injected persona and context.
        """
        system_instruction = persona or GeminiWrapper.DEFAULT_PERSONA
        user_content = f"CONTEXT DATA:\n{context}\n\nINSTRUCTION:\n{prompt}"
        
        logger.info(f"LLM Request via GeminiWrapper (Batch={is_batch})")
        
        # Delegates to the core health-routing client
        return await generate_analysis(
            system_prompt=system_instruction,
            user_prompt=user_content,
            preferred_model="gemini",
            is_batch=is_batch
        )

    @staticmethod
    async def classify_signals(batch_data: List[Dict]) -> Dict:
        """
        Specialized method for batch signal classification with Confidence Scores.
        [Gemini Recommendation] Includes requirement for confidence and reasoning.
        """
        import json
        prompt = (
            "Classify the following signals. For each signal, provide:\n"
            "1. category (code)\n"
            "2. confidence_score (0.0-1.0)\n"
            "3. reasoning_evidence (short explanation of the score)\n"
            "4. strategic_impact (Potential second-order effects)\n"
            "Strictly return as JSON object with a 'results' key containing the list."
        )
        
        return await GeminiWrapper.analyze_with_context(
            prompt=prompt,
            context=json.dumps(batch_data),
            is_batch=True
        )

    @staticmethod
    async def correlate_events(event_a: str, event_b: str) -> str:
        """
        Strategic correlation between two disparate events.
        [Gemini Recommendation] multidimensional analysis (temporal, subjective, causal).
        """
        prompt = (
            "Analyze the correlation between Event A and Event B across three axes:\n"
            "1. Temporal (Timing and sequence)\n"
            "2. Subjective (Shared actors or organizations)\n"
            "3. Causal (Potential lead-lag or triggering relationship)\n"
            "Identify if these represent a unified strategic trend."
        )
        context = f"EVENT A: {event_a}\n\nEVENT B: {event_b}"
        
        return await GeminiWrapper.analyze_with_context(prompt=prompt, context=context)
