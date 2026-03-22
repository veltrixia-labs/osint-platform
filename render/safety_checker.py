import logging
import re

logger = logging.getLogger(__name__)

PROHIBITED_PHRASES = [
    "必ず上がる", "絶対儲かる", "買い推奨",
    "must buy", "guaranteed profit", "investment advice"
]

REFUSAL_PHRASES = [
    "blocked due to safety",
    "i cannot fulfill",
    "unable to provide",
    "i can't help with that",
    "i'm unable to",
    "against my safety guidelines"
]

MANDATORY_SECTIONS = [
    "## Summary",
    "## Key Developments",
    "## Potential Implications",
    "## Monitoring Points",
    "## Sources"
]

def check_safety(content: str) -> tuple[bool, str]:
    if not content or len(content) < 500:
        return False, f"Content too short ({len(content) if content else 0} chars)"
        
    content_lower = content.lower()
    
    # 1. Prohibited phrases (Investment advice etc.)
    for phrase in PROHIBITED_PHRASES:
        if phrase.lower() in content_lower:
            return False, f"Prohibited phrase found: {phrase}"
            
    # 2. Refusal Detection
    for phrase in REFUSAL_PHRASES:
        if phrase in content_lower:
            return False, f"LLM refusal detected: {phrase}"
            
    # 3. Structural Validation
    for section in MANDATORY_SECTIONS:
        if section not in content:
            return False, f"Missing mandatory section: {section}"
            
    # 4. Source Verification (Check for at least one markdown link in Sources or general content)
    links = re.findall(r'\[.*?\]\(https?://.*?\)', content)
    if not links:
        return False, "No valid source URLs found in content"
        
    return True, "Passed"
