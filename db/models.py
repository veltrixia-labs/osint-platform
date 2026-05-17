import uuid
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Date, ForeignKey, JSON, Text, Enum, select, func, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from db.database import Base

class RawItem(Base):
    __tablename__ = "raw_items"
    __table_args__ = (
        Index("ix_raw_items_payload_hash_unique", "payload_hash", unique=True),
    )
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
    location_lat = Column(Float)
    location_lng = Column(Float)
    
    # Intelligence UI payload
    structured_payload = Column(JSONB, nullable=True)
    
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
    container_id = Column(String)  # Threads 2-step flow: container ID before publish
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
    location_lat = Column(Float)
    location_lng = Column(Float)
    metadata_json = Column(JSONB) # {delta, source_count, domain_count, visual_path, scoring_breakdown}

class AnalystProfile(Base):
    __tablename__ = "analyst_profiles"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_chat_id = Column(String, unique=True, nullable=True) # Now optional
    email = Column(String, unique=True, nullable=True)           # New Primary ID
    is_email_verified = Column(Boolean, default=False)
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

# --- Phase 4: Cascading Impact & Self-Learning Engine ---

class Stakeholder(Base):
    __tablename__ = "stakeholders"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    ticker = Column(String, index=True)
    sector = Column(String)
    country = Column(String)
    domain = Column(String, nullable=False) # ai_semi, market, energy, supply_chain, defense, crypto, digital_infra
    description = Column(Text)
    location_lat = Column(Float)
    location_lng = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # [v10.21] Entity Lifecycle Management — Hybrid Backbone/Tactical Architecture
    is_auto_provisioned = Column(Boolean, default=True)   # False = backbone (永続保護), True = AI auto-added (削除候補)
    strategic_score = Column(Float, default=0.0)          # 多次元優先スコア (0.0〜1.0)
    hit_count = Column(Integer, default=0)                 # 波及予測で参照された累計回数
    last_hit_at = Column(DateTime(timezone=True), nullable=True)  # 最終参照日時

class Dependency(Base):
    __tablename__ = "dependencies"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("stakeholders.id", ondelete="CASCADE"), nullable=False)
    target_id = Column(UUID(as_uuid=True), ForeignKey("stakeholders.id", ondelete="CASCADE"), nullable=False)
    dependency_type = Column(String) # supplier, competitor, subsidiary, regulator
    exposure_weight = Column(Float, default=0.5) # 0.0-1.0
    beta_correlation = Column(Float, default=1.0) # correlation with macro/trigger
    substitution_elasticity = Column(Float, default=0.5) # 0.0-1.0
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source_id", "target_id", name="uq_dependency_pair"),
    )

class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prediction_id = Column(String, unique=True, nullable=False)
    trigger_event = Column(Text)
    target_id = Column(UUID(as_uuid=True), ForeignKey("stakeholders.id", ondelete="CASCADE"), nullable=False)
    predicted_alpha = Column(Float) # Expected movement relative to baseline
    baseline_index_ticker = Column(String, default="^GSPC") # S&P 500 default
    time_horizon_days = Column(Integer, default=7)
    confidence_score = Column(Float)
    is_evaluated = Column(Boolean, default=False)
    actual_alpha = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    evaluated_at = Column(DateTime(timezone=True))

# --- BEA Economic Data ---

class BEAGDPByIndustry(Base):
    """BEA GDP by Industry normalized data points.

    Each row represents a single (dataset, table, frequency, year, quarter, industry)
    data point from the BEA API.  The UNIQUE constraint enables safe UPSERT on
    repeated fetches and BEA data revisions.
    """
    __tablename__ = "bea_gdp_by_industry"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_name = Column(String(64), nullable=False)           # e.g. "GDPbyIndustry"
    table_id = Column(String(16), nullable=False)               # e.g. "1", "5", "25"
    frequency = Column(String(4), nullable=False)               # "A" (Annual) / "Q" (Quarterly)
    year = Column(String(8), nullable=False)                    # e.g. "2022"
    quarter = Column(String(8), nullable=False)                 # Annual: "2022" / Quarterly: "2022Q1"
    industry = Column(String(16), nullable=False)               # BEA industry code e.g. "11", "3361MV"
    industry_description = Column(String(256))                  # Human-readable name
    data_value = Column(Float)                                  # Numeric value; NULL if unparseable
    note_ref = Column(String(32))                               # BEA NoteRef e.g. "1", "1;1.1.A"
    note_text = Column(Text)                                    # Resolved note text
    statistic = Column(String(128))                             # BEA Statistic field
    utc_production_time = Column(String(32))                    # BEA response timestamp (raw string)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    raw_json = Column(JSON)                                     # Original row dict for audit

    __table_args__ = (
        UniqueConstraint(
            "dataset_name", "table_id", "frequency",
            "year", "quarter", "industry",
            name="uq_bea_gdp_data_point"
        ),
        Index("ix_bea_gdp_year_industry", "year", "industry"),
        Index("ix_bea_gdp_fetched_at", "fetched_at"),
    )


class BEANIPAObservation(Base):
    """BEA NIPA (National Income and Product Accounts) normalized data points.

    Each row represents a single observation in a NIPA table.
    The UNIQUE constraint is based on dataset, table, line number, and time period.
    """
    __tablename__ = "bea_nipa_observations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_name = Column(String(64), nullable=False)           # e.g. "NIPA"
    table_name = Column(String(16), nullable=False)             # e.g. "T10101"
    series_code = Column(String(16))                            # e.g. "A191RC"
    line_number = Column(String(8), nullable=False)             # Row number in table
    line_description = Column(String(256))                      # e.g. "Gross domestic product"
    time_period = Column(String(16), nullable=False)            # e.g. "2024", "2024Q1"
    frequency = Column(String(4), nullable=False)               # "A", "Q", "M"
    metric_name = Column(String(64))                            # e.g. "Current Dollars"
    cl_unit = Column(String(64))                                # e.g. "Level"
    unit_mult = Column(Integer)                                 # Scale (6 = Millions)
    data_value = Column(Float)                                  # Numeric value
    note_ref = Column(String(32))                               # BEA NoteRef
    statistic = Column(String(128))                             # BEA Statistic field
    utc_production_time = Column(String(32))                    # BEA response timestamp
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    raw_json = Column(JSON)                                     # Original row dict

    __table_args__ = (
        UniqueConstraint(
            "dataset_name", "table_name", "line_number",
            "time_period", "frequency",
            name="uq_bea_nipa_data_point"
        ),
        Index("ix_bea_nipa_table_line", "table_name", "line_number"),
        Index("ix_bea_nipa_table_period", "table_name", "time_period"),
        Index("ix_bea_nipa_series_code", "series_code"),
        Index("ix_bea_nipa_fetched_at", "fetched_at"),
    )


class BLSPPIObservation(Base):
    """BLS PPI (Producer Price Index) normalized data points.

    Each row represents a single monthly observation for a specific PPI series.
    The UNIQUE constraint is based on source, dataset, series, and date.
    """
    __tablename__ = "bls_ppi_observations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String(16), nullable=False)                 # e.g. "BLS"
    dataset_name = Column(String(32), nullable=False)           # e.g. "PPI"
    series_id = Column(String(32), nullable=False)               # e.g. "WPUFD4"
    series_name = Column(String(256))                            # e.g. "PPI Final demand"
    year = Column(Integer, nullable=False)                       # e.g. 2024
    period = Column(String(4), nullable=False)                   # e.g. "M12"
    period_name = Column(String(16))                             # e.g. "December"
    date = Column(String(10), nullable=False)                    # e.g. "2024-12"
    value = Column(Float)                                        # Index value
    footnotes = Column(JSON)                                     # BLS footnotes array
    latest = Column(Boolean, nullable=False, default=False)      # True for most recent monthly value
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    raw_json = Column(JSON)                                     # Original observation dict

    __table_args__ = (
        UniqueConstraint(
            "source", "dataset_name", "series_id", "date",
            name="uq_bls_ppi_data_point"
        ),
        Index("ix_bls_ppi_series_date", "series_id", "date"),
        Index("ix_bls_ppi_date", "date"),
        Index("ix_bls_ppi_latest", "latest"),
        Index("ix_bls_ppi_fetched_at", "fetched_at"),
    )


# --- Generic External Data Consolidation Layer ---

class ExternalDataSeries(Base):
    """Catalog of external data series (FRED, BLS, WB, etc.)"""
    __tablename__ = "external_data_series"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String, index=True, nullable=False) # e.g. "fred", "bls", "worldbank"
    series_id = Column(String, index=True, nullable=False) # e.g. "FEDFUNDS"
    name = Column(String, nullable=False)
    unit = Column(String)
    frequency = Column(String)
    category = Column(String)
    pro_use = Column(String)
    geography = Column(String)
    metadata_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("source", "series_id", name="uq_external_series_id"),
    )

class ExternalObservation(Base):
    """Generic time-series observation for single-value points."""
    __tablename__ = "external_observations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    series_ref_id = Column(UUID(as_uuid=True), ForeignKey("external_data_series.id", ondelete="CASCADE"), nullable=False)
    source = Column(String, index=True, nullable=False)
    series_id = Column(String, index=True, nullable=False)
    date = Column(Date, index=True, nullable=False)
    period_label = Column(String) # e.g. "2024Q1", "M12"
    value = Column(Float)
    is_latest = Column(Boolean, default=False)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
    raw_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "series_id", "date", "period_label", name="uq_external_observation"),
    )

class ExternalTradeFlow(Base):
    """Specialized trade data (Comtrade, Census Trade)."""
    __tablename__ = "external_trade_flows"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String, index=True, nullable=False)
    reporter_id = Column(String, index=True, nullable=False)
    reporter_name = Column(String)
    partner_id = Column(String, index=True, nullable=False)
    partner_name = Column(String)
    flow_type = Column(String, index=True) # M (Import), X (Export)
    commodity_id = Column(String, index=True) # HS Code
    commodity_name = Column(String)
    year = Column(Integer, index=True)
    period = Column(String) # e.g. "2023", "2023-01"
    trade_value = Column(Float)
    quantity = Column(Float)
    unit = Column(String)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
    raw_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "reporter_id", "partner_id", "flow_type", "commodity_id", "year", "period", name="uq_external_trade_flow"),
    )

class ExternalIndustryStat(Base):
    """Cross-sectional industry and geo-based statistics (BEA, Census CBP)."""
    __tablename__ = "external_industry_stats"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String, index=True, nullable=False)
    dataset = Column(String, index=True) # e.g. "GDPbyIndustry", "CBP"
    geo_id = Column(String, index=True) # FIPS, ISO
    geo_name = Column(String)
    industry_id = Column(String, index=True) # NAICS, BEA Code
    industry_name = Column(String)
    metric_name = Column(String, index=True, nullable=False) # e.g. "GDP", "EMP"
    year = Column(Integer, index=True)
    period = Column(String)
    value = Column(Float)
    unit = Column(String)
    metadata_json = Column(JSONB)
    raw_json = Column(JSONB)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "dataset", "geo_id", "industry_id", "metric_name", "year", "period", name="uq_external_industry_stat"),
    )

class ExternalDataFetchLog(Base):
    """Logging for external data acquisition jobs."""
    __tablename__ = "external_data_fetch_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String, index=True, nullable=False)
    job_name = Column(String, index=True, nullable=False)
    status = Column(String, index=True) # success, failed, partial
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
    rows_fetched = Column(Integer, default=0)
    rows_saved = Column(Integer, default=0)
    error_message = Column(Text)
    metadata_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class MarketDataInstrument(Base):
    """Catalog of market instruments (ETFs, Indices, FX pairs, Crypto, etc.)"""
    __tablename__ = "market_data_instruments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider = Column(String, index=True, nullable=False) # e.g. "alpha_vantage", "frankfurter"
    symbol = Column(String, index=True, nullable=False) # e.g. "SPY", "USDJPY"
    name = Column(String, nullable=False)
    asset_class = Column(String, index=True, nullable=False) # equity, etf, index, fx, commodity, crypto, rates_proxy
    domain_ids = Column(JSON, nullable=True) # List of domains this instrument is relevant for
    quote_currency = Column(String) # e.g. "USD"
    base_currency = Column(String) # For FX/Crypto
    metadata_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("provider", "symbol", name="uq_market_instrument"),
    )

class MarketDataPrice(Base):
    """Historical and daily market price data."""
    __tablename__ = "market_data_prices"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_id = Column(UUID(as_uuid=True), ForeignKey("market_data_instruments.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String, index=True, nullable=False)
    symbol = Column(String, index=True, nullable=False)
    date = Column(Date, index=True, nullable=False)
    interval = Column(String, index=True, default="daily") # daily, 15min, etc.
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    adjusted_close = Column(Float)
    volume = Column(Float)
    raw_json = Column(JSONB)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("provider", "symbol", "date", "interval", name="uq_market_data_price"),
    )

class MarketDataFetchLog(Base):
    """Logging for market data acquisition jobs."""
    __tablename__ = "market_data_fetch_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider = Column(String, index=True, nullable=False)
    job_name = Column(String, index=True, nullable=False)
    status = Column(String, index=True) # running, success, partial, failed
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
    instruments_requested = Column(Integer, default=0)
    rows_fetched = Column(Integer, default=0)
    rows_saved = Column(Integer, default=0)
    error_message = Column(Text)
    metadata_json = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
