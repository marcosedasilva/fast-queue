import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# 1. Tenta pegar a variável de ambiente
# O os.environ.get é mais rigoroso que o os.getenv em alguns casos
DATABASE_URL = os.environ.get("DATABASE_URL")

# 2. DEBUG CRÍTICO: Vamos ver o que o Python está lendo no momento da execução
print(f"🔍 DEBUG DATABASE: A variável lida do ambiente foi: {DATABASE_URL}")

# 3. SE a variável estiver vazia ou for localhost, nós FORÇAMOS o valor do Docker
if not DATABASE_URL or "localhost" in DATABASE_URL or "127.0.0.1" in DATABASE_URL:
    print("⚠️  Aviso: DATABASE_URL não encontrada ou é localhost. Forçando para 'postgres:5432'")
    DATABASE_URL = "postgresql+asyncpg://user:password@postgres:5432/fast_queue_db"

print(f"🚀 [PAYMENT-SERVICE] Engine conectando em: {DATABASE_URL}")

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session