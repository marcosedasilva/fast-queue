import pytest
import respx
import httpx
from httpx import AsyncClient, Response
from src.main import app, get_current_user, get_db
from src import models
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.future import select

MOCK_USER = {
    "uid": "test_streamer_123",
    "email": "streamer@test.com",
    "display_name": "Streamer de Teste",
    "is_streamer": True,
}


from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from src.main import app, get_db, get_current_user


@pytest.fixture(autouse=True)
def setup_overrides(db_session):
    mock_redis = AsyncMock()
    mock_redis.incr.return_value = 1
    mock_redis.aclose = AsyncMock()

    with patch("src.services.queue_manager.redis.from_url", return_value=mock_redis), \
         patch("src.main.db_firestore", MagicMock()), \
         patch("src.main.kafka_manager", AsyncMock()):

        async def _get_db_override():
            yield db_session

        app.dependency_overrides[get_db] = _get_db_override
        app.dependency_overrides[get_current_user] = lambda: MOCK_USER

        yield
        app.dependency_overrides.clear()


def create_test_queue(user_id=MOCK_USER["uid"]):
    return models.Queue(
        title="Fila de Teste",
        entry_fee=500,
        streamer_id=user_id,
        streamer_name=MOCK_USER["display_name"],
        status=models.QueueStatus.OPEN,
    )


@pytest.mark.asyncio
async def test_create_queue(db_session):
    user = models.User(
        id=MOCK_USER["uid"],
        email=MOCK_USER["email"],
        display_name=MOCK_USER["display_name"],
    )
    db_session.add(user)
    await db_session.flush()

    async with AsyncClient(app=app, base_url="http://test") as ac:
        payload = {
            "title": "Fila de Teste API",
            "entry_fee": 500,
            "max_slots": 10,
        }
        response = await ac.post("/v1/queues/", json=payload)

    assert response.status_code == 200
    assert response.json()["title"] == "Fila de Teste API"


async def test_create_queue_user_not_found(db_session):
    user = models.User(
        id="nonexistent_user",
        email=MOCK_USER["email"],
        display_name=MOCK_USER["display_name"],
    )
    db_session.add(user)
    await db_session.flush()
    async with AsyncClient(app=app, base_url="http://test") as ac:
        payload = {
            "title": "Fila de Teste API",
            "entry_fee": 500,
            "max_slots": 10,
        }
        response = await ac.post("/v1/queues/", json=payload)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_queue_details_success(db_session):
    streamer = models.User(
        id=MOCK_USER["uid"],
        email=MOCK_USER["email"],
        display_name=MOCK_USER["display_name"],
    )
    db_session.add(streamer)
    await db_session.flush()

    queue = create_test_queue()
    db_session.add(queue)
    await db_session.commit()
    await db_session.refresh(queue)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get(f"/v1/queues/{queue.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == queue.id
    assert data["title"] == queue.title
    assert data["streamer_name"] == streamer.display_name
    assert data["entry_fee"] == queue.entry_fee
    assert data["status"] == queue.status.value


@pytest.mark.asyncio
async def test_get_queue_details_not_found():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/v1/queues/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Fila não encontrada"


@pytest.mark.asyncio
async def test_update_queue_success(db_session):
    user = models.User(id=MOCK_USER["uid"], email=MOCK_USER["email"])
    db_session.add(user)
    await db_session.flush()

    queue = create_test_queue()
    db_session.add(queue)
    await db_session.commit()
    await db_session.refresh(queue)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        payload = {"title": "Fila Atualizada", "status": "CLOSED"}
        response = await ac.patch(f"/v1/queues/{queue.id}", json=payload)

    assert response.status_code == 200
    assert response.json()["title"] == "Fila Atualizada"
    assert response.json()["status"] == "CLOSED"

    await db_session.refresh(queue)
    assert queue.title == "Fila Atualizada"
    assert queue.status == models.QueueStatus.CLOSED


@pytest.mark.asyncio
async def test_update_queue_forbidden(db_session):
    other_user = models.User(id="outro_cara", email="outro@test.com")
    db_session.add(other_user)

    queue = create_test_queue(user_id=other_user.id)
    db_session.add(queue)
    await db_session.commit()
    await db_session.refresh(queue)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.patch(
            f"/v1/queues/{queue.id}", json={"title": "Hacker Edit"}
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Não autorizado"


@pytest.mark.asyncio
async def test_update_queue_invalid_status(db_session):
    user = models.User(id=MOCK_USER["uid"], email=MOCK_USER["email"])
    db_session.add(user)

    queue = create_test_queue()
    db_session.add(queue)
    await db_session.commit()
    await db_session.refresh(queue)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.patch("/v1/queues/10", json={"status": "STATUS_INVENTADO"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_delete_queue_and_refund_success(db_session):
    user = models.User(id=MOCK_USER["uid"], email=MOCK_USER["email"])
    db_session.add(user)
    await db_session.flush()

    queue = create_test_queue()
    db_session.add(queue)
    await db_session.commit()
    await db_session.refresh(queue)

    v1 = models.QueueEntry(
        id=50,
        queue_id=queue.id,
        viewer_id="v1",
        game_nick="nick1",
        status="WAITING",
        position=1,
    )
    v2 = models.QueueEntry(
        id=51,
        queue_id=queue.id,
        viewer_id="v2",
        game_nick="nick2",
        status="WAITING",
        position=2,
    )
    v3 = models.QueueEntry(
        id=52,
        queue_id=queue.id,
        viewer_id="v3",
        game_nick="nick3",
        status="COMPLETED",
        position=0,
    )

    db_session.add_all([v1, v2, v3])
    await db_session.commit()

    from src.main import kafka_manager

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.delete(f"/v1/queues/{queue.id}")

    assert response.status_code == 200
    assert response.json()["message"] == "Fila encerrada e estornos processados."

    assert kafka_manager.send_event.call_count == 3

    await db_session.refresh(queue)
    assert queue.status == models.QueueStatus.DELETED


@pytest.mark.asyncio
async def test_delete_queue_not_found():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.delete("/v1/queues/9999")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_queue_forbidden(db_session):
    queue = models.Queue(
        id=99,
        title="Fila Alheia",
        entry_fee=100,
        streamer_id="outro_dono",
        streamer_name="Outro Dono",
        status="OPEN",
    )
    db_session.add(queue)
    await db_session.commit()

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.delete("/v1/queues/99")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_join_queue_success(db_session):
    streamer = models.User(id="streamer_1", email="s@test.com", display_name="Streamer")
    viewer = models.User(id=MOCK_USER["uid"], email=MOCK_USER["email"])
    db_session.add_all([streamer, viewer])
    await db_session.commit()
    
    queue = create_test_queue(user_id=streamer.id)
    db_session.add(queue)
    await db_session.commit()
    await db_session.refresh(queue)
    target_id = queue.id

    async with respx.mock:
        respx.post(url__regex=r".*/checkouts").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "billing_123",
                    "amount": 500,
                    "status": "pending",
                    "brCode": "000201...",
                    "brCodeBase64": "base64",
                    "expiresAt": "2026-01-01",
                },
            )
        )

        async with AsyncClient(app=app, base_url="http://test") as ac:
            payload = {"game_nick": "PlayerOne", "social_handle": "@p1"}
            response = await ac.post(f"/v1/queues/{target_id}/join", json=payload)

    assert response.status_code == 200

    db_session.expire_all()
    result = await db_session.execute(
        select(models.QueueEntry).filter(models.QueueEntry.queue_id == target_id)
    )
    entry = result.scalars().first()

    assert entry is not None, "A entrada não foi encontrada! O banco continua vazio."
    assert entry.game_nick == "PlayerOne"


@pytest.mark.asyncio
async def test_join_queue_closed(db_session):
    queue = models.Queue(
        id=2, title="Fila Fechada", entry_fee=500, streamer_id="any", status="CLOSED", streamer_name="Any"
    )
    db_session.add(queue)
    await db_session.commit()

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post("/v1/queues/2/join", json={"game_nick": "test"})

    assert response.status_code == 400
    assert "Fila fechada" in response.json()["detail"]


@pytest.mark.asyncio
async def test_join_queue_full(db_session):
    queue = models.Queue(
        id=3,
        title="Fila Lotada",
        entry_fee=500,
        max_slots=1,
        streamer_id="any",
        streamer_name="Any",
        status="OPEN",
    )
    db_session.add(queue)
    entry = models.QueueEntry(
        queue_id=3, viewer_id="other", game_nick="nick", status="WAITING", position=1
    )
    db_session.add(entry)
    await db_session.commit()

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post("/v1/queues/3/join", json={"game_nick": "tentativa"})

    assert response.status_code == 400
    assert "lotada" in response.json()["detail"]


@pytest.mark.asyncio
async def test_join_queue_payment_service_down(db_session):
    streamer = models.User(id="s1", email="s1@t.com")
    viewer = models.User(id=MOCK_USER["uid"], email=MOCK_USER["email"])
    db_session.add_all([streamer, viewer])

    queue = create_test_queue(user_id=streamer.id)

    db_session.add(queue)
    await db_session.commit()
    await db_session.refresh(queue)

    async with respx.mock:
        respx.post(url__regex=r".*/checkouts").mock(
            side_effect=httpx.ConnectError("Connection Refused")
        )

        async with AsyncClient(app=app, base_url="http://test") as ac:
            payload = {"game_nick": "NickTest", "social_handle": "@test"}
            response = await ac.post(f"/v1/queues/{queue.id}/join", json=payload)

    assert response.status_code == 503
    assert "indisponível" in response.json()["detail"]


@pytest.mark.asyncio
async def test_call_next_queue_not_found():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post("/v1/queues/999/next")

    assert response.status_code == 404
    assert response.json()["detail"] == "Fila não encontrada."


@pytest.mark.asyncio
async def test_call_next_forbidden(db_session):
    other_owner = models.User(id="hacker_id", email="h@t.com")
    db_session.add(other_owner)

    queue = create_test_queue(user_id=other_owner.id)
    db_session.add(queue)
    await db_session.commit()
    await db_session.refresh(queue)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(f"/v1/queues/{queue.id}/next")

    assert response.status_code == 403
    assert "permissão" in response.json()["detail"]


@pytest.mark.asyncio
async def test_call_next_empty_queue(db_session):
    queue = create_test_queue()
    db_session.add(queue)
    await db_session.commit()
    await db_session.refresh(queue)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(f"/v1/queues/{queue.id}/next")

    assert response.status_code == 404
    assert "empty queue" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_call_next_success(db_session):
    user_v1 = models.User(id="u1", email="u1@t.com", display_name="Player 1")
    user_v2 = models.User(id="u2", email="u2@t.com", display_name="Player 2")

    db_session.add_all([user_v1, user_v2])
    await db_session.flush()

    queue = create_test_queue()
    db_session.add(queue)
    await db_session.commit()
    await db_session.refresh(queue)

    v1 = models.QueueEntry(
        id=1,
        queue_id=queue.id,
        viewer_id="u1",
        game_nick="P1_Nick",
        status="CALLED",
        position=1,
    )
    v2 = models.QueueEntry(
        id=2,
        queue_id=queue.id,
        viewer_id="u2",
        game_nick="P2_Nick",
        status="WAITING",
        position=2,
    )

    db_session.add_all([v1, v2])
    await db_session.commit()

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(f"/v1/queues/{queue.id}/next")

    assert response.status_code == 200
    await db_session.refresh(v1)
    assert v1.status == models.QueueEntryStatus.COMPLETED

    await db_session.refresh(v2)
    assert v2.status == models.QueueEntryStatus.CALLED


@pytest.mark.asyncio
async def test_reject_viewer_success(db_session):
    queue = create_test_queue()
    db_session.add(queue)
    await db_session.commit()
    await db_session.refresh(queue)

    entry = models.QueueEntry(
        id=100,
        queue_id=queue.id,
        viewer_id="viewer_id",
        game_nick="Player 1",
        status=models.QueueEntryStatus.WAITING,
        position=1,
    )
    db_session.add(entry)
    await db_session.commit()

    from src.main import kafka_manager

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(f"/v1/queues/{queue.id}/reject/{entry.id}")

    assert response.status_code == 200
    assert kafka_manager.send_event.call_count == 1
    db_session.expire_all()
    await db_session.refresh(entry)
    assert entry.status == models.QueueEntryStatus.REJECTED


@pytest.mark.asyncio
async def test_reject_viewer_forbidden(db_session):
    other_owner = models.User(id="hacker_id", email="h@t.com")
    db_session.add(other_owner)

    queue = create_test_queue(user_id=other_owner.id)
    db_session.add(queue)
    await db_session.commit()
    await db_session.refresh(queue)

    entry = models.QueueEntry(
        id=101, queue_id=queue.id, viewer_id="v", game_nick="n", status="WAITING", position=1
    )
    db_session.add(entry)
    await db_session.commit()

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(f"/v1/queues/{queue.id}/reject/{entry.id}")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_reject_viewer_not_found(db_session):
    queue = create_test_queue()
    db_session.add(queue)
    await db_session.commit()
    await db_session.refresh(queue)

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post("/v1/queues/70/reject/999")

    assert response.status_code == 404
