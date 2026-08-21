"""Link a Supabase user to Dashem and grant the initial platform role.

Run with DATABASE_URL pointing at the intended environment. This command does
not create credentials; the user must already exist in Supabase Auth.
"""

import argparse

from sqlmodel import Session, select

from app.core.database import engine
from app.models.identity import AuthIdentity, User
from app.models.platform import PlatformMembership, PlatformRoleEnum


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", required=True, help="Supabase Auth user UUID (JWT sub)")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--platform-role",
        choices=[role.value for role in PlatformRoleEnum],
        default=PlatformRoleEnum.PLATFORM_OWNER.value,
    )
    args = parser.parse_args()

    with Session(engine) as session:
        identity = session.exec(
            select(AuthIdentity).where(
                AuthIdentity.provider == "supabase",
                AuthIdentity.provider_subject == args.subject,
            )
        ).first()
        if identity:
            user = session.get(User, identity.user_id)
        else:
            user = session.exec(select(User).where(User.email == args.email)).first()
            if not user:
                user = User(email=args.email, full_name=args.name)
                session.add(user)
                session.flush()
            session.add(AuthIdentity(
                user_id=user.id,
                provider="supabase",
                provider_subject=args.subject,
                provider_email=args.email,
                email_verified=True,
            ))
            session.flush()

        platform = session.exec(
            select(PlatformMembership).where(PlatformMembership.user_id == user.id)
        ).first()
        role = PlatformRoleEnum(args.platform_role)
        if platform:
            platform.role = role
            platform.is_active = True
            session.add(platform)
        else:
            session.add(PlatformMembership(user_id=user.id, role=role))
        session.commit()
        print(f"Provisioned {args.email} as {role.value} (user_id={user.id}).")


if __name__ == "__main__":
    main()
