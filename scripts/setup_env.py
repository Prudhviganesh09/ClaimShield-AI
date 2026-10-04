"""Create .env once, without reading or printing existing secrets."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env"
template = (root / ".env.example").read_text(encoding="utf-8")
template = template.replace("JWT_SECRET=CHANGE_ME_TO_A_RANDOM_SECRET_AT_LEAST_32_CHARACTERS",
                            "JWT_SECRET=" + secrets.token_urlsafe(48))
with target.open("x", encoding="utf-8") as stream:
    stream.write(template)
target.chmod(0o600)
print("Created .env. Set your Supabase DATABASE_URL, NVIDIA_API_KEY, and deployment origin before starting.")
