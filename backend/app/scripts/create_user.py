import argparse

from sqlalchemy import select

from app.db.models import User
from app.db.session import SessionLocal
from app.services.security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Create internal user account")
    parser.add_argument("--email", required=True, help="User email")
    parser.add_argument("--password", required=True, help="User password")
    parser.add_argument("--display-name", default=None, help="Optional display name")
    parser.add_argument("--admin", action="store_true", help="Create admin user")
    args = parser.parse_args()

    email = args.email.lower().strip()
    if len(args.password) < 8:
        raise ValueError("Password must have at least 8 characters.")

    with SessionLocal() as session:
        existing = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existing:
            raise ValueError(f"User already exists: {email}")

        user = User(
            email=email,
            password_hash=hash_password(args.password),
            display_name=args.display_name.strip() if args.display_name else None,
            is_active=True,
            is_admin=args.admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)

    print(f"Created user #{user.id}: {user.email}")


if __name__ == "__main__":
    main()
