from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import User
from app.db.session import SessionLocal
from app.services.security import hash_password


def main() -> None:
    settings = get_settings()
    if settings.env.lower() != "dev":
        print("Skipping dev user bootstrap (ENV is not dev).")
        return

    email = settings.dev_default_user_email.lower().strip()
    password = settings.dev_default_user_password
    display_name = settings.dev_default_user_display_name.strip()
    is_admin = settings.dev_default_user_is_admin

    if len(password) < 8:
        raise ValueError("DEV_DEFAULT_USER_PASSWORD must have at least 8 characters.")

    with SessionLocal() as session:
        existing = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existing:
            print(f"Dev user already exists: {email}")
            return

        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name or None,
            is_active=True,
            is_admin=is_admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)

    print(f"Created dev user #{user.id}: {user.email}")


if __name__ == "__main__":
    main()
