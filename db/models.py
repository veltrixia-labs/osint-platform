import uuid
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, JSON, Text, Enum, select, func, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from db.database import Base

class RawItem(Base):
    __tablename__ = "raw_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fetched_at = Column(DateTime(timezone=True), nullable=False)
    source_system = Column(String, nullable=False)
    source_endpoint = Column(String, nullable=False)
    source_id = Column(String)
    source_group = Column(String)
    reliability_weight = Column(Float)
    payload_json = Column(JSON, nullable=False)
    payload_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Item(Base):
    __tablename__ = "items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type = Column(String)
    dedup_key = Column(String, unique=True, nullable=False)
    published_at = Column(DateTime(timezone=True))
    title = Column(String)
    summary = Column(String)
    source_name = Column(String)
    source_url = Column(String)
    source_id = Column(String)
    source_group = Column(String)
    reliability_weight = Column(Float)
    category = Column(String)
    rough_category = Column(String)  # Stage 1 rough category
    lightweight_score = Column(Float, default=0.0) # Stage 1 relevance score
    cluster_id = Column(UUID(as_uuid=True), ForeignKey("event_clusters.id", ondelete="SET NULL"), nullable=True)
    geo = Column(JSON)
    tags = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Topic(Base):
    __tablename__ = "topics"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_code = Column(String, unique=True, nullable=False)
    topic_name_ja = Column(String)
    topic_name_en = Column(String)
    keywords = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ItemTopic(Base):
    __tablename__ = "item_topics"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"))
    topic_code = Column(String)
    confidence_score = Column(Float)
    matched_keywords = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Report(Base):
    __tablename__ = "reports"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_type = Column(String)                     # daily, weekly, monthly
    plan_required = Column(String, default="free")  # free, pro, experts
    topic_code = Column(String)
    period_start = Column(DateTime(timezone=True))
    period_end = Column(DateTime(timezone=True))
    lang = Column(String)
    model_name = Column(String)
    input_items_hash = Column(String)
    # Content & Identification
    title = Column(String)
    teaser_md = Column(Text)
    content_markdown = Column(String)
    archive_pdf_path = Column(String)
    
    # Substack Integration Metadata
    substack_slug = Column(String, unique=True)
    substack_draft_url = Column(String)
    substack_published_url = Column(String)
    substack_post_status = Column(String, default="draft") # draft, published
    substack_post_id = Column(String)
    
    # Gating & Trust Metrics (Phase 35)
    is_premium = Column(Boolean, default=False)
    source_count = Column(Integer, default=0)
    confidence_level = Column(String, default="Low") # High, Medium, Low
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SignalRanking(Base):
    __tablename__ = "signal_rankings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    signal_type = Column(String)
    period_start = Column(DateTime(timezone=True))
    period_end = Column(DateTime(timezone=True))
    rank = Column(Integer)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"))
    score = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ArticleOutput(Base):
    __tablename__ = "article_outputs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    output_type = Column(String)
    article_type = Column(String)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"))
    topic_code = Column(String)
    lang = Column(String)
    title = Column(String)
    summary = Column(String)
    body_markdown = Column(String)
    cta_text = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class PdfJob(Base):
    __tablename__ = "pdf_jobs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"))
    pdf_type = Column(String)
    is_required = Column(Boolean)
    status = Column(String)
    output_path = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class JobRun(Base):
    __tablename__ = "job_runs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
    error_message = Column(String)

class SourceRegistry(Base):
    __tablename__ = "source_registry"
    source_id = Column(String, primary_key=True)
    source_name = Column(String, nullable=False)
    source_group = Column(String, nullable=False)
    rss_url = Column(String, nullable=False)
    reliability_weight = Column(Float, nullable=False)
    enabled = Column(Boolean, default=True)
    last_checked_at = Column(DateTime(timezone=True))
    last_success_at = Column(DateTime(timezone=True))
    consecutive_failures = Column(Integer, default=0)

class SourceHealthLog(Base):
    __tablename__ = "source_health_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(String, ForeignKey("source_registry.source_id", ondelete="CASCADE"))
    checked_at = Column(DateTime(timezone=True), server_default=func.now())
    success = Column(Boolean, nullable=False)
    entry_count = Column(Integer, default=0)
    error_message = Column(String)

class ReportTriggerLog(Base):
    __tablename__ = "report_trigger_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_code = Column(String, nullable=False)     # e.g. "energy_resource_risk" or "global"
    triggered_at = Column(DateTime(timezone=True), server_default=func.now())
    peak_score = Column(Float)                       # score that triggered the report
    report_type = Column(String)                     # e.g. "event_driven"
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="SET NULL"), nullable=True)

class AnalysisCache(Base):
    __tablename__ = "analysis_cache"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(UUID(as_uuid=True), ForeignKey("items.id", ondelete="CASCADE"), unique=True)
    model_name = Column(String)
    prompt_version = Column(String)
    classification_result = Column(JSON)             # {category, confidence, keep, reason}
    signal_result = Column(JSON)                     # {final_score, novelty, impact}
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    cache_expires_at = Column(DateTime(timezone=True))

class EventCluster(Base):
    __tablename__ = "event_clusters"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    representative_title = Column(String, nullable=False)
    category = Column(String)
    article_count = Column(Integer, default=0)
    source_count = Column(Integer, default=0)
    avg_signal_score = Column(Float, default=0.0)
    metrics_json = Column(JSON) # {purity, distribution, etc.}
    summary_data = Column(JSON) # {themes, keywords, entities}
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ExternalPost(Base):
    __tablename__ = "external_posts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform = Column(String, nullable=False) # e.g., "threads"
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"))
    external_id = Column(String) # media_id or post_id from the platform
    category = Column(String) # e.g. "energy_resource_risk"
    normalized_theme = Column(String, index=True) # Normalized theme key for novelty checks
    status = Column(String) # success, failure
    error_message = Column(String)
    published_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class TrendSignal(Base):
    __tablename__ = "trend_signals"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trend_type = Column(String, nullable=False)  # entity_heat, sector_surge, sustained_event, risk_acceleration
    target_label = Column(String, nullable=False) # e.g. "Iran", "Cyber"
    topic = Column(String)  # Broad category (global, market, etc.)
    intensity_score = Column(Float, default=0.0)
    window_start = Column(DateTime(timezone=True))
    window_end = Column(DateTime(timezone=True))
    description = Column(String)
    metrics_json = Column(JSON) # {baseline, recent, delta, supporting_cluster_count}
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AlertLog(Base):
    __tablename__ = "alert_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_label = Column(String, nullable=False)
    topic = Column(String) # Broad category for gating
    trigger_type = Column(String, nullable=False) # spike, new_pattern, multi_source
    severity = Column(String, default="watch")    # critical, elevated, watch
    triggered_at = Column(DateTime(timezone=True), server_default=func.now())
    intensity = Column(Float)
    feedback_score = Column(Integer) # 1-5 scale
    section_anchor = Column(String) # For deep linking
    related_report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="SET NULL"), nullable=True)
    intelligence_score = Column(Float) # 0.0-1.0 prioritization score
    suppressed = Column(Boolean, default=False)
    status = Column(String, default="pending_evidence") # confirmed, pending_evidence
    is_system_wide = Column(Boolean, default=True)
    supporting_events_count = Column(Integer, default=0)
    fidelity_score = Column(Float, default=0.0) # 0.0-1.0 signal verification score
    is_high_fidelity = Column(Boolean, default=False)
    metadata_json = Column(JSONB) # {delta, source_count, domain_count, visual_path, scoring_breakdown}

class AnalystProfile(Base):
    __tablename__ = "analyst_profiles"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_chat_id = Column(String, unique=True, nullable=False)
    hashed_password = Column(String) # For Phase 27 Auth
    user_role = Column(String, default="analyst") # analyst, admin
    subscription_tier = Column(String, default="free") # free, pro, enterprise
    subscription_expires_at = Column(DateTime(timezone=True), nullable=True)
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    watch_keywords = Column(JSONB) # ["Iran", "Nuclear"]
    watch_entities = Column(JSONB) # ["IRGC", "IAEA"]
    watch_sectors = Column(JSONB)  # ["energy", "defense"]
    min_severity_threshold = Column(String, default="watch")
    min_intelligence_threshold = Column(Float, default=0.35)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_log_id = Column(UUID(as_uuid=True), ForeignKey("alert_logs.id", ondelete="CASCADE"))
    analyst_id = Column(UUID(as_uuid=True), ForeignKey("analyst_profiles.id", ondelete="CASCADE"))
    status = Column(String) # delivered, suppressed
    relevance_score = Column(Float)
    suppression_reason = Column(String)
    delivered_at = Column(DateTime(timezone=True), server_default=func.now())

class SessionRevocation(Base):
    __tablename__ = "session_revocations"
    session_id = Column(UUID(as_uuid=True), primary_key=True)
    version = Column(Integer, default=1)
    revoked = Column(Boolean, default=False)
    revoked_at = Column(DateTime(timezone=True))
    reason = Column(String)

class SecurityLog(Base):
    __tablename__ = "security_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String, nullable=False) # token_reuse, invalid_signature, login_failed
    user_id = Column(UUID(as_uuid=True), nullable=True)
    session_id = Column(UUID(as_uuid=True), nullable=True)
    details = Column(JSONB)
    client_ip = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String, nullable=False, index=True) # preview_view, cta_click, full_view, login_success
    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("analyst_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    metadata_json = Column(JSON) # {utm_source, utm_medium, utm_campaign, visitor_id, etc.}
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class StripeEvent(Base):
    __tablename__ = "stripe_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(String, nullable=False, index=True) # Stripe Event ID
    event_type = Column(String)
    processed_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("event_id", name="uq_stripe_event_id"),
    )

class SystemMetric(Base):
    __tablename__ = "system_metrics"
    metric_key = Column(String, primary_key=True)
    metric_value = Column(String)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
