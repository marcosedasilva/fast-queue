from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from .. import models
import logging

class PaymentManager:
    def __init__(self, db: AsyncSession):
        self.db = db
    async def create_pending_transaction(self, user_id: str, queue_id: int, entry_id: int, amount: float, provider_id: str):
        new_tx = models.Transaction(
            user_id=user_id,
            queue_id=queue_id,
            entry_id=entry_id,
            amount=amount,
            status="PENDING",
            provider_id=provider_id # ID que o AbacatePay nos deu
        )
        self.db.add(new_tx)
        try:
            await self.db.commit()
            return new_tx
        except Exception as e:
            await self.db.rollback()
            raise e

    async def confirm_payment(self, entry_id: int):
        # Busca a transação pendente vinculada a essa entrada da fila
        result = await self.db.execute(
            select(models.Transaction).filter(models.Transaction.entry_id == entry_id)
        )
        tx = result.scalars().first()

        if tx:
            tx.status = "PAID"
            await self.db.commit()
            return tx
        return None

    async def process_refund(self, event_data: dict):
        """
        Lógica para registrar o estorno no banco de dados.
        """
        entry_id = event_data.get("entry_id")
        viewer_id = event_data.get("viewer_id")
        amount = event_data.get("amount")

        # 1. Tenta encontrar uma transação existente de 'PAID' para essa entrada
        # (No futuro, toda entrada na fila gerará uma Transaction com status 'PAID')
        result = await self.db.execute(
            select(models.Transaction).filter(models.Transaction.entry_id == entry_id)
        )
        transaction = result.scalars().first()

        if transaction:
            transaction.status = "REFUNDED"
        else:
            # Se não achou (ex: teste manual), criamos uma nova de estorno
            transaction = models.Transaction(
                user_id=viewer_id,
                queue_id=event_data.get("queue_id"),
                entry_id=entry_id,
                amount=amount,
                status="REFUNDED"
            )
            self.db.add(transaction)

        try:
            await self.db.commit()
            logging.info(f"✅ [DATABASE] Estorno da Entry {entry_id} gravado com sucesso.")
        except Exception as e:
            await self.db.rollback()
            logging.error(f"❌ Erro ao gravar estorno no banco: {e}")