from httpx import AsyncClient
from src.main import app
import pytest
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


@pytest.fixture(autouse=True)
def setup_overrides(db_session):
    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER

    with patch("src.main.db_firestore", MagicMock()), patch(
        "src.main.kafka_manager", AsyncMock()
    ):
        yield
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_me(db_session):
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/v1/queues/users/me")

    assert response.status_code == 200
    assert response.json()["id"] == "test_streamer_123"

    db_session.expire_all()
    res = await db_session.execute(
        select(models.User).filter(models.User.id == "test_streamer_123")
    )
    assert res.scalars().first() is not None


@pytest.mark.asyncio
async def test_update_display_name_onboarding(db_session):
    user = models.User(id="test_streamer_123", email="john@doe.com", display_name=None)
    db_session.add(user)
    await db_session.commit()

    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.put(
            "/v1/queues/users/me", json={"display_name": "John Doe"}
        )

    assert response.status_code == 200
    assert response.json()["display_name"] == "John Doe"

    await db_session.refresh(user)
    assert user.display_name == "John Doe"
