import httpx
from fastapi import FastAPI, Depends, HTTPException, APIRouter, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from .database import get_db
from . import models, schemas
import firebase_admin
from firebase_admin import credentials, firestore
import os
from sqlalchemy import func
from .services.queue_manager import QueueManager
from contextlib import asynccontextmanager
from .kafka_producer import KafkaProducerManager
import redis.asyncio as redis
from .auth import get_current_user
from .services.user_manager import UserManager
from .kafka_consumer import consume_payment_confirmations
import asyncio
from libs.logger import setup_logger
import os
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

load_dotenv()

logger = setup_logger("queue-service")

PAYMENT_URL = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8001/v1/payments")

KAFKA_SERVER = os.environ.get("KAFKA_SERVER", "kafka:9092")
kafka_manager = KafkaProducerManager(KAFKA_SERVER)

FIREBASE_PATH = os.getenv("FIREBASE_ADMIN_SDK_PATH", "firebase.json")


import os
import firebase_admin
from firebase_admin import credentials, firestore

def init_firebase():
    if not firebase_admin._apps:
        # 1. Busca o caminho do arquivo (em dev no Docker será /app/firebase.json)
        cred_path = os.getenv("FIREBASE_ADMIN_SDK_PATH", "firebase.json")
        project_id = os.getenv("GCLOUD_PROJECT", "fast-queue-493301")

        # 2. Inicializa SEMPRE com o arquivo (Ele é a prova de falhas)
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, options={'projectId': project_id})

        # 3. Log de verificação para sabermos para onde o dado vai
        if os.getenv("FIRESTORE_EMULATOR_HOST"):
            print(f"🛠️  MODO EMULADOR: {os.getenv('FIRESTORE_EMULATOR_HOST')}")
        else:
            print("🔥 MODO PRODUÇÃO (FIREBASE REAL)")
    

db_firestore = init_firebase()


try:
    db_firestore = init_firebase()
except Exception:
    db_firestore = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    print("🚀 [BOOT] Iniciando Queue Service...")

    payment_task = None

    try:
        # Tenta o Kafka, mas se falhar, loga o erro em vez de travar o boot
        print(f"📡 [BOOT] Tentando conectar ao Kafka em: {KAFKA_SERVER}")
        await kafka_manager.start()
        print("✅ [BOOT] Kafka conectado!")

        # Inicia o consumidor
        loop = asyncio.get_event_loop()
        payment_task = loop.create_task(consume_payment_confirmations())
        print("🎧 [BOOT] Consumidor de pagamentos iniciado em background.")

    except Exception as e:
        print(f"❌ [BOOT ERROR] Falha crítica na inicialização de serviços: {e}")
        # NÃO damos raise aqui. Queremos que o app suba para podermos
        # ver este print no log do Google e saber que o erro é o Kafka.

    print("🏁 [BOOT] App pronto para receber tráfego na porta 8080!")
    yield  # O FastAPI abre a porta 8080 EXATAMENTE AQUI

    # --- SHUTDOWN ---
    print("🛑 [SHUTDOWN] Desligando Queue Service...")
    if kafka_manager:
        await kafka_manager.stop()
    if payment_task:
        payment_task.cancel()


if os.getenv("ENV") == "testing":
    REDIS_URL = "memory://"
else:
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")

limiter = Limiter(key_func=get_remote_address, storage_uri=REDIS_URL)

app = FastAPI(title="Fast Queue - Queue Service", lifespan=lifespan)
api_router = APIRouter(prefix="/v1/queues")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_PATH)
    firebase_admin.initialize_app(cred)

db_firestore = firestore.client()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://fastq.site",
        "https://fast-queue-493301.web.app",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],  # Use "*" nos headers para evitar erros de preflight
)


@api_router.post("/", response_model=schemas.QueueResponse)
async def create(
    data: schemas.QueueCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    manager = QueueManager(db, db_firestore, kafka_manager)
    return await manager.store(
        streamer_id=current_user["uid"],
        title=data.title,
        entry_fee=data.entry_fee,
        max_slots=data.max_slots,
    )


@api_router.get("/{queue_id}")
async def read(queue_id: int, db: AsyncSession = Depends(get_db)):
    manager = QueueManager(db, db_firestore, kafka_manager)
    return await manager.show(queue_id=queue_id)


@api_router.get("/", response_model=List[schemas.QueueResponse])
async def list_my_queues(
    db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    query = (
        select(models.Queue)
        .filter(
            models.Queue.streamer_id == current_user["uid"],
            models.Queue.status != "DELETED",
        )
        .order_by(models.Queue.created_at.desc())
    )

    result = await db.execute(query)
    return result.scalars().all()


@api_router.patch("/{queue_id}", response_model=schemas.QueueResponse)
async def update(
    queue_id: int,
    data: schemas.QueueUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    res = await db.execute(select(models.Queue).filter(models.Queue.id == queue_id))
    queue = res.scalars().first()
    if queue.streamer_id != current_user["uid"]:
        raise HTTPException(status_code=403, detail="Não autorizado")

    manager = QueueManager(db, db_firestore, kafka_manager)
    return await manager.update(queue_id, data.model_dump(exclude_unset=True))


@api_router.delete("/{queue_id}")
async def delete(
    queue_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    res = await db.execute(select(models.Queue).filter(models.Queue.id == queue_id))
    queue = res.scalars().first()
    if not queue:
        raise HTTPException(status_code=404, detail="Fila não encontrada")
    if queue.streamer_id != current_user["uid"]:
        raise HTTPException(status_code=403, detail="Não autorizado")

    manager = QueueManager(db, db_firestore, kafka_manager)
    await manager.delete_and_refund_all(queue_id)
    return {"message": "Fila encerrada e estornos processados."}


@api_router.post("/{queue_id}/join", response_model=schemas.QueueJoinResponse)
@limiter.limit("5/minute")
async def join_queue(
    request: Request,
    queue_id: int,
    data: schemas.QueueJoin,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    manager = QueueManager(db, db_firestore, kafka_manager)

    entry, entry_fee = await manager.create_pending_entry(
        current_user["uid"], queue_id, data.game_nick, data.social_handle
    )

    async with httpx.AsyncClient() as client:
        try:
            payment_payload = {
                "user_id": current_user["uid"],
                "email": current_user["email"],
                "amount": entry_fee,
                "queue_id": queue_id,
                "entry_id": entry.id,
            }

            url = f"{PAYMENT_URL}/checkouts"
            resp = await client.post(url, json=payment_payload)

            if resp.status_code != 200:
                raise HTTPException(
                    status_code=500,
                    detail="Erro ao gerar pagamento no serviço financeiro",
                )

            payment_data = resp.json()

            return payment_data
        except Exception as e:
            logger.error(f"Erro no processamento: {str(url)}")
            print(f"Erro de conexão com Payment Service: {e}")
            raise HTTPException(
                status_code=503, detail="Serviço de pagamento indisponível"
            )


@api_router.post("/{queue_id}/next", response_model=schemas.CalledViewerResponse)
async def call_next(
    queue_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    result = await db.execute(select(models.Queue).filter(models.Queue.id == queue_id))
    queue = result.scalars().first()

    if not queue:
        raise HTTPException(status_code=404, detail="Fila não encontrada.")

    if queue.streamer_id != current_user["uid"]:
        raise HTTPException(
            status_code=403, detail="Você não tem permissão para gerenciar esta fila."
        )

    manager = QueueManager(db, db_firestore, kafka_manager)
    entry = await manager.call_next(queue_id)

    return entry


@api_router.put("/users/me", response_model=schemas.UserResponse)
async def update_me(
    data: schemas.UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    manager = UserManager(db)
    return await manager.update(current_user["uid"], data.display_name)


@api_router.get("/users/me", response_model=schemas.UserResponse)
async def me(
    db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    manager = UserManager(db)
    user = await manager.get_or_create_user(current_user)
    return user


@api_router.post("/{queue_id}/reject/{entry_id}")
async def reject_viewer(
    queue_id: int,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    res = await db.execute(select(models.Queue).filter(models.Queue.id == queue_id))
    queue = res.scalars().first()
    
    if not queue:
        raise HTTPException(status_code=404, detail="Fila não encontrada.")
    
    if queue.streamer_id != current_user["uid"]:
        raise HTTPException(status_code=403, detail="Não autorizado")

    manager = QueueManager(db, db_firestore, kafka_manager)
    await manager.reject_entry(queue_id, entry_id)
    return {"status": "success"}


app.include_router(api_router)
