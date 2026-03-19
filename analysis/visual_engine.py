import os
import logging
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from sqlalchemy import desc
from db.models import TrendSignal, EventCluster, Item
from typing import Optional, List

logger = logging.getLogger(__name__)

class AnalystPlotStyle:
    BG_COLOR = "#121212"
    TEXT_COLOR = "#E0E0E0"
    PRIMARY_COLOR = "#00FF41" # Matrix Green
    SECONDARY_COLOR = "#007BFF" # Contrast Blue
    ACCENT_COLOR = "#FF3131" # Risk Red
    GRID_COLOR = "#2A2A2A"
    FONT_SIZE_TITLE = 14
    FONT_SIZE_LABEL = 10
    DPI = 200

    @classmethod
    def apply(cls, ax, title: str, xlabel: str, ylabel: str):
        ax.set_facecolor(cls.BG_COLOR)
        ax.set_title(title, color=cls.TEXT_COLOR, fontsize=cls.FONT_SIZE_TITLE, pad=20)
        ax.set_xlabel(xlabel, color=cls.TEXT_COLOR, fontsize=cls.FONT_SIZE_LABEL)
        ax.set_ylabel(ylabel, color=cls.TEXT_COLOR, fontsize=cls.FONT_SIZE_LABEL)
        
        ax.tick_params(colors=cls.TEXT_COLOR, which='both', labelsize=8)
        ax.spines['bottom'].set_color(cls.GRID_COLOR)
        ax.spines['top'].set_color(cls.GRID_COLOR)
        ax.spines['left'].set_color(cls.GRID_COLOR)
        ax.spines['right'].set_color(cls.GRID_COLOR)
        ax.grid(True, color=cls.GRID_COLOR, linestyle='--', alpha=0.5)

async def generate_intensity_chart(db, target_label: str, topic: str, date_str: str) -> Optional[str]:
    """Generates a 7-day intensity line chart for a specific trend."""
    try:
        now = datetime.now(timezone.utc)
        start_date = now - timedelta(days=7)
        
        stmt = select(TrendSignal).where(
            TrendSignal.target_label == target_label,
            TrendSignal.created_at >= start_date
        ).order_by(TrendSignal.created_at.asc())
        
        signals = (await db.execute(stmt)).scalars().all()
        if not signals:
            return None
        
        dates = [s.created_at for s in signals]
        intensities = [s.intensity_score for s in signals]
        
        fig, ax = plt.subplots(figsize=(10, 5), facecolor=AnalystPlotStyle.BG_COLOR)
        AnalystPlotStyle.apply(ax, f"Trend Intensity: {target_label}", "Timeline", "Intensity Score (0.0 - 10.0)")
        
        ax.plot(dates, intensities, color=AnalystPlotStyle.PRIMARY_COLOR, linewidth=2, marker='o', markersize=4)
        ax.fill_between(dates, intensities, color=AnalystPlotStyle.PRIMARY_COLOR, alpha=0.1)
        
        ax.set_ylim(0, 10.5)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
        plt.xticks(rotation=45)
        
        filename = f"visual_{topic}_{date_str}_{target_label.replace(' ', '_').lower()}_intensity.png"
        out_path = _get_output_path(filename)
        fig.savefig(out_path, dpi=AnalystPlotStyle.DPI, bbox_inches='tight')
        plt.close(fig)
        
        return filename
    except Exception as e:
        logger.error(f"Failed to generate intensity chart for {target_label}: {e}")
        return None

async def generate_diversity_chart(db, cluster_id, topic: str, date_str: str) -> Optional[str]:
    """Generates a source diversity bar chart for a specific cluster."""
    try:
        cluster = (await db.execute(select(EventCluster).where(EventCluster.id == cluster_id))).scalar_one_or_none()
        if not cluster:
            return None
            
        stmt = select(Item).where(Item.cluster_id == cluster_id)
        items = (await db.execute(stmt)).scalars().all()
        
        source_counts = {}
        for it in items:
            source = it.source_name or "Unknown"
            source_counts[source] = source_counts.get(source, 0) + 1
            
        if not source_counts:
            return None
            
        sorted_sources = sorted(source_counts.items(), key=lambda x: x[1], reverse=True)[:8]
        names = [x[0] for x in sorted_sources]
        counts = [x[1] for x in sorted_sources]
        
        fig, ax = plt.subplots(figsize=(10, 5), facecolor=AnalystPlotStyle.BG_COLOR)
        AnalystPlotStyle.apply(ax, f"Source Diversity: {cluster.representative_title[:50]}...", "Source Name", "Article Count")
        
        bars = ax.bar(names, counts, color=AnalystPlotStyle.SECONDARY_COLOR, alpha=0.8)
        # Gradient effect (manual)
        for i, bar in enumerate(bars):
            if i == 0: bar.set_color(AnalystPlotStyle.PRIMARY_COLOR)
            
        plt.xticks(rotation=45, ha='right')
        
        filename = f"visual_{topic}_{date_str}_{cluster_id.hex[:8]}_diversity.png"
        out_path = _get_output_path(filename)
        fig.savefig(out_path, dpi=AnalystPlotStyle.DPI, bbox_inches='tight')
        plt.close(fig)
        
        return filename
    except Exception as e:
        logger.error(f"Failed to generate diversity chart for cluster {cluster_id}: {e}")
        return None

def _get_output_path(filename: str) -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    visuals_dir = os.path.join(base_dir, "outputs", "visuals")
    os.makedirs(visuals_dir, exist_ok=True)
    return os.path.join(visuals_dir, filename)
