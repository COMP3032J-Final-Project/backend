from app.core.config import settings
from app.models.user import UserRegister
from app.repositories.user import UserDAO
from sqlmodel.ext.asyncio.session import AsyncSession


async def create_default_admin(db: AsyncSession) -> None:
    existing_user_by_email = await UserDAO.get_user_by_email(settings.ADMIN_EMAIL, db)
    if existing_user_by_email:
        existing_user_by_email.is_superuser = True
        await db.commit()
        return

    user_register = UserRegister(
        email=settings.ADMIN_EMAIL, username=settings.ADMIN_USERNAME, password=settings.ADMIN_PASSWORD
    )
    await UserDAO.create_user(db, user_register, is_superuser=True)
