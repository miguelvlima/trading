from __future__ import annotations

import os

from sqlalchemy import select

from app.db.models import User
from app.db.session import SessionLocal
from app.services.security import hash_password


def main() -> None:
    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")
    display_name = os.getenv("BOOTSTRAP_ADMIN_DISPLAY_NAME", "Admin").strip() or "Admin"

    if not email or not password:
        print("Bootstrap admin skipped: BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD not set.")
        return

    if len(password) < 8:
        raise ValueError("BOOTSTRAP_ADMIN_PASSWORD must have at least 8 characters.")

    with SessionLocal() as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()

        if user is None:
            user = User(
                email=email,
                password_hash=hash_password(password),
                display_name=display_name,
                is_active=True,
                is_admin=True,
            )
            session.add(user)
            session.commit()
            print(f"Bootstrap admin created: {email}")
            return

        user.password_hash = hash_password(password)
        user.display_name = display_name
        user.is_active = True
        user.is_admin = True
        session.commit()
        print(f"Bootstrap admin updated: {email}")


if __name__ == "__main__":
    main()
