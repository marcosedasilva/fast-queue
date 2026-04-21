import os, pytest, pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from src.database import Base, get_db

TEST_DB = "./test_payment.db"

@pytest_asyncio.fixture(scope="function")
async def db_session():
    if os.path.exists(TEST_DB): os.remove(TEST_DB)
    engine = create_async_engine(f"sqlite+aiosqlite:///{TEST_DB}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    Factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Factory() as session:
        yield session
    await engine.dispose()
    if os.path.exists(TEST_DB): os.remove(TEST_DB)