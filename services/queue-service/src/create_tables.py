import asyncio
from src.database import engine, Base
from src.models import User, Queue, QueueEntry

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Tabelas criadas com sucesso no Postgres!")

if __name__ == "__main__":
    asyncio.run(create_tables())