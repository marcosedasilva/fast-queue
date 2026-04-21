import pytest, respx, httpx
from httpx import AsyncClient, ASGITransport
from src.main import app, get_db, kafka_manager
from unittest.mock import AsyncMock
from unittest.mock import patch


@pytest.mark.asyncio
async def test_create_checkout_success(db_session):
    app.dependency_overrides[get_db] = lambda: db_session

    async with respx.mock:
        respx.post("https://api.abacatepay.com/v1/pixQrCode/create").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "id": "billing_123",
                        "amount": 500,
                        "status": "pending",
                        "brCode": "000201...",
                        "brCodeBase64": "base64",
                        "expiresAt": "2026-01-01",
                    }
                },
            )
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            payload = {
                "amount": 500,
                "user_id": "u1",
                "email": "u@t.com",
                "queue_id": 1,
                "entry_id": 10,
            }
            response = await ac.post("/v1/payments/checkouts", json=payload)

    assert response.status_code == 200
    assert response.json()["id"] == "billing_123"


@pytest.mark.asyncio
async def test_webhook_paid_confirms_and_sends_kafka(db_session):
    app.dependency_overrides[get_db] = lambda: db_session

    from src.models import Transaction

    tx = Transaction(
        user_id="u1", queue_id=1, entry_id=10, amount=500, status="PENDING"
    )
    db_session.add(tx)
    await db_session.commit()

    with patch(
        "src.main.kafka_manager.send_event", new_callable=AsyncMock
    ) as mock_kafka:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            webhook_data = {
                "event": "billing.paid",
                "data": {"pixQrCode": {"metadata": {"externalId": "10"}}},
            }
            response = await ac.post(
                "/v1/payments/webhooks/abacatepay", json=webhook_data
            )

    assert response.status_code == 200
    await db_session.refresh(tx)
    assert tx.status == "PAID"
    mock_kafka.assert_called_once()
