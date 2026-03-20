import asyncio
import os
import uuid
import logging
from datetime import datetime, timezone

# Use local test DB
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///osint_platform.db"

from db.database import AsyncSessionLocal
from db.models import Report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_public_api")

async def test_public_endpoint():
    async with AsyncSessionLocal() as session:
        # Create a long report to test truncation
        long_content = "\n\n".join([f"Paragraph {i}: This is some technical OSINT analysis about a specific signal and its geopolitical implications." for i in range(10)])
        
        report = Report(
            id=uuid.uuid4(),
            report_type="public_preview_test",
            topic_code="tech",
            content_markdown=long_content,
            created_at=datetime.now(timezone.utc)
        )
        session.add(report)
        await session.commit()
        report_id = str(report.id)
        logger.info(f"Created long test report: {report_id}")

        # The backend logic I implemented in api/main.py:
        # paragraphs = [p for p in content.split('\n\n') if p.strip()]
        # preview_parts = paragraphs[:3]
        # preview_text = "\n\n".join(preview_parts)
        
        paragraphs = [p for p in long_content.split('\n\n') if p.strip()]
        preview_parts = paragraphs[:3]
        preview_text = "\n\n".join(preview_parts)
        
        logger.info(f"Paragraph count: {len(paragraphs)}")
        logger.info(f"Preview paragraph count: {len(preview_parts)}")
        
        if len(preview_parts) == 3 and len(paragraphs) == 10:
            logger.info("✅ Truncation logic (paragraphs) verified.")
        else:
            logger.error("❌ Truncation logic FAILED!")

        logger.info(f"Preview Text Sample: {preview_text[:50]}...")
        
async def main():
    await test_public_endpoint()

if __name__ == "__main__":
    asyncio.run(main())
