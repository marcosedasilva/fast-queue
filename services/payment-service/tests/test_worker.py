import pytest
from src.services.payment_manager import PaymentManager
from src.models import Transaction

@pytest.mark.asyncio
async def test_process_refund_updates_db(db_session):
    tx = Transaction(user_id="u1", queue_id=1, entry_id=50, amount=1000, status="PAID")
    db_session.add(tx)
    await db_session.commit()

    manager = PaymentManager(db_session)
    event = {"entry_id": 50, "viewer_id": "u1", "amount": 1000}
    await manager.process_refund(event)

    await db_session.refresh(tx)
    assert tx.status == "REFUNDED"