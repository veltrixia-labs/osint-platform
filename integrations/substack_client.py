import re
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Configuration (In a real scenario, these would be in .env)
# SUBSTACK_DOMAIN = "yourdomain.substack.com"
SUBSTACK_BASE_URL = "https://substack.com" # Fallback

def generate_slug(report) -> str:
    """
    Generates a deterministic, URL-safe slug for a Substack report.
    Format: {topic}-{year}-{month}-{day}
    """
    date_str = report.created_at.strftime("%Y-%m-%d") if report.created_at else datetime.now().strftime("%Y-%m-%d")
    clean_topic = report.topic_code.lower().replace("_", "-")
    slug = f"{clean_topic}-{date_str}"
    
    slug = re.sub(r'[^a-z0-9-]', '', slug)
    return slug

async def create_draft(report) -> dict:
    """
    Simulates creating a Substack draft.
    Returns metadata including draft_url and post_id.
    """
    slug = generate_slug(report)
    logger.info(f"Creating Substack draft for report {report.id} with slug {slug}")
    
    try:
        # Mocking the interaction:
        mock_post_id = f"post_{str(report.id)[:8]}"
        mock_draft_url = f"https://substack.com/publish/post/{mock_post_id}?draft=true"
        
        return {
            "substack_post_id": mock_post_id,
            "substack_draft_url": mock_draft_url,
            "substack_slug": slug,
            "substack_post_status": "draft"
        }
    except Exception as e:
        logger.error(f"Failed to create Substack draft: {e}")
        return {
            "substack_post_id": None,
            "substack_draft_url": SUBSTACK_BASE_URL,
            "substack_slug": slug,
            "substack_post_status": "failed"
        }

async def update_draft(report, new_content: str) -> dict:
    """
    Simulates updating an existing Substack draft.
    """
    logger.info(f"Updating Substack draft for report {report.id} (slug: {report.substack_slug})")
    
    return {
        "substack_post_id": report.substack_post_id,
        "substack_draft_url": report.substack_draft_url,
        "substack_slug": report.substack_slug,
        "substack_post_status": report.substack_post_status
    }

def get_final_url(slug: str) -> str:
    """Constructs the final published URL for a slug."""
    return f"https://yourintelligence.substack.com/p/{slug}"
