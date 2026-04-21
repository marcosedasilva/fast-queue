from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException
from .. import models


class UserManager:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def update(self, user_id: str, display_name: str):
        result = await self.db.execute(
            select(models.User).filter(models.User.id == user_id)
        )
        user = result.scalars().first()

        if not user:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")

        user.display_name = display_name
        await self.db.commit()
        await self.db.refresh(user)

        # Todo: update username in search index (Elasticsearch)

        return user

    async def get_or_create_user(self, user_data: dict):
        uid = user_data.get("uid")
        email = user_data.get("email")

        result = await self.db.execute(
            select(models.User).filter(models.User.id == uid)
        )
        db_user = result.scalars().first()

        if db_user:
            return db_user

        new_user = models.User(id=uid, email=email)
        self.db.add(new_user)
        await self.db.commit()
        await self.db.refresh(new_user)

        return new_user
