from fastapi import FastAPI, Depends, HTTPException, Request, APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from .database import get_db
from .services.payment_manager import PaymentManager
from .services.abacate_pay import AbacatePayService
from .kafka_consumer import consume_refunds
from contextlib import asynccontextmanager
import asyncio
from .kafka_producer import KafkaProducerManager
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import os


load_dotenv()

KAFKA_SERVER = os.getenv("KAFKA_SERVER", "kafka:9092")
kafka_manager = KafkaProducerManager(KAFKA_SERVER)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    print("🚀 [BOOT] Iniciando Payment Service...")
    
    consumer_task = None
    
    try:
        # Tenta o Kafka, mas não trava o boot se ele falhar
        print(f"📡 [BOOT] Conectando ao Kafka em: {KAFKA_SERVER}")
        await kafka_manager.start()
        print("✅ [BOOT] Kafka Producer conectado!")

        # Inicia o consumidor em background
        from .kafka_consumer import consume_refunds
        loop = asyncio.get_event_loop()
        consumer_task = loop.create_task(consume_refunds())
        print("🎧 [BOOT] Consumidor de estornos iniciado.")
        
    except Exception as e:
        print(f"❌ [BOOT ERROR] Falha na infra: {e}")

    print("🏁 [BOOT] Payment Service pronto na porta 8080!")
    yield # O Google Cloud Run verá a porta aberta aqui

    # --- SHUTDOWN ---
    if kafka_manager:
        await kafka_manager.stop()
    if consumer_task:
        consumer_task.cancel()

app = FastAPI(title="Fast Queue - Payment Service", lifespan=lifespan)
api_router = APIRouter(prefix="/v1/payments")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://fastq.site", "https://fast-queue-493301.web.app", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"], # Use "*" nos headers para evitar erros de preflight
)

@api_router.post("/webhooks/abacatepay")
async def abacatepay_webhook(data: dict, db: AsyncSession = Depends(get_db)):
    # 1. Validar o evento
    print(f"🔍 [DEBUG WEBHOOK] Payload recebido: {data}")
    
    event_type = data.get("event")
    if event_type != "billing.paid":
        return {"status": "ignored"}


    # 2. Navegar na estrutura que você recebeu:
    # data -> data -> pixQrCode -> metadata -> externalId
    billing_data = data.get("data", {})
    pix_data = billing_data.get("pixQrCode", {})
    metadata = pix_data.get("metadata", {})
    external_id = metadata.get("externalId")
    
    print(f"🔍 [DEBUG WEBHOOK] Status: {event_type}, ExternalID: {external_id}")

    if not external_id:
        print("⚠️ Webhook recebido sem externalId")
        return {"status": "error", "message": "No externalId"}

    # 3. Processar a confirmação
    manager = PaymentManager(db)
    # Convertemos para int porque no banco o entry_id é Integer
    tx = await manager.confirm_payment(int(external_id))
    
    if tx:
        # 4. Notificar o Queue Service via Kafka
        event = {
            "type": "PAYMENT_CONFIRMED",
            "entry_id": int(external_id),
            "queue_id": tx.queue_id
        }
        await kafka_manager.send_event("payment_confirmed", event)
        print(f"✅ [PAYMENT] Sucesso! Entrada {external_id} confirmada e enviada ao Kafka.")

    return {"status": "ok"}

@api_router.post("/checkouts")
async def create_checkout(data: dict, db: AsyncSession = Depends(get_db)):
    abacate = AbacatePayService()
    
    # 1. Solicita o Pix ao AbacatePay
    billing = await abacate.create_pix_billing(
        amount=data["amount"],
        external_id=str(data["entry_id"]),
        user_email=data["email"]
    )
    
    if not billing:
        raise HTTPException(status_code=500, detail="Erro ao gerar cobrança no AbacatePay")

    # 2. Registra a intenção de pagamento no nosso banco
    manager = PaymentManager(db)
    await manager.create_pending_transaction(
        user_id=data["user_id"],
        queue_id=data["queue_id"],
        entry_id=data["entry_id"],
        amount=data["amount"],
        provider_id=billing["data"]["id"]
    )

    return billing["data"]

app.include_router(api_router)