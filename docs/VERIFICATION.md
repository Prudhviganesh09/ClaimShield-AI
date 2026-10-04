# Verification record

Implemented in the empty workspace on October 4, 2026. The database architecture was changed to Supabase-hosted
PostgreSQL at the user's request. No local production database or model container is defined.

## Passed

- 57 automated tests: provider payloads, retry/backoff/fallback, structured JSON validation/repair, token limits,
  passage/query embeddings, batching/caching, cancellation deduplication, document extraction/OCR line boundaries,
  concurrent duplicate uploads, tenant isolation, saved originals and previous reports surviving provider outages,
  reindexing after model changes, exact citations, semantic rejection, review persistence, usage aggregation,
  synthetic document ingestion, PostgreSQL/pgvector query compilation, migration/RLS SQL compilation,
  Supabase CA/hostname verification, valid appeals without separate findings, rejected-response regeneration,
  bounded grounding correction with re-verification, mandatory vision transcription fields, and rejection of
  unsupported appeal-timeliness assertions even when the model's semantic reviewer accepts them.
- Ruff checks for backend and scripts; Python package dependency consistency.
- TypeScript checking and Next.js optimized production build.
- npm production dependency audit reported zero known vulnerabilities during this verification run.
- Production source/dependency scan: no prohibited provider keys, API URLs, SDK imports, or client constructors.
- Browser check with the real local backend: sign-in, claim creation, original upload, provider-unconfigured retry
  status, manual review save, admin usage/health screen, and mobile layout. This used an isolated SQLite **test
  harness**, explicitly without AI responses; the production app uses Supabase and the real NVIDIA provider.
- Live NVIDIA authentication and five inference checks using synthetic inputs: passage embeddings, query
  embeddings (both 2048 dimensions), structured fast-model output, structured reasoning output, and structured
  vision output. Results and metadata-only usage records are in `data/verification/nvidia-live-checks.json`
  and `data/verification/nvidia-live-usage.jsonl`. These checks do not establish future quota availability.
- Supabase Data API authentication with the supplied service-role credential returned HTTP 200. Its schema
  initially contained no ClaimShield tables. API keys were stored only in the ignored root `.env`.
- Live Supabase PostgreSQL authentication with certificate and hostname verification. Corrected URI password
  encoding, used an IPv4 session pooler, and bundled Supabase's public root CA. The migration executed and
  pgvector 0.8.2 is installed. All six ClaimShield tables have RLS enabled; anon/authenticated table grants are
  zero. See `data/verification/supabase-sql-check.json` and `supabase-schema-check.json`.
- The isolated full workflow with real NVIDIA inference passed every check; its database is explicitly a
  SQLite test fixture. See `data/verification/workflow-20261004T154136Z/report.json`.
- Live browser registration, sample ingestion, grounded analysis, citation expansion, persisted human review,
  and preservation of unsaved notes/status during document refresh. The backend uses actual Supabase and NVIDIA.
- Final browser appeal export downloaded successfully to `Downloads/claimshield-appeal-draft.txt`, with the draft
  warning and cited source quotations. The authenticated export endpoint rejects anonymous access and another
  tenant in automated tests. Desktop/mobile proof is saved in `data/verification/live-workspace.jpg` and
  `live-mobile.jpg`. At a 390-pixel viewport, the final page width is 390 pixels with no horizontal overflow.
- Compiled frontend assets contain none of the configured private keys or administrator/JWT secrets.
  See `data/verification/frontend-secret-check.json`.
- All 25 checks in the complete live Supabase + NVIDIA workflow passed in
  `data/verification/workflow-20261004T160432Z/report.json`: authentication, three upload formats, actual
  pgvector embeddings/retrieval, cited analysis/chat/appeal, inference-free cache reuse, duplicate uploads,
  rejected invalid uploads/unsafe questions, reindexing, tenant/admin boundaries, sessions, persisted history,
  human review, usage aggregates, and provider health.

## Issues found and corrected

Vision metadata could omit the transcription field; it is now required. A valid cited appeal without a separate
findings list could be rejected; all evidence-bearing conclusion types are now accepted. Rejected responses
could remain cached; only fully verified reports are cached. Semantic verification now receives the cited source
context as well as short quotations. One bounded grounding correction is permitted, with full re-verification
before saving. The frontend review form now tracks saved server status while preserving unsaved edits.
Next.js's default 30-second rewrite proxy timeout could interrupt browser requests while the backend completed
them successfully. It is now 600 seconds, matching the client and gateway inference timeout.
Appeal export now uses an authenticated server download rather than a short-lived browser Blob URL.
A 35-second synthetic upstream request passed through Next's actual proxy implementation; see
`data/verification/long-request-proxy-check.json`. Appeal timeliness now also requires explicit cited support;
an excerpt without a deadline cannot justify asserting that a request is timely.
The final timeliness guard was verified against live NVIDIA/Supabase after the complete workflow pass; see
`data/verification/final-appeal-check.json`. Final export verification is in `appeal-export-check.json`.

Live Super analysis exposed reasoning prose spilling into the content field when a 1024-token reasoning budget
was exhausted. Defaults now use low-effort reasoning, a 4096-token reasoning budget, and an 8192-token output cap.
Strict JSON/schema validation and the single schema-repair limit remain enforced. Earlier failed test reports are
retained alongside subsequent runs; successful tests do not guarantee that future model responses or quotas will
always be available. Unsupported output remains rejected rather than displayed as a verified conclusion.

## Pending external verification

- EC2 deployment, ARM64 container builds/runtime, and production HTTPS. No AWS host or credentials were supplied.
  Compose/Dockerfiles and HTTPS configurations are provided for deployment.

## Docker Desktop verification

After repairing WSL and starting Docker's Linux engine, both application images built successfully on Linux
AMD64 and all three Compose containers started. The backend health check passed against Supabase. Checks
through Nginx at `http://localhost` passed for the frontend, unauthenticated access rejection, administrator
login, HttpOnly session cookies, authenticated claims, and NVIDIA reachability. A real NVIDIA inference request
from inside the backend container returned a 2048-dimensional passage embedding. Metadata-only reports are
`data/verification/docker-smoke-check.json` and `docker-inference-check.json`.

Native Tesseract 5.5.0 inside the backend container successfully read a generated fictional image. The backend
also ran as UID 10001 and could write its mounted upload directory. This verifies native container OCR; Tesseract
is still not installed directly on Windows. Idle observed memory was approximately 96 MiB backend, 37 MiB
frontend, and 18 MiB Nginx; these observations are not peak-load measurements or EC2 sizing guarantees.

The ignored root `.env` now contains the supplied Supabase API credentials, the project URL derived from their
project reference, the user's existing NVIDIA key, generated JWT/admin secrets, localhost origins, development
HTTP cookies, a complete session-pooler PostgreSQL URI, and a local upload directory. Secrets are never included
in these verification reports. Follow the
README's production cookie and TLS instructions when deploying beyond localhost.
