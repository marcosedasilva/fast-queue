import asyncio
import json
import logging
from aiokafka import AIOKafkaConsumer
from src.database import AsyncSessionLocal
from src.services.queue_manager import QueueManager
from firebase_admin import firestore
import os

KAFKA_SERVER = os.getenv("KAFKA_SERVER", "kafka:9092")


async def consume_payment_confirmations():
    consumer = AIOKafkaConsumer(
        "payment_confirmed",
        bootstrap_servers=KAFKA_SERVER,
        group_id="queue_service_group",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )
    await consumer.start()
    logging.info("🎧 Queue Service ouvindo confirmações de pagamento...")

    try:
        async for msg in consumer:
            event = msg.value
            entry_id = event.get("entry_id")

            async with AsyncSessionLocal() as db:
                db_firestore = firestore.client()
                manager = QueueManager(db, db_firestore)

                await manager.activate_entry(entry_id)
                logging.info(f"✅ [QUEUE] Entrada {entry_id} ativada com sucesso!")

    except Exception as e:
        logging.error(f"❌ Erro no consumidor de pagamentos: {e}")
    finally:
        await consumer.stop()
