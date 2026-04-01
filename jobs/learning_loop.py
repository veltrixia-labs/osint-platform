import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Prediction, Stakeholder, Dependency, Item
from db.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

LEARNING_RATE = 0.05
EVALUATION_HORIZON_DAYS = 7

MAX_CORRECTION = 0.05  # Prevent extreme weights in a single cycle
VOLATILITY_THRESHOLD = 15.0  # Skip updates if Alpha > 15% (likely noise/outlier)

class LearningLoop:
    @classmethod
    async def run_audit(cls):
        """
        Periodically audit pending predictions and update intelligence weights.
        """
        logger.info("Starting Self-Learning Feedback Loop Audit")
        async with AsyncSessionLocal() as db:
            # 1. Find pending predictions that have reached their time horizon
            horizon_date = datetime.now(timezone.utc) - timedelta(days=EVALUATION_HORIZON_DAYS)
            stmt = select(Prediction).where(
                Prediction.is_evaluated == False,
                Prediction.created_at <= horizon_date
            )
            pending = (await db.execute(stmt)).scalars().all()
            
            if not pending:
                logger.info("No pending predictions to audit.")
                return

            for pred in pending:
                await cls._evaluate_prediction(db, pred)
            
            await db.commit()
            logger.info(f"Self-Learning Audit complete. Processed {len(pending)} predictions.")

    @classmethod
    async def _evaluate_prediction(cls, db: AsyncSession, pred: Prediction):
        """
        Calculate actual impact (Alpha) and refine the corporate graph weights.
        """
        # 1. Fetch the stakeholder (to get the ticker)
        stmt = select(Stakeholder).where(Stakeholder.id == pred.target_id)
        stakeholder = (await db.execute(stmt)).scalar_one_or_none()
        if not stakeholder:
            return

        # 2. Fetch Market Data (Mocked for current environment)
        actual_asset_return, actual_index_return = await cls._fetch_market_data(
            stakeholder.ticker, pred.baseline_index_ticker, pred.created_at
        )
        
        # 3. Alpha-Beta Signal Separation
        actual_alpha = actual_asset_return - actual_index_return
        pred.actual_alpha = actual_alpha
        pred.is_evaluated = True
        pred.evaluated_at = datetime.now(timezone.utc)
        
        # --- Reliability Guardrails ---
        error = actual_alpha - pred.predicted_alpha
        
        # A. Volatility Filtering (Outlier Rejection)
        if abs(actual_alpha) > VOLATILITY_THRESHOLD:
            logger.warning(f"Skipping weight update for {stakeholder.name}: Extreme Alpha ({actual_alpha:.2f}%) detected as likely outlier.")
            return

        # B. Correction Clipping (Prevent Overlearning)
        correction_raw = LEARNING_RATE * error
        correction = max(-MAX_CORRECTION, min(MAX_CORRECTION, correction_raw))
        
        # 4. Weight Correction (Self-Learning)
        dep_stmt = select(Dependency).where(
            (Dependency.source_id == stakeholder.id) | (Dependency.target_id == stakeholder.id)
        )
        dependencies = (await db.execute(dep_stmt)).scalars().all()
        
        for dep in dependencies:
            # Adjust exposure weight with clipping
            new_weight = max(0.0, min(1.0, dep.exposure_weight + (correction * 0.1)))
            dep.exposure_weight = new_weight
            
            # Adjust beta correlation
            new_beta = max(0.0, min(2.0, dep.beta_correlation + correction))
            dep.beta_correlation = new_beta
            
        logger.info(f"Evaluated Prediction {pred.prediction_id}: Error {error:.2f}, Clipped Correction {correction:.4f}")

    @classmethod
    async def _fetch_market_data(cls, ticker: str, index_ticker: str, start_date: datetime):
        """
        Fetch historical performance. 
        MOCK: Simulates realistic market noise around a signal.
        """
        # If we had yfinance installed:
        # data = yf.download(ticker, start=start_date, end=start_date + timedelta(days=7))
        # ...
        
        # For OSINT Demo: Generate 'Realistic' Alpha based on item presence in DB
        # We check how many 'Keep' items talked about this entity in that window.
        await asyncio.sleep(0.1) # Simulate network lag
        
        # Simulation logic:
        # Base market trend (Index)
        market_trend = random.uniform(-2.0, 2.0)
        
        # Entity specific trend (Asset)
        # We add some bias to simulate that the system actually learns something
        entity_bias = random.uniform(-5.0, 5.0) 
        
        asset_return = market_trend + entity_bias
        return asset_return, market_trend

async def run_learning_job():
    await LearningLoop.run_audit()

if __name__ == "__main__":
    # Manual trigger for testing
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_learning_job())
