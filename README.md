# ClaimShield AI

ClaimShield AI is a workspace for reviewing healthcare insurance claims and preparing appeals from supporting documents. Upload a policy, denial letter, invoice, or medical record; the app helps you understand the evidence, ask questions, and record a human review.

**The website runs locally or on one CPU-only server. Supabase PostgreSQL stores the records, and NVIDIA-hosted APIs perform AI inference. A GPU is not required.**

For example, a denial may say an invoice was missing. After you upload the invoice, ClaimShield can identify how it addresses the denial and draft an appeal with supporting quotations. The draft still needs a person to verify it.

## Contents

- [What the four tabs mean](#what-the-four-tabs-mean)
- [Run locally with Docker](#run-locally-with-docker)
- [Use the application](#use-the-application)
- [Test the complete local workflow](#test-the-complete-local-workflow)
- [Configure Supabase PostgreSQL](#configure-supabase-postgresql)
- [Configure NVIDIA AI](#configure-nvidia-ai)
- [Environment settings](#environment-settings)
- [Storage and security](#storage-and-security)
- [Deploy on one AWS EC2 instance](#deploy-on-one-aws-ec2-instance)
- [Troubleshooting](#troubleshooting)
- [Develop without Docker](#develop-without-docker)
- [Verification and project structure](#verification-and-project-structure)

## What the four tabs mean

| Tab | Purpose | Example |
| --- | --- | --- |
| **Analysis** | Reviews indexed documents for supported findings, missing information, inconsistencies, and suggested next steps. | Identify the reason for denial and the evidence relevant to it. |
| **Ask evidence** | Answers a specific question using this claim's uploaded documents. Answers include source citations. | "Does this policy cover outpatient consultations?" |
| **Appeal draft** | Prepares proposed appeal paragraphs with evidence and quotations, available as a text download. | Explain how a newly supplied invoice addresses a documentation denial. |
| **Human review** | Saves a person's review notes and workflow status. | "Invoice checked; request a clearer clinician note." |

A useful sequence is **upload documents → Analysis → Ask evidence → Appeal draft → Human review**. You can return to any tab as evidence changes.

The app does not approve or deny insurance claims, submit appeals to insurers, or guarantee an appeal's success. The evidence-quality score measures the available evidence, not the probability of approval. Check every conclusion and quotation against the original documents before using a result.

## Run locally with Docker

### 1. Install and start Docker

On Windows, install [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) with its WSL 2 Linux-container backend. Start Docker Desktop and wait until the engine is running. Python virtual-environment activation is not required for the Docker setup.

In a new PowerShell window, check:

```powershell
docker version
docker compose version
```

`docker version` must show both **Client** and **Server**. If only Client appears, fix Docker/WSL before starting the app. On Linux, use Docker Engine with the Compose plugin.

### 2. Configure the root .env

From this Windows workspace:

```powershell
cd "C:\Users\jayak\Music\ClaimShield AI"
```

If `.env` already exists, retain its configured credentials. For a fresh checkout only, copy the template:

```powershell
Copy-Item .env.example .env
```

Edit `.env` to supply the real Supabase SQL connection URI, NVIDIA key, and JWT secret. For local HTTP, use:

```dotenv
APP_ENV=development
AI_PROVIDER=nvidia
NVIDIA_API_KEY=YOUR_NVIDIA_API_KEY
DATABASE_URL=postgresql+asyncpg://postgres.PROJECT_REF:URL_ENCODED_PASSWORD@YOUR_SESSION_POOLER_HOST:5432/postgres
DATABASE_SSL=true
DATABASE_POOL_SIZE=1
JWT_SECRET=REPLACE_WITH_A_RANDOM_SECRET_OF_AT_LEAST_32_CHARACTERS
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=REPLACE_WITH_A_STRONG_PASSWORD_OF_AT_LEAST_12_CHARACTERS
COOKIE_SECURE=false
ALLOWED_ORIGINS=["http://localhost"]
DEMO_MODE=true
LOW_MEMORY_MODE=true
PUBLIC_PORT=80
```

Replace every placeholder before starting. Keep the NVIDIA model settings from `.env.example`. To generate a random JWT secret using Docker:

```powershell
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the generated value into `JWT_SECRET`. Keep `.env` private and excluded from Git.

`ADMIN_EMAIL` and `ADMIN_PASSWORD` must both be set or both be empty. On first startup, the app creates an administrator only if that email does not already exist. Changing `ADMIN_PASSWORD` later does not reset an existing account, and an existing reviewer account is not silently promoted.

### 3. Build and start

Run these commands one at a time; stop and inspect the error if a command fails:

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
curl.exe --fail http://localhost/api/health
```

The first build downloads images and dependencies and can take several minutes. Wait for it to finish. Expect three running services, with `backend` marked **healthy**, and this health response:

```json
{"status":"ok","database":true,"ai_provider":"nvidia"}
```

Backend container startup runs the database migrations automatically. The health endpoint verifies application/database readiness; it does not verify access to every NVIDIA model.

### 4. Open the website

Open **[http://localhost](http://localhost)** in Chrome or Edge. Sign in using the administrator credentials in `.env`, or choose **Create an account** for a reviewer account. Passwords require at least 12 characters.

| Running mode | Browser URL |
| --- | --- |
| Docker Compose with the default gateway port | `http://localhost` |
| Source development with Next.js | `http://localhost:3000` |
| Production | Your configured HTTPS domain |

If port 80 is already occupied, set `PUBLIC_PORT=8080` and `ALLOWED_ORIGINS=["http://localhost:8080"]`, run `docker compose up -d`, and open `http://localhost:8080`.

### Everyday commands

```powershell
# Start after Docker Desktop is running.
docker compose up -d

# Inspect service status and recent logs.
docker compose ps
docker compose logs --tail=100 backend frontend nginx

# Stop services while retaining containers and uploaded files.
docker compose stop

# Rebuild after application code changes.
docker compose up --build -d
```

**Do not run `docker compose down -v` unless you intend to delete the uploaded originals in the Docker volume.**

## Use the application

1. **Overview / All claims:** browse claims or click **New claim**. Enter a title and any available claim number, insurer, and amount. Amounts use the document's currency; the app does not convert currencies.
2. **Upload evidence:** open a claim and choose PDF, PNG, JPEG, or UTF-8 `.txt` files. Wait until processing finishes and the document status becomes `ready`.
3. **Analyze:** open **Analysis** and click **Analyze claim**. Read the supported findings, recommendations, missing-information notices, and evidence-quality explanation. Expand citations and use **Download source** to inspect originals.
4. **Ask:** open **Ask evidence**, enter a question, and click the send button. For example: "What documents support the reason for denial?"
5. **Draft:** open **Appeal draft** and click **Draft appeal**. Verify the paragraphs and citations, then use **Download appeal draft**. Edit the downloaded draft outside the app before sending it through your own process.
6. **Review:** open **Human review**, choose a status, enter notes, and click **Save review**. The statuses are `collecting_evidence`, `ready_for_review`, `in_review`, and `reviewed`; they are administrative workflow labels.

Default upload limits are **20 MB/file**, **50 pages/PDF**, and **50 documents/claim**. Text PDFs are extracted locally; scanned pages/images attempt Tesseract OCR, then NVIDIA vision when local extraction is insufficient. An AI transcription can contain mistakes and needs source review.

A failed document offers **Retry**. A ready document offers **Reindex**, useful after an embedding-model change. If evidence changes, the app warns when a saved report is outdated; run a new analysis to include the new evidence. Previous reports remain available in history.

## Test the complete local workflow

Use fictional documents for testing. Four portable examples are included in [docs/examples](docs/examples):

| File | What it contains |
| --- | --- |
| [01-policy.txt](docs/examples/01-policy.txt) | Outpatient coverage, required documents, and an appeal deadline rule. |
| [02-denial.txt](docs/examples/02-denial.txt) | A fictional denial for a missing invoice and clinician visit note. |
| [03-invoice.txt](docs/examples/03-invoice.txt) | An itemised invoice and payment receipt. |
| [04-clinician-note.txt](docs/examples/04-clinician-note.txt) | A fictional outpatient visit record. |

In this workspace, find them in `C:\Users\jayak\Music\ClaimShield AI\docs\examples`.

1. Confirm the health response shown above.
2. Sign in as admin. Open **Provider & usage → Check provider**. Expect the configured-key and reachable-endpoint indicators to show `ready`.
3. Create a claim titled **Local Test — Fictional**, claim number `LOCAL-TEST-001`, insurer **Fictional Test Insurer**, amount `1000`.
4. Upload all four example files. Wait for every document to show `ready`. Use **Original** to download one and compare it with the uploaded file.
5. Run **Analyze claim**. Check the denial reason and supporting citations. Conclusions should distinguish the original missing-document denial from documents now available for review; they must not promise insurer approval.
6. In **Ask evidence**, ask: **"What caused the denial, and which uploaded documents address that reason?"** Verify quotations against the originals.
7. Run **Draft appeal**, download it, and confirm it contains evidence quotations and a human-review notice. These files do not establish when an appeal was actually submitted; a draft should not invent that date.
8. Save a human-review note such as **Local verification completed**. Refresh the page and confirm the note remains.
9. After processing and AI requests finish, run `docker compose restart backend`. Wait for a healthy backend, refresh, and confirm records, reports, review notes, and original downloads remain accessible.
10. In PowerShell, run `curl.exe -i http://localhost/api/claims` without a session cookie. Expect **401 Unauthorized**.

With `DEMO_MODE=true`, a user with no claims can also choose **Try synthetic sample** from the empty claims view. It creates fictional evidence and uses real NVIDIA inference. The button is not shown once that user's claims list is populated.

To test scanned-document OCR, also upload a legible fictional PNG/JPEG or scanned PDF. Check the extracted evidence against the image. The four text examples above test text ingestion rather than OCR. AI requests consume NVIDIA account quota and may take a few minutes.

## Configure Supabase PostgreSQL

ClaimShield connects to Supabase with SQLAlchemy and `asyncpg`; it authenticates users in FastAPI rather than through Supabase Auth.

1. Open your Supabase project and click **Connect**.
2. For an IPv4 connection, select **Session pooler**, port **5432**. Copy its exact username and hostname.
3. Substitute your database password and percent-encode reserved characters in that password, such as `@` as `%40`.
4. Change the URI prefix from `postgresql://` to `postgresql+asyncpg://` and save it as `DATABASE_URL`.
5. Keep `DATABASE_SSL=true`. A direct connection on port 5432 is also supported when the host's network can reach it.

Example structure only:

```dotenv
DATABASE_URL=postgresql+asyncpg://postgres.PROJECT_REF:URL_ENCODED_PASSWORD@YOUR_SESSION_POOLER_HOST:5432/postgres
DATABASE_SSL=true
DATABASE_POOL_SIZE=1
```

**Do not use transaction-pooler port 6543:** this application uses prepared statements and rejects that connection mode. Copy the pooler host from your project's Connect dialog; do not guess it from the region. See [Supabase's connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres).

Supabase anon/service-role keys and the project URL **do not replace the database URI or database password**. The optional `SUPABASE_*` settings support Data API diagnostics; normal application storage uses the SQL connection.

Initial migration requires a database role allowed to create the app's tables and enable `vector`. It creates `cs_*` tables plus `alembic_version`, enables RLS on the application tables, and revokes public API access for Supabase's `anon`/`authenticated` roles. A restricted runtime role needs the appropriate application-table and RLS permissions.

Database TLS verifies certificates and hostnames. The public Supabase Root 2021 CA is bundled in `backend/certs`; `DATABASE_SSL_CA_FILE` can supply an alternative trusted CA. Do not disable TLS to work around an error.

## Configure NVIDIA AI

1. Sign in to [NVIDIA's model catalog](https://build.nvidia.com/).
2. Obtain an [NVIDIA API key](https://build.nvidia.com/settings/api-keys) and place it in the root `.env` as `NVIDIA_API_KEY`.
3. Retain or configure model IDs supported by your account.
4. Recreate the backend after configuration changes with `docker compose up -d`.
5. Run the admin provider check and an actual upload/analysis workflow. Reachability alone does not prove individual model access or available quota.

The application's configured defaults are:

| Task | Environment variable | Default model ID |
| --- | --- | --- |
| Fast extraction/classification and simple questions | `NVIDIA_FAST_MODEL` | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` |
| Policy/denial reasoning and appeals | `NVIDIA_REASONING_MODEL` | `nvidia/nemotron-3-super-120b-a12b` |
| Image extraction when OCR is insufficient | `NVIDIA_VISION_MODEL` | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` |
| Document/query embeddings | `NVIDIA_EMBEDDING_MODEL` | `nvidia/nemotron-3-embed-1b` |

These IDs describe the application configuration, not guaranteed endpoint availability or permanent free access. NVIDIA controls availability, quota, and rate limits. The default embedding dimension is **2048**. Changing embedding model/dimension requires reindexing affected documents.

All inference uses `https://integrate.api.nvidia.com/v1`. Model-specific reasoning settings, retry/fallback behavior, caching, and evidence verification are documented in [the implementation notes](docs/ARCHITECTURE.md).

## Environment settings

[.env.example](.env.example) lists all settings. The most relevant ones are:

| Setting | Meaning |
| --- | --- |
| `APP_ENV` | `development` for local HTTP; `production` for an HTTPS deployment. |
| `DATABASE_URL`, `DATABASE_SSL` | Supabase PostgreSQL URI and verified TLS. |
| `DATABASE_POOL_SIZE` | Connection-pool size; `1` is a conservative setting for light use on a small server. |
| `NVIDIA_API_KEY`, `NVIDIA_*_MODEL` | Backend-only credentials and model routing. |
| `JWT_SECRET` | Random session-signing secret; changing it invalidates existing sessions on that deployment. |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Optional first-time administrator bootstrap. |
| `COOKIE_SECURE` | `false` for local HTTP; `true` for production HTTPS. |
| `ALLOWED_ORIGINS` | JSON array of allowed browser origins, including scheme and any nondefault port. |
| `DEMO_MODE` | Enables the fictional sample option; disable in production. |
| `LOW_MEMORY_MODE` | Uses smaller bounded in-process caches. |
| `PUBLIC_PORT` | Host HTTP gateway port; defaults to `80`. |
| `UPLOAD_DIR` | Local source-mode upload directory; Compose overrides it to `/data/uploads`. |
| `MAX_UPLOAD_MB`, `MAX_DOCUMENT_PAGES` | Document-size/page limits. |
| `MAX_CONTEXT_TOKENS`, `MAX_OUTPUT_TOKENS` | Input-context/output budgets; output includes model reasoning allocation. |
| `AI_USAGE_MODE` | `quota` by default; the dashboard also accepts `cost`, without inventing dollar costs. |

A `.env` change normally requires `docker compose up -d` to recreate affected services. `docker compose restart` alone does not apply changed container environment variables. Use `docker compose config --quiet` for validation; unrestricted `docker compose config` can print resolved secrets.

## Storage and security

| Component | Data/responsibility |
| --- | --- |
| Supabase PostgreSQL + pgvector | Users, claims, extracted passages, embeddings, reports, reviews, and usage records. |
| Persistent Docker `uploads` volume | Uploaded original files on the machine running Docker. |
| NVIDIA-hosted APIs | Relevant document text, questions, and images supplied for inference tasks. |
| FastAPI | Authentication, claim ownership/admin checks, processing, and evidence validation. |
| Nginx / Next.js | Gateway and browser interface; application secrets stay on the backend. |

NVIDIA inference requires sending task inputs to NVIDIA; the system is not an entirely offline application. Keep credentials out of frontend code and `NEXT_PUBLIC_*` variables. Download endpoints enforce authentication and claim access.

Back up **both** the original-file volume and the Supabase database. A fresh Docker volume does not contain originals uploaded in source development or on another machine. Moving records alone does not migrate those files or their stored paths.

Citation checks and a separate semantic review reject unsupported outputs, but they do not guarantee that every AI conclusion or OCR transcription is correct. Review originals. If inference fails, previously saved evidence/reports and manual review remain available.

## Deploy on one AWS EC2 instance

Follow [the complete EC2 deployment guide](docs/EC2_DEPLOYMENT.md) for source transfer, Docker installation, swap, production configuration, HTTPS certificates, renewal, and verification.

The deployment uses **three containers on one CPU-only EC2 instance**: Nginx, Next.js, and FastAPI. Supabase and NVIDIA remain external services. A 2 GiB instance is a practical starting point for light use; the configured container memory limits total 1,088 MiB before host overhead. Monitor actual load rather than treating idle measurements as a capacity guarantee.

For production, configure:

```dotenv
APP_ENV=production
COOKIE_SECURE=true
ALLOWED_ORIGINS=["https://YOUR_DOMAIN"]
DATABASE_SSL=true
DEMO_MODE=false
```

Supply strong secrets and valid certificates at `deploy/certs/fullchain.pem` and `deploy/certs/privkey.pem`, then use both Compose files:

```bash
sudo docker compose -f compose.yaml -f compose.tls.yaml up -d
```

Complete the guide's certificate renewal setup. Expose the HTTPS gateway and restrict SSH; backend/frontend ports remain internal. Use one backend worker. Pricing and trial eligibility must be checked before launching. EC2/ARM64 runtime and production HTTPS are not yet verified for this workspace.

## Troubleshooting

| Symptom | What to check/do |
| --- | --- |
| `docker` is not recognized | Install Docker Desktop and open a new terminal so PATH updates apply. |
| Missing `dockerDesktopLinuxEngine` pipe or only Docker Client appears | Start Docker Desktop; wait for its Linux engine. Check WSL errors if startup fails. |
| `wsl --version` reports a missing path | Repair/update WSL using Microsoft's [installation instructions](https://learn.microsoft.com/en-us/windows/wsl/install#offline-install), restart Windows if required, then retry Docker. |
| WSL repair script cannot find its installer | `scripts/repair_wsl.ps1` is a workspace helper for a separately downloaded, verified MSI under `data/setup`; that installer is not part of the source archive. Use the Microsoft installer instructions instead on a fresh checkout. |
| Browser cannot reach localhost | Check `docker compose ps`, gateway port, and logs. Compose uses port 80 by default, not port 3000. |
| Backend is unhealthy or readiness returns 503 | Check the complete Supabase URI, encoded password, session-pooler host/port, project availability, TLS, and migration permissions. |
| Login succeeds but does not remain signed in over HTTP | For local testing, use `APP_ENV=development` and `COOKIE_SECURE=false`. Production secure cookies require HTTPS. |
| Administrator password changes in .env have no effect | Bootstrap settings do not reset an existing user's password. Use that account's existing credentials. |
| Provider check fails or a document shows `needs_retry` | Check NVIDIA key/model access, quota, network, and logs. Use **Retry** after resolving the cause. |
| Inference takes time | Wait for document indexing or evidence verification; the UI displays progress. Avoid duplicate clicks. |
| Semantic evidence check rejects a draft | The app regenerates once. If specific conclusions remain unsupported, it can omit them and independently verify the remaining statements. A passing subset is labelled incomplete in the page and appeal download; review sources and supply missing evidence. If nothing usable verifies, nothing is saved. |
| AI response is rejected for another reason | Review the error, source evidence, NVIDIA availability, and model configuration. Strict citation/schema checks can reject output; a saved successful result is not guaranteed for every input. |
| Original download is missing after moving environments | Migrate original-file storage and stored paths as well as the database. |
| Environment edits seem ignored | Run `docker compose up -d` to recreate the affected service. |

Logs for diagnosis:

```powershell
docker compose logs --tail=100 backend frontend nginx
```

Share relevant errors, keeping credentials, connection URIs, and private document contents out of public logs/issues.

## Develop without Docker

Use this path when modifying source code. Install **Python 3.12**, **Node.js 24**, and native **Tesseract OCR**. Keep `.env` at the repository root, set local upload storage to `UPLOAD_DIR=data/uploads`, and allow `http://localhost:3000` for the development frontend. Supabase remains the database.

In PowerShell, from the project root:

```powershell
# Skip this first command if the project's .venv already exists.
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe scripts/migrate.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log
```

Leave the backend terminal running. In a second PowerShell terminal:

```powershell
cd "C:\Users\jayak\Music\ClaimShield AI\frontend"
npm ci
npm run dev
```

Open **http://localhost:3000**. Docker already installs Tesseract in its backend image; installing it directly on Windows is only necessary for source-mode OCR. Do not run two backends using the same Supabase database/upload paths for concurrent processing.

## Verification and project structure

From the project root, using the development virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\ruff.exe check backend scripts
```

From `frontend`:

```powershell
npm run typecheck
npm run build
```

Optional live checks, from the root:

```powershell
.\.venv\Scripts\python.exe scripts/check_supabase_api.py
.\.venv\Scripts\python.exe scripts/check_nvidia.py
.\.venv\Scripts\python.exe scripts/check_workflow.py --isolated
.\.venv\Scripts\python.exe scripts/check_workflow.py --postgres
```

The Supabase API check is read-only and does not prove SQL connectivity. NVIDIA/workflow checks consume real inference quota. `--isolated` uses a temporary SQLite test fixture, not the production database. `--postgres` uses the configured Supabase database and leaves clearly named fictional accounts/claims/documents. Reports are written under ignored `data/verification`; fictional AI outputs may be saved there for diagnosis without credentials or request headers. These scripts run on the host, not inside the production backend image.

Recorded verification includes **64 automated tests**, TypeScript checks/build, live Supabase/NVIDIA workflows, and Linux AMD64 Docker startup, authentication, native OCR, and NVIDIA embedding inference. Read [the verification record](docs/VERIFICATION.md) for evidence and remaining limits; these results do not certify EC2 deployment or every future model response.

```text
backend/
  app/                 FastAPI, authentication, models, AI provider, services
  migrations/          Supabase PostgreSQL schema migrations
  certs/               Public database trust certificate
  tests/               Automated backend tests
frontend/
  app/                 Next.js workspace interface
  lib/                 API client and shared UI types
deploy/                Nginx HTTP/HTTPS configuration
docs/
  ARCHITECTURE.md      Provider, retrieval, caching, and API details
  EC2_DEPLOYMENT.md    Single-instance AWS deployment steps
  VERIFICATION.md     Recorded checks and limitations
  examples/           Fictional documents for manual testing
scripts/              Environment setup, migrations, diagnostics, live checks
compose.yaml          Local HTTP / base production services
compose.tls.yaml      Production HTTPS override
.env.example          Configuration template with placeholders
```

For backend endpoints and detailed inference behavior, see [Architecture and implementation notes](docs/ARCHITECTURE.md).
#   C l a i m S h i e l d - A I  
 