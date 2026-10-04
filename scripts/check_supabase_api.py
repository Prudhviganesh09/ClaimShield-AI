"""Read-only Supabase Data API check. This does not establish a PostgreSQL SQL connection."""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx
import jwt
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]


async def main():
    values = dotenv_values(root / ".env")
    url, key = values.get("SUPABASE_PROJECT_URL", ""), values.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not key:
        raise ValueError("Supabase API credentials are not configured")
    # Read project routing metadata only; the server verifies the JWT signature.
    reference = jwt.decode(key, options={"verify_signature": False})["ref"]
    if url != "https://" + reference + ".supabase.co" or urlparse(url).scheme != "https":
        raise ValueError("Supabase URL must match the project in the supplied credential")
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        try:
            response = await client.get(url + "/rest/v1/", headers={"apikey": key,
                "Authorization": "Bearer " + key, "Accept": "application/openapi+json"})
            record = {"http_status": response.status_code, "data_api_authenticated": response.status_code == 200,
                      "sql_connection_verified": False}
            if response.status_code == 200:
                definitions = response.json().get("definitions", {})
                record["claimshield_schema_present"] = all(table in definitions for table in
                    ("cs_users", "cs_claims", "cs_documents", "cs_chunks", "cs_analyses", "cs_ai_usage"))
        except httpx.TransportError:
            record = {"data_api_authenticated": False, "error": "Supabase could not be reached",
                      "sql_connection_verified": False}
    folder = root / "data/verification"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "supabase-api-check.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record))


if __name__ == "__main__":
    asyncio.run(main())
