"""Run migrations from the repository root using the same root .env as FastAPI."""
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root / "backend"))
config = Config(str(root / "backend" / "alembic.ini"))
config.set_main_option("script_location", str(root / "backend" / "migrations"))
command.upgrade(config, "head")
