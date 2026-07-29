from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,   
)

AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  
)
