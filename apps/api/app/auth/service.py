"""User persistence helpers.

Identities come from Supabase: the local `users` row mirrors a Supabase account,
keyed by the Supabase user id (the token's `sub`). Rows are created lazily on the
first authenticated request so saved fields/plans have an owner to hang off.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


async def get_user(session: AsyncSession, user_id: str) -> User | None:
    return await session.get(User, user_id)


async def get_or_create_supabase_user(
    session: AsyncSession,
    sub: str,
    email: str | None,
    name: str | None = None,
) -> User:
    """Return the local user for a Supabase account, creating it on first sign-in.

    `sub` is the Supabase user id and becomes the local primary key, so saved
    fields keep the same owner across logins and devices.
    """
    user = await session.get(User, sub)
    if user is not None:
        changed = False
        if email and user.email != email:
            user.email = email
            changed = True
        if name and not user.name:
            user.name = name
            changed = True
        if changed:
            await session.commit()
        return user

    user = User(id=sub, email=email, name=name)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # Another concurrent request created it, or the email is already held by
        # a pre-existing row — fall back to whatever is now on record.
        await session.rollback()
        user = await session.get(User, sub)
        if user is not None:
            return user
        if email:
            existing = await session.execute(select(User).where(User.email == email))
            row = existing.scalar_one_or_none()
            if row is not None:
                return row
        raise
    await session.refresh(user)
    return user
