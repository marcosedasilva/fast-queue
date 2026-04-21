from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, update
from fastapi import HTTPException
from .. import models, schemas
from firebase_admin import firestore
from datetime import datetime
from sqlalchemy.orm import joinedload
import redis.asyncio as redis
import os
from libs.logger import setup_logger

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
logger = setup_logger("queue-manager")


class QueueManager:
    def __init__(self, db: AsyncSession, firestore_db, kafka_producer=None):
        self.db = db
        self.firestore_db = firestore_db
        self.kafka_producer = kafka_producer
        r = redis.Redis(host="localhost", port=6379, db=0)

    async def store(self, streamer_id: str, title: str, entry_fee: int, max_slots: int):
        res = await self.db.execute(
            select(models.User).filter(models.User.id == streamer_id)
        )
        streamer = res.scalars().first()

        if not streamer:
            raise HTTPException(status_code=404, detail="Streamer não encontrado.")

        existing_query = select(models.Queue).filter(
            models.Queue.streamer_id == streamer_id,
            models.Queue.status == models.QueueStatus.OPEN,
        )
        existing = await self.db.execute(existing_query)
        if existing.scalars().first():
            raise HTTPException(
                status_code=400, detail="Você já possui uma fila ativa."
            )

        new_queue = models.Queue(
            title=title,
            entry_fee=entry_fee,
            max_slots=max_slots,
            streamer_id=streamer_id,
            streamer_name=streamer.display_name,
            status=models.QueueStatus.OPEN,
        )
        self.db.add(new_queue)
        await self.db.commit()
        await self.db.refresh(new_queue)

        firestore_data = {
            "id": new_queue.id,
            "title": new_queue.title,
            "entry_fee": new_queue.entry_fee,
            "max_slots": new_queue.max_slots,
            "status": "OPEN",
            "streamer_name": streamer.display_name,
            "created_at": firestore.SERVER_TIMESTAMP,
        }

        self.firestore_db.collection("active_queues").document(str(new_queue.id)).set(
            firestore_data
        )
        logger.info(f"Fila {new_queue.id} criada e sincronizada com Firestore.")

        if self.kafka_producer:
            now_iso = datetime.now().isoformat()

            search_event = {
                "type": "QUEUE_CREATED",
                "streamer_id": streamer.id,
                "display_name": streamer.display_name,
                "queue_id": new_queue.id,
                "queue_title": new_queue.title,
                "is_live": True,
                "timestamp": now_iso,
            }
            await self.kafka_producer.send_event("search_sync", search_event)
            logger.info(
                f"Evento de criação de fila enviado para Kafka com timestamp: {now_iso}"
            )

        return new_queue

    async def show(self, queue_id: int):
        result = await self.db.execute(
            select(models.Queue)
            .options(joinedload(models.Queue.streamer))
            .filter(models.Queue.id == queue_id)
        )
        queue = result.scalars().first()

        if not queue:
            raise HTTPException(status_code=404, detail="Fila não encontrada")

        return {
            "id": queue.id,
            "title": queue.title,
            "entry_fee": queue.entry_fee,
            "streamer_name": queue.streamer.display_name,
            "status": queue.status,
        }

    async def update(self, queue_id: int, data: dict):
        result = await self.db.execute(
            select(models.Queue).filter(models.Queue.id == queue_id)
        )
        queue = result.scalars().first()
        if not queue:
            raise HTTPException(status_code=404, detail="Fila não encontrada.")

        for key, value in data.items():
            if value is not None:
                setattr(queue, key, value)

        await self.db.commit()
        await self.db.refresh(queue)

        self.firestore_db.collection("active_queues").document(str(queue_id)).update(
            data
        )

        if self.kafka_producer:
            await self.kafka_producer.send_event(
                "search_sync",
                {
                    "type": "QUEUE_UPDATED",
                    "queue_id": queue.id,
                    "queue_title": queue.title,
                    "is_live": queue.status == "OPEN",
                },
            )

        return queue

    async def delete_and_refund_all(self, queue_id: int):
        result = await self.db.execute(
            select(models.Queue).filter(models.Queue.id == queue_id)
        )
        queue = result.scalars().first()
        if not queue:
            return

        entries_query = select(models.QueueEntry).filter(
            models.QueueEntry.queue_id == queue_id,
            models.QueueEntry.status == models.QueueEntryStatus.WAITING,
        )
        entries_res = await self.db.execute(entries_query)
        entries_to_refund = entries_res.scalars().all()

        for entry in entries_to_refund:
            entry.status = models.QueueEntryStatus.REJECTED
            if self.kafka_producer:
                await self.kafka_producer.send_event(
                    "refund_requests",
                    {
                        "type": "REFUND_REQUESTED",
                        "entry_id": entry.id,
                        "viewer_id": entry.viewer_id,
                        "amount": queue.entry_fee,
                        "reason": "Fila encerrada pelo streamer",
                    },
                )

        self.firestore_db.collection("active_queues").document(str(queue_id)).delete()

        if self.kafka_producer:
            await self.kafka_producer.send_event(
                "search_sync", {"type": "QUEUE_DELETED", "queue_id": queue_id}
            )

        queue.status = "DELETED"
        await self.db.commit()
        return True

    async def create_pending_entry(
        self, viewer_id: str, queue_id: int, game_nick: str, social_handle: str
    ):
        active_count_query = select(func.count(models.QueueEntry.id)).filter(
            models.QueueEntry.queue_id == queue_id,
            models.QueueEntry.status.in_(["WAITING", "CALLED", "PENDING_PAYMENT"]),
        )
        result = await self.db.execute(active_count_query)
        current_active = result.scalar()

        queue_res = await self.db.execute(
            select(models.Queue).filter(models.Queue.id == queue_id)
        )
        queue = queue_res.scalars().first()

        if current_active >= queue.max_slots:
            raise HTTPException(status_code=400, detail="Esta fila já está lotada!")

        if queue.status != models.QueueStatus.OPEN:
            raise HTTPException(
                status_code=400, detail="Fila fechada para novas entradas."
            )

        new_entry = models.QueueEntry(
            queue_id=queue_id,
            viewer_id=viewer_id,
            game_nick=game_nick,
            social_handle=social_handle,
            position=0,
            status=models.QueueEntryStatus.PENDING_PAYMENT,
        )
        self.db.add(new_entry)

        await self.db.commit()
        await self.db.refresh(new_entry)

        res = await self.db.execute(
            select(models.Queue).filter(models.Queue.id == queue_id)
        )
        queue = res.scalars().first()

        return new_entry, queue.entry_fee

    async def call_next(self, queue_id: int):
        await self.db.execute(
            update(models.QueueEntry)
            .where(
                models.QueueEntry.queue_id == queue_id,
                models.QueueEntry.status == models.QueueEntryStatus.CALLED,
            )
            .values(status=models.QueueEntryStatus.COMPLETED)
        )

        query = (
            select(models.QueueEntry)
            .options(joinedload(models.QueueEntry.viewer))
            .filter(
                models.QueueEntry.queue_id == queue_id,
                models.QueueEntry.status == models.QueueEntryStatus.WAITING,
            )
            .order_by(models.QueueEntry.position.asc())
            .limit(1)
        )

        result = await self.db.execute(query)
        entry = result.scalars().first()

        if not entry:
            raise HTTPException(status_code=404, detail="Empty Queue")

        entry.status = models.QueueEntryStatus.CALLED
        await self.db.commit()
        await self.db.refresh(entry)

        self._sync_to_firestore(queue_id, entry)

        return entry

    def _sync_to_firestore(self, queue_id, entry):
        entry_data = {
            "id": entry.id,
            "viewer_id": entry.viewer_id,
            "game_nick": entry.game_nick,
            "social_handle": entry.social_handle,
            "position": entry.position,
            "status": entry.status,
            "created_at": firestore.SERVER_TIMESTAMP,
        }
        self.firestore_db.collection("active_queues").document(
            str(queue_id)
        ).collection("entries").document(str(entry.id)).set(entry_data)

    async def reject_entry(self, queue_id: int, entry_id: int):
        result = await self.db.execute(
            select(models.QueueEntry).filter(
                models.QueueEntry.id == entry_id, models.QueueEntry.queue_id == queue_id
            )
        )
        entry = result.scalars().first()

        if not entry:
            raise HTTPException(status_code=404, detail="Entrada não encontrada.")

        entry.status = models.QueueEntryStatus.REJECTED

        await self.db.commit()

        self.firestore_db.collection("active_queues").document(
            str(queue_id)
        ).collection("entries").document(str(entry.id)).update(
            {
                "status": models.QueueEntryStatus.REJECTED,
                "rejected_at": firestore.SERVER_TIMESTAMP,
            }
        )

        queue = await self.db.execute(
            select(models.Queue).filter(models.Queue.id == queue_id)
        )
        queue = queue.scalars().first()

        if self.kafka_producer:
            event = {
                "type": "REFUND_REQUESTED",
                "queue_id": queue_id,
                "entry_id": entry.id,
                "viewer_id": entry.viewer_id,
                "amount": queue.entry_fee,
                "reason": "Rejeitado pelo streamer",
            }
            await self.kafka_producer.send_event("refund_requests", event)

            return True

        return True

    async def close_queue(self, queue_id: int):
        result = await self.db.execute(
            select(models.Queue).filter(models.Queue.id == queue_id)
        )
        queue = result.scalars().first()
        if queue:
            queue.status = models.QueueStatus.CLOSED
            await self.db.commit()

            self.firestore_db.collection("active_queues").document(
                str(queue_id)
            ).update({"status": "CLOSED"})
        return queue

    async def activate_entry(self, entry_id: int):
        print(f"🚀 [DEBUG] Iniciando ativação da entry {entry_id}")

        try:
            result = await self.db.execute(
                select(models.QueueEntry).filter(models.QueueEntry.id == entry_id)
            )
            entry = result.scalars().first()

            if not entry or entry.status != models.QueueEntryStatus.PENDING_PAYMENT:
                print(
                    f"⚠️ [QUEUE] Abortando: Entrada {entry_id} não está pendente ou não existe."
                )
                return

            r = redis.from_url(REDIS_URL, decode_responses=True)

            next_pos = await r.incr(f"queue_pos:{entry.queue_id}")
            print(f"🔢 [DEBUG] Nova posição gerada: {next_pos}")

            entry.position = next_pos
            entry.status = models.QueueEntryStatus.WAITING

            await self.db.commit()
            await self.db.refresh(entry)
            print(f"✅ [DEBUG] Banco de dados atualizado para Entry {entry_id}")

            self._sync_to_firestore(entry.queue_id, entry)

            await r.aclose()

        except Exception as e:
            await self.db.rollback()
            print(f"🔥 [ERRO CRÍTICO] Falha ao ativar entry {entry_id}: {str(e)}")
