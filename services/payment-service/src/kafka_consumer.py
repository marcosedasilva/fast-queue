import json
import logging
from aiokafka import AIOKafkaConsumer
from src.database import AsyncSessionLocal # Importamos a fábrica de sessões
from src.services.payment_manager import PaymentManager
import os

KAFKA_SERVER = os.getenv("KAFKA_SERVER", "kafka:9092")

async def consume_refunds():
    consumer = AIOKafkaConsumer(
        "refund_requests",
        bootstrap_servers=KAFKA_SERVER,
        group_id="payment_group",
        value_deserializer=lambda v: json.loads(v.decode('utf-8'))
    )
    await consumer.start()
    
    try:
        async for msg in consumer:
            event = msg.value
            # Criamos uma nova sessão de banco para cada mensagem
            async with AsyncSessionLocal() as db:
                manager = PaymentManager(db)
                await manager.process_refund(event)
    finally:
        await consumer.stop()