import asyncio
import os
from dotenv import load_dotenv
from src.database import engine, Base
from src.models import Transaction

# Isso garante que se o arquivo .env existir na pasta, ele será lido
load_dotenv()

async def create_tables():
    # Log de debug para você ter certeza de onde ele está tentando conectar
    print(f"DEBUG: Conectando para criar tabelas em: {engine.url}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Tabelas criadas com sucesso!")

if __name__ == "__main__":
    asyncio.run(create_tables())