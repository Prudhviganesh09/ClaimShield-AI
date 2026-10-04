# ClaimShield AI

An evidence-first healthcare claim administration workspace. FastAPI handles authentication, documents,
retrieval, and review history. Next.js provides the user interface. Supabase-hosted PostgreSQL stores claims,
analyses, usage events, and pgvector embeddings. NVIDIA-hosted endpoints perform all model inference.

**The application uses NVIDIA-hosted inference. No GPU is required on the AWS EC2 instance.**

## Architecture

```mermaid
flowchart TD
    User[User] --> Internet[Internet / HTTPS]
    Internet --> TLS[TLS termination: AWS ALB or Nginx]
    subgraph EC2[AWS EC2 · CPU only · Docker Compose]
        TLS --> Nginx[claimshield-nginx]
        Nginx --> Next[claimshield-frontend · Next.js]
        Nginx --> API[claimshield-backend · FastAPI]
        API --> OCR[PyMuPDF + local Tesseract OCR]
        API --> Provider[NvidiaProvider · pooled async httpx]
    end
    API -->|TLS / SQLAlchemy + asyncpg| DB[Supabase PostgreSQL + pgvector]
    Provider -->|HTTPS| NVIDIA[integrate.api.nvidia.com]
    NVIDIA --> Models[Hosted Nemotron reasoning / fast / vision / embeddings]
```

The default Compose deployment has **three application containers**, using Supabase as the external database.
It does not run a local PostgreSQL container, model server, GPU runtime, or model weights. Redis is not required;
bounded caches and single-flight request deduplication run in the backend process. Use one backend worker.

```mermaid
flowchart TD
    Upload[Uploaded original · saved before inference] --> Text[PyMuPDF / UTF-8 text extraction]
    Text --> Quality{Usable text?}
    Quality -->|Yes| Clean[Clean text + local field heuristics]
    Quality -->|No| OCR[Tesseract OCR]
    OCR --> Confidence{OCR quality sufficient?}
    Confidence -->|Yes| Clean
    Confidence -->|No| Vision[NVIDIA structured vision extraction]
    Vision --> Clean
    Clean --> Chunk[Paragraph / sentence-aware chunks]
    Chunk --> Passage[NVIDIA embedding · input_type passage · batches]
    Passage --> Vector[Supabase pgvector + model/dimension metadata]
    Question[User question] --> Query[NVIDIA embedding · input_type query]
    Query --> Search[Hybrid vector + PostgreSQL full-text search]
    Vector --> Search
    Search --> Rank[Heuristic rerank + deduplicate + context budget]
    Rank --> Reason[NVIDIA routed reasoning · Pydantic JSON validation]
    Reason --> Verify[Exact citation verification + semantic evidence review]
    Verify --> Answer[Grounded response + deterministic risk/confidence]
    Answer --> Human[Human review / appeal draft]
```

## First start

This workspace's ignored `.env` is configured for localhost with the supplied Supabase API keys and existing
NVIDIA key. Supabase PostgreSQL authentication, the initial migration, pgvector, and database access checks have
passed using a verified TLS session-pooler connection. Administrator credentials are saved in `.env`. See
[the verification record](docs/VERIFICATION.md) for the checks and remaining deployment validation.

Prerequisites: Docker Engine with Compose v2, a Supabase project, and an NVIDIA API key. For source development,
use Python 3.12, Node 24, and Tesseract. Docker installs Tesseract in the backend image.

1. Create `.env` from `.env.example` and replace `JWT_SECRET` with at least 32 random characters. You can run
   `python scripts/setup_env.py` to create it with a generated secret. The script refuses to overwrite an existing file.
2. Configure Supabase as described below, and put its complete connection URI in `DATABASE_URL`.
3. Set `NVIDIA_API_KEY` and confirm model IDs in NVIDIA's catalog.
4. For an administrator, set **both** `ADMIN_EMAIL` and a strong `ADMIN_PASSWORD` (12+ characters). A new admin is
   created at startup only when that email does not exist. Existing accounts are never silently promoted.
5. For local HTTP testing, set `APP_ENV=development`, `COOKIE_SECURE=false`, and
   `ALLOWED_ORIGINS=["http://localhost"]`. Keep `DATABASE_SSL=true` for Supabase.
6. Run:

   ```sh
   docker compose up --build -d
   docker compose ps
   docker compose logs --tail=100 backend
   ```

7. Open [ClaimShield on localhost](http://localhost). Create a reviewer account or sign in as your configured admin.
   Start a claim and upload PDF, PNG, JPEG, or UTF-8 `.txt` documents. Indexing runs in the background with visible
   processing status. Failed documents offer **Retry**. **Reindex** updates embeddings after changing the model.

With `DEMO_MODE=true`, **Try synthetic sample** creates three explicitly fictional documents. They pass through
the same real extraction and NVIDIA embedding pipeline as uploads; the application does not fabricate AI results.
Disable demo mode for your production workspace. Never use synthetic outputs as real claim evidence.

## Supabase PostgreSQL setup

1. Create or select your Supabase project and open its **Connect** dialog.
2. Copy the **direct database connection** if your EC2 host supports IPv6, or use the **session pooler** on port
   `5432` for IPv4. Change the URI scheme to `postgresql+asyncpg://`.
3. URL-encode special characters in the database password. Copy the hostname/user from your own project's dialog;
   the example hostname is a placeholder.

   ```dotenv
   DATABASE_URL=postgresql+asyncpg://postgres.PROJECT_REF:URL_ENCODED_PASSWORD@YOUR_SESSION_POOLER_HOST:5432/postgres
   DATABASE_SSL=true
   DATABASE_POOL_SIZE=3
   ```

4. Use a database role allowed to create the ClaimShield tables and enable the `vector` extension. The default
   Supabase `postgres` connection can run the initial migration. A restricted runtime role must own the application
   tables or have appropriate table privileges and RLS access. Do not expose database credentials to browsers.
5. Backend startup runs `alembic upgrade head`. The initial migration creates only `cs_*` tables plus
   `alembic_version`, a full-text GIN index, and the pgvector extension in `extensions`. It enables RLS on `cs_*`
   tables and revokes Supabase `anon` and `authenticated` access. ClaimShield authenticates users in FastAPI and
   enforces owner/admin checks on every claim/document endpoint. It does not use Supabase's public REST API or Auth.

**Use direct or session mode, not the transaction pooler on port `6543`.** SQLAlchemy's asyncpg dialect uses
prepared statements. This deployment intentionally rejects transaction-mode URLs. TLS validates certificates;
it is not disabled to work around connection errors.

The public Supabase Root 2021 CA is bundled under `backend/certs` and added to system trust for Supabase database
hostnames. Hostname verification remains enabled. `DATABASE_SSL_CA_FILE` can override the CA file if needed.
The optional URI parameter `sslmode=require` is normalized to the application's verified TLS configuration.

Vector columns store variable dimensions with explicit `embedding_model` and `embedding_dimension` metadata.
Retrieval filters both before distance comparisons. Model changes require reindexing each affected document.
An exact vector scan is used per claim (bounded to 50 documents), combined with indexed PostgreSQL full-text
search. There is no HNSW vector index in this MVP; this avoids assuming index dimension compatibility for 2048-D
vectors and keeps the initial deployment simple. Profile actual workloads before adding an index.

References: [Supabase connection modes](https://supabase.com/docs/guides/database/connecting-to-postgres),
[Supabase pgvector](https://supabase.com/docs/guides/database/extensions/pgvector).

## NVIDIA AI Setup

1. Create/sign in to an [NVIDIA developer account](https://developer.nvidia.com/).
2. Open [NVIDIA's API/model catalog](https://build.nvidia.com/).
3. Select available hosted/free endpoints, and verify your account has access to each configured model.
4. Generate an [NVIDIA API key](https://build.nvidia.com/settings/api-keys).
5. Add `NVIDIA_API_KEY=...` to the backend `.env`.
6. Configure model IDs, embedding dimension, and any supported model-specific parameters.
7. Start ClaimShield; an admin can run the **Check provider** action in **Provider & usage**.

**Hosted endpoint availability, free quotas, and rate limits are controlled by NVIDIA and may change. Model IDs
are therefore configurable.** A successful `/models` health request verifies reachability/authentication, not access
to every individual model or remaining quota. Check the catalog and run an actual document/analysis workflow.

| Task | Environment configuration | Default model |
| --- | --- | --- |
| Classification, metadata, simple questions, summaries | `NVIDIA_FAST_MODEL` | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` |
| Policy, denial, contradictions, synthesis, appeals, orchestration | `NVIDIA_REASONING_MODEL` | `nvidia/nemotron-3-super-120b-a12b` |
| Poor OCR / image understanding | `NVIDIA_VISION_MODEL` | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` |
| Passage/query embeddings | `NVIDIA_EMBEDDING_MODEL` | `nvidia/nemotron-3-embed-1b` |
| Optional safety classification | `NVIDIA_SAFETY_MODEL` | Configured by operator, disabled by default |

`NvidiaModelRouter` centralizes selection. `NvidiaProvider` uses `httpx.AsyncClient` connection pooling and low
temperature. Model parameters can be supplied as a JSON mapping in `NVIDIA_MODEL_PARAMETERS`, for example:

```dotenv
NVIDIA_MODEL_PARAMETERS={"nvidia/nemotron-3-super-120b-a12b":{"reasoning_effort":"low","reasoning_budget":4096},"nvidia/nemotron-3-nano-omni-30b-a3b-reasoning":{"reasoning_budget":512}}
```

The example environment uses low-effort Super reasoning with a 4096-token reasoning budget and an 8192-token
total output cap. Live testing showed that an excessively small reasoning budget could leave reasoning prose
in the answer field and fail strict JSON validation. Only use
parameters supported by the selected endpoint. They are not sent to unrelated models. Output tokens
include the model's reasoning allocation; if output is truncated, the provider rejects it and reports the token
limit. Adjust `MAX_OUTPUT_TOKENS` and supported reasoning parameters as appropriate for your model/account.

The generic structured path supplies a JSON schema in the system prompt, parses JSON, validates with Pydantic,
and permits exactly one schema repair request. It does not require provider-native JSON-schema support. Vision
uses base64 image content parts. The provider interface supports future streaming; current user-facing responses
are buffered so evidence checks complete before any conclusions are displayed.

`NVIDIA_REASONING_FALLBACK_MODEL` and `NVIDIA_FAST_FALLBACK_MODEL` are optional. Transient network failures,
timeouts, `429`, `5xx`, and unavailable-model responses use bounded exponential backoff. The configured fallback
is used only after retries are exhausted, with model-specific parameters. Authentication and invalid payload
errors do not trigger failover. The actual model and fallback status appear in usage logs and saved reports.
Pending (`202`) responses are retried within the bounded policy; no arbitrary redirect or polling URL is followed.

The default embedding endpoint accepts **passage** for indexing and **query** for questions. The default model
uses 2048-D output; set `NVIDIA_EMBEDDING_DIMENSION` if choosing another model. Inputs are batched (16 by default),
bounded conservatively below the endpoint's input limit, and vectors are checked for dimension, finiteness,
nonzero values, response index ordering, and count.

API references: [reasoning](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-super-120b-a12b-infer),
[multimodal](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-nano-omni-30b-a3b-reasoning-infer),
[embeddings](https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-embed-1b-infer).

## Evidence, caching, and failure behavior

- Originals are written to a persistent Docker volume and database records are committed before inference.
  Provider failures leave claims, originals, previous analyses, login, and human review available.
- Text PDFs use PyMuPDF. Scanned pages/images attempt local Tesseract first. Only poor OCR triggers remote vision.
  AI transcriptions carry explicit warnings and reduced confidence. Corrupt, encrypted, oversized, or empty files
  fail safely. The configurable defaults are 20 MB/file and 50 pages/PDF, plus 50 documents/claim.
- Document checksums deduplicate uploads within a claim. Persisted chunks/embeddings survive restart, and reindexing
  preserves chunk IDs so historical citations stay resolvable. Interrupted jobs become retryable; committed but
  unstarted uploads are scheduled at startup. Failed jobs do not consume quota in a retry loop.
- Response/embedding/query caches are bounded, in-memory, tenant-scoped TTL caches. Concurrent equivalent requests
  share one task. Embedding keys include input mode, model, dimension, and tenant. Errors are never cached.
  Analysis caching persists in PostgreSQL, keyed by claim evidence revision, question/task, and model configuration.
- Retrieval selects candidate passages, reranks vector/full-text/keyword/document-priority scores, removes duplicate
  text, and fits a token budget. Entire document collections are never sent as a reasoning prompt.
- Every finding, recommendation, and appeal paragraph requires existing chunk IDs and exact source quotations.
  A separate semantic review checks conclusions against their quotations and source context. One bounded
  regeneration can correct a rejected draft, followed by the same exact and semantic checks. A still-rejected
  response is never saved or cached, so a manual retry makes a fresh inference request. These checks reduce unsupported outputs but do not
  replace a human reviewing source documents, especially OCR/vision transcriptions.
- Missing-document/risk rules and the weighted evidence-confidence score are deterministic Python. The confidence
  score describes evidence quality, not approval probability. Workflow statuses never approve or deny a claim.
- Optional safety classification is enabled by `ENABLE_NVIDIA_SAFETY=true` and a configured safety model. Its
  outage does not block the application. Application scope rules, constrained prompts, typed schemas, citation
  verification, semantic review, and human review remain active.

## Admin usage

`AI_USAGE_MODE=quota` is the default; `cost` mode is also accepted. The dashboard shows NVIDIA requests, requests
today/month, token estimates, rate-limit events, failures, per-model distribution, and average latency. Counts
are **HTTP inference attempts**, including retries and structured-output repair/verification calls. Reporting
periods use UTC. Cached results make no inference calls and add no usage events. Dollar cost remains unavailable
until verified pricing data is supplied; no costs are fabricated.

Every inference attempt records provider, actual model, task, timestamp, latency, token counts/estimates,
HTTP status, success, retry count, fallback use, claim/owner IDs, and request ID. Sensitive prompts and document
contents are not stored in usage logs. Evidence and reports remain in their authorized application tables.

Key endpoints (session cookie required except register/login/health):

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/api/auth/register`, `/api/auth/login`, `/api/auth/logout` | Session lifecycle |
| GET | `/api/auth/me` | Current user |
| GET/POST | `/api/claims` | Browse/create claims |
| GET | `/api/claims/{id}` | Documents + report history |
| POST | `/api/claims/{id}/documents` | Save upload, enqueue extraction/indexing |
| GET | `/api/documents/{id}/download` | Authorized original download |
| GET | `/api/analyses/{id}/appeal/download` | Authorized appeal draft with source quotations |
| POST | `/api/documents/{id}/retry` | Retry/reindex |
| POST | `/api/claims/{id}/analyze`, `/appeal`, `/chat` | Evidence-grounded workflows |
| POST | `/api/claims/{id}/review` | Human review notes/status |
| GET | `/api/admin/providers/nvidia/health` | Lightweight authenticated provider check |
| GET | `/api/admin/usage` | Admin usage aggregates |
| GET | `/api/health` | Database/application readiness, independent of NVIDIA |

## Production EC2 deployment

For this workspace's local run commands and a single low-cost EC2 deployment, follow
[the step-by-step EC2 guide](docs/EC2_DEPLOYMENT.md). It includes source transfer,
production environment settings, HTTPS, automatic certificate renewal, and verification.

Use a CPU-only Linux instance with sufficient memory for Next.js, Python PDF/OCR processing, and the OS
(2 GB is a practical starting point; build images elsewhere if build memory is constrained). Supabase hosts
the database. Docker memory limits bound each container. OCR and inference concurrency are deliberately limited.
No CUDA, GPU drivers, NVIDIA Container Toolkit, Transformers, NIM containers, or local model downloads are used.

1. Configure `.env` with `APP_ENV=production`, `COOKIE_SECURE=true`, `DEMO_MODE=false`, strong secrets, Supabase TLS,
   and `ALLOWED_ORIGINS=["https://YOUR_DOMAIN"]`.
2. Restrict `.env` permissions on Linux: `chmod 600 .env`. Restrict SSH to your administration IP.
3. Put the HTTP Nginx service behind a TLS-terminating AWS ALB/reverse proxy, or use the provided Nginx TLS override:

   ```sh
   # Provision your certificate/key first under deploy/certs (excluded from Git).
   docker compose -f compose.yaml -f compose.tls.yaml up --build -d
   ```

4. Expose only your intended HTTP/HTTPS gateway. Backend and frontend ports are internal. No PostgreSQL port
   is opened on EC2. Enable outbound HTTPS to NVIDIA and database TLS to Supabase.
5. Verify readiness, administrator sign-in, a text/PDF upload, extraction status, real embeddings, analysis,
   source download, review persistence, and provider health. The NVIDIA key is accessible only to FastAPI;
   it is not injected into frontend builds or a `NEXT_PUBLIC_` variable.
6. Back up the Docker `uploads` volume alongside Supabase database backups. A database-only backup cannot restore
   original uploaded files. Use an encrypted backup destination and test restoring both together.

The TLS override expects `deploy/certs/fullchain.pem` and `deploy/certs/privkey.pem`. For ALB termination, use the
base Compose file and restrict EC2 gateway access to the ALB security group. Do not expose production sign-in over
plain HTTP while secure cookies are enabled. The application deliberately refuses insecure production cookie settings.

## Source development and verification

Keep `.env` at the repository root. Backend commands below run from the root so configuration resolves consistently:

```sh
python -m venv .venv
# Activate .venv (Windows: .venv\Scripts\Activate.ps1; Linux: source .venv/bin/activate)
pip install -r backend/requirements-dev.txt
```

Run migrations from the root with `scripts/migrate.py`:

```sh
python scripts/migrate.py
uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log
```

Optional live checks from the root (the NVIDIA check consumes a small amount of account quota and uses only
synthetic inputs):

```sh
python scripts/check_supabase_api.py
python scripts/check_nvidia.py
python scripts/check_workflow.py --isolated
# Complete live Supabase + NVIDIA test; creates clearly labeled fictional accounts/claims/documents:
python scripts/check_workflow.py --postgres
```

The Supabase API check is read-only and does not run migrations or verify a PostgreSQL connection.
The workflow check uses real NVIDIA inference in either mode, consumes account quota, and saves its report under
`data/verification/workflow-*`. `--isolated` uses a SQLite test fixture; `--postgres` uses your configured Supabase
database. Fictional completions are saved locally for diagnosing failed checks, without keys or request headers.

Set development origins to `["http://localhost:3000"]`, `APP_ENV=development`, `COOKIE_SECURE=false`, and a local
`UPLOAD_DIR=data/uploads`. The database stays Supabase; only test fixtures use SQLite.

```sh
cd frontend
npm ci
npm run dev
# In another terminal, from repository root:
python -m pytest backend/tests -q
ruff check backend
# In frontend:
npm run typecheck
npm run build
```

Tests use HTTP transport fixtures and temporary SQLite databases to exercise endpoint payloads, retries/failover,
JSON validation, embedding modes/caching, tenant isolation, originals surviving outages, evidence verification,
model-change reindexing, and review persistence. Test doubles are confined to tests; production calls use native
HTTPS requests to NVIDIA. PostgreSQL migration/retrieval SQL has a separate compilation check. Live Supabase
migrations and NVIDIA inference require your configured credentials and are not proved by offline test passes.

Project map: `backend/app/ai` (provider/router/cache), `backend/app/services` (documents/retrieval/reasoning),
`backend/migrations` (Supabase schema), `frontend/app` (workspace UI), `deploy` (gateway), `scripts` (setup/checks).
#   C l a i m S h i e l d - A I  
 