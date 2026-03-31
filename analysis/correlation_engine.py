import logging
import json
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from db.models import Item, EventCluster, AlertLog
from llm.wrapper import GeminiWrapper

logger = logging.getLogger(__name__)

class CorrelationEngine:
    """
    Strategic Correlation Analysis Engine.
    [Gemini Recommendation] Focuses on temporal, subjective, and causal axes.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.wrapper = GeminiWrapper()

    async def find_strategic_patterns(self, lookback_hours: int = 24) -> List[Dict]:
        """
        Scans recent alerts and clusters to find non-obvious correlations.
        """
        logger.info(f"Starting strategic correlation scan (lookback: {lookback_hours}h)")
        
        # 1. Fetch recent high-intelligence alerts
        stmt = select(AlertLog).where(AlertLog.status == "confirmed").order_by(AlertLog.triggered_at.desc()).limit(10)
        alerts = (await self.db.execute(stmt)).scalars().all()
        
        if len(alerts) < 2:
            logger.info("Insufficient active alerts for correlation analysis.")
            return []

        # 2. Pairwise correlation check (Sampled for efficiency)
        correlations = []
        for i in range(len(alerts)):
            for j in range(i + 1, min(i + 4, len(alerts))): # Check top 3 pairs per alert
                a1 = alerts[i]
                a2 = alerts[j]
                
                # LLM-based multidimensional check
                analysis = await self.wrapper.correlate_events(
                    event_a=f"{a1.target_label} ({a1.trigger_type})",
                    event_b=f"{a2.target_label} ({a2.trigger_type})"
                )
                
                if analysis and "unified strategic trend" in analysis.lower():
                    correlations.append({
                        "alert_a_id": str(a1.id),
                        "alert_b_id": str(a2.id),
                        "analysis": analysis,
                        "primary_labels": [a1.target_label, a2.target_label]
                    })
        
        return correlations

    async def extract_second_order_effects(self, cluster_id: str) -> Optional[str]:
        """
        Extracts strategic context and wave effects for a specific event cluster.
        """
        stmt = select(EventCluster).where(EventCluster.id == cluster_id)
        cluster = (await self.db.execute(stmt)).scalar_one_or_none()
        
        if not cluster:
            return None
            
        context = (
            f"REPRESENTATIVE TITLE: {cluster.representative_title}\n"
            f"SUMMARY: {json.dumps(cluster.summary_data)}\n"
            f"METRICS: {json.dumps(cluster.metrics_json)}"
        )
        
        prompt = (
            "Analyze this event cluster and extract strictly SECOND-ORDER EFFECTS. "
            "How does this event impact supply chains, market sentiment, or diplomatic relations "
            "beyond the immediate event itself? Identify potential 'unintended consequences'."
        )
        
        return await self.wrapper.analyze_with_context(prompt=prompt, context=context)
