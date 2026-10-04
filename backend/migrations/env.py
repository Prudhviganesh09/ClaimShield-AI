import asyncio

from alembic import context
from sqlalchemy import text

from app.config import get_settings
from app.db import Base, Database


def run_migrations(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions"))
        connection.execute(text("SET LOCAL search_path TO public, extensions"))
        context.run_migrations()


async def online():
    db = Database(get_settings())
    async with db.engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await db.engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Use online migrations against the Supabase direct/session-pooler connection")
else:
    asyncio.run(online())
