"""Configure a local run. Supabase API credentials arrive through one JSON stdin line, never argv/logs."""
import json
import re
import secrets
import sys
from pathlib import Path

import jwt
from dotenv import dotenv_values, set_key

path = Path(__file__).resolve().parents[1] / ".env"
supabase = json.loads(sys.stdin.readline())
claims = jwt.decode(supabase["SUPABASE_ANON_KEY"], options={"verify_signature": False})
reference = claims["ref"]
if not re.fullmatch(r"[a-z0-9]{20}", reference):
    raise ValueError("Invalid Supabase project reference")
service_claims = jwt.decode(supabase["SUPABASE_SERVICE_ROLE_KEY"], options={"verify_signature": False})
if service_claims["ref"] != reference or service_claims["role"] != "service_role":
    raise ValueError("The supplied Supabase keys do not identify the same project")
current = dotenv_values(path)
values = {"APP_ENV": "development", "COOKIE_SECURE": "false",
          "ALLOWED_ORIGINS": '["http://localhost","http://localhost:3000","http://127.0.0.1:3000"]',
          "UPLOAD_DIR": "data/uploads", "PUBLIC_PORT": "80", "DATABASE_SSL": "true",
          "SUPABASE_PROJECT_URL": "https://" + reference + ".supabase.co", **supabase}
if not current.get("ADMIN_EMAIL"):
    values["ADMIN_EMAIL"] = "admin@claimshield.local"
if not current.get("ADMIN_PASSWORD"):
    values["ADMIN_PASSWORD"] = secrets.token_urlsafe(24)
if not current.get("DATABASE_URL") or "PROJECT_REF" in current["DATABASE_URL"]:
    values["DATABASE_URL"] = ("postgresql+asyncpg://postgres:YOUR_DATABASE_PASSWORD@db." +
                              reference + ".supabase.co:5432/postgres")
for key, value in values.items():
    set_key(str(path), key, value, quote_mode="auto")
path.chmod(0o600)
print("Configured localhost origins, local uploads, administrator credentials, and Supabase API credentials.")
print("NVIDIA_API_KEY and JWT_SECRET were preserved. DATABASE_URL still needs the database password/connection URI.")
