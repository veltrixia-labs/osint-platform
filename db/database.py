from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from config.settings import settings

db_url = settings.get_database_url()
connect_args = {}
if "ssl=require" in db_url or "postgresql" in db_url:
    connect_args["ssl"] = True

engine = create_async_engine(db_url, echo=False, connect_args=connect_args)
AsyncSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
