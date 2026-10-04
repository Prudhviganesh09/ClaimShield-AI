"""LOCAL UI verification harness only. No fabricated AI responses; inference is unconfigured.

Run: uvicorn preview:app --app-dir backend --host 127.0.0.1 --port 8000
SQLite here is an isolated test fixture. Production app.main always uses configured Supabase PostgreSQL.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import select

from app.auth import hash_password
from app.config import Settings
from app.db import Database, User
from app.main import create_app

root = Path(__file__).resolve().parents[1]
(root / "data").mkdir(exist_ok=True)
settings = Settings(_env_file=None, app_env="test", database_url="sqlite+aiosqlite:///"+str(root/"data/preview.sqlite"),
                    upload_dir=root/"data/preview-uploads", cookie_secure=False, nvidia_api_key="",
                    allowed_origins=["http://localhost:3000"], demo_mode=True)
db = Database(settings)
app = create_app(settings, db)
original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application):
    await db.initialize_for_tests()
    async with db.sessions() as session:
        user = await session.scalar(select(User).where(User.email == "reviewer@example.test"))
        if not user:
            session.add(User(email="reviewer@example.test", name="Preview Reviewer", role="admin",
                             password_hash=await hash_password("claimshield-preview-123")))
            await session.commit()
    async with original_lifespan(application):
        yield


app.router.lifespan_context = lifespan
