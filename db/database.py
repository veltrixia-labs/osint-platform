import ssl
import logging
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import os
import sqlalchemy
from alembic.config import Config
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from config.settings import settings

logger = logging.getLogger(__name__)

def mask_url(url: str) -> str:
    """Mask credentials in a DB URL for safe logging."""
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://****:****@{parsed.hostname}{parsed.path}"
    except:
        return "****"

def is_internal_render_host(url: str) -> bool:
    """Detect if the DB URL points to a Render internal service."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        # 1. Start with 'dpg-' (Render private database prefix)
        if hostname.startswith("dpg-"): return True
        # 2. Hostname has no dots (internal service resolution)
        if "." not in hostname: return True
        # 3. Absence of 'render.com' and not localhost
        if "render.com" not in hostname and hostname not in ["localhost", "127.0.0.1"]:
            return True
        return False
    except:
        return False

def get_engine_args(use_asyncpg: bool = True):
    """Generate engine arguments with unified SSL strategy for Render."""
    raw_url = settings.get_database_url()
    if not use_asyncpg:
        raw_url = raw_url.replace("postgresql+asyncpg", "postgresql+psycopg2").replace("sqlite+aiosqlite", "sqlite")
    
    parsed = urlparse(raw_url)
    connect_args = {}
    db_url = raw_url
    ssl_mode = "default"

    if "postgresql" in parsed.scheme:
        if is_internal_render_host(raw_url):
            ssl_mode = "internal_bypass"
            # Strip conflicting query params for internal connection
            query = dict(parse_qsl(parsed.query))
            for key in ["ssl", "sslmode"]:
                query.pop(key, None)
            
            # Reconstruct URL without SSL params
            new_query = urlencode(query)
            db_url = urlunparse(parsed._replace(query=new_query))
            
            if use_asyncpg:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                connect_args["ssl"] = ctx
            else:
                # For psycopg2 (Alembic), use sslmode=require but allow self-signed
                connect_args["sslmode"] = "require"
        else:
            ssl_mode = "strict_require"
            connect_args[ "ssl" if use_asyncpg else "sslmode" ] = "require"
    elif "sqlite" in parsed.scheme:
        # Increase timeout for SQLite to avoid 'database is locked' errors
        connect_args["timeout"] = 60

    return db_url, connect_args, ssl_mode

# Initialize Engine
db_url, connect_args, ssl_mode = get_engine_args(use_asyncpg=True)

logger.info(f"DB Init: Mode={ssl_mode}, Host={urlparse(db_url).hostname}, URL={mask_url(db_url)}")

engine = create_async_engine(
    db_url,
    echo=False,
    connect_args=connect_args
)

AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

def run_migrations():
    """Run Alembic migrations to 'head'."""
    logger.info("--- DATABASE MIGRATION START ---")
    try:
        alembic_cfg = Config("alembic.ini")
        # Use sync URL and connect_args from get_engine_args
        db_url, connect_args, ssl_mode = get_engine_args(use_asyncpg=False)
        
        # Ensure we don't have asyncpg driver in the URL for Alembic
        if db_url.startswith("postgresql+asyncpg://"):
            db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        
        # Logging: Current and Target Revisions
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext
        
        sync_engine = sqlalchemy.create_engine(db_url, connect_args=connect_args)
        with sync_engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_rev = context.get_current_revision()
            script = ScriptDirectory.from_config(alembic_cfg)
            target_rev = script.get_current_head()
            
            logger.info(f"Current Revision: {current_rev}")
            logger.info(f"Target Revision (Head): {target_rev}")
            
            if current_rev != target_rev:
                logger.info(f"Applying migrations: {current_rev} -> {target_rev}")
                command.upgrade(alembic_cfg, "head")
                logger.info("DATABASE MIGRATION SUCCESS")
            else:
                logger.info("Database is already at latest revision.")
    except Exception as mig_e:
        import traceback
        logger.error("DATABASE MIGRATION FAILURE")
        logger.error(f"Error: {mig_e}")
        logger.error(traceback.format_exc())
        raise mig_e

async def get_db_size_mb(db: AsyncSession) -> float:
    """Get database size in MB for both PostgreSQL and SQLite."""
    try:
        url = settings.database_url
        if "postgresql" in url:
            # PostgreSQL specific size query
            res = await db.execute(sqlalchemy.text("SELECT pg_database_size(current_database())"))
            size_bytes = res.scalar()
            return size_bytes / (1024 * 1024)
        else:
            # SQLite specific path
            db_path = "osint_platform.db"
            if os.path.exists(db_path):
                return os.path.getsize(db_path) / (1024 * 1024)
            return 0.0
    except Exception as e:
        logger.error(f"Failed to get DB size: {e}")
        return 0.0
