# Northstar — AI Job Search & Application Assistant

Northstar is a modular job-search platform foundation. It includes an authenticated API, PostgreSQL schema, encrypted resume file storage, a local dashboard, resume parsing, job matching, deduplication, policy checks, application tracking, Celery worker services, and synthetic portal fixtures.

The included portal is deliberately synthetic. No connector logs into or submits to a real job platform. Real platform work requires an official API or a reviewed, permitted browser flow for that platform; unsupported flows remain `MANUAL_ACTION_REQUIRED`.

## Start locally with Docker

1. Copy `.env.example` to `.env`.
2. Generate a unique JWT signing secret and Fernet key; never deploy the example placeholders. Example commands from the project directory:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. Set `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, and `FILE_ENCRYPTION_KEY` in `.env`. Set `CORS_ORIGINS=http://localhost:3000` for local use.
4. Start services:

   ```powershell
   docker compose up --build
   ```

5. Open [http://localhost:3000](http://localhost:3000). Create an account, upload a PDF/DOCX/TXT resume, and click **Run demo discovery**. The demo feed contains synthetic jobs only.
6. API docs are at [http://localhost:3000/docs](http://localhost:3000/docs).

Without Docker, install `backend/requirements.txt`, set `ENVIRONMENT=development`, and run `uvicorn app.main:app --reload` from `backend/`. This starts the API against a local SQLite database. The local development encryption key is fixed and must never be used for real resume data.

## Current vertical slice

- Email/password registration and bearer-token authentication with Argon2 password hashing.
- Structured user profile, preferences, and saved-answer bank.
- PDF, DOCX, and TXT extraction with conservative resume parsing; extracted fields should be reviewed by the user.
- Multiple resume support and best-fit resume ranking.
- Per-job manual resume override.
- Normalized jobs, source mappings, canonical company/title/location deduplication, match explanations, and missing explicit skills.
- Configurable decision thresholds, freshness/salary/location filters, daily/hourly/company tracking caps, duplicate protection, and an application state model.
- Unknown application questions stay unanswered and become manual actions; job descriptions and forms are treated as untrusted input.
- Application status can be recorded as `SUBMITTED` only with a supported confirmation signal and reference.
- Connector protocol, registry, Playwright lifecycle/form inspection boundary, and a synthetic mock portal.
- Redis/Celery worker scaffold, structured JSON logs, audit events, notifications, and Docker Compose services.
- Prometheus text metrics at the internal API route `/metrics`.
- Responsive local web dashboard for account setup, resume upload, mock discovery, matches, and tracking.

## Connector and model extension points

Implement `JobPlatformAdapter` in `backend/app/platforms/protocol.py`; register it in `registry.py`. Use only supported APIs or platform-permitted browser automation. Connector health should disable a source after repeated errors. A CAPTCHA, OTP, MFA, bot challenge, blocked automation, ambiguous field, or account restriction must stop the workflow and produce a manual action.

Implement the `AIProvider` protocol in `backend/app/services/ai_provider.py` for a selected provider. The default `RuleBasedProvider` is offline and conservative. It does not fabricate cover letters or unsupported answers. Job descriptions and user-provided application forms are untrusted content and must never override system policy or verified user facts.

The scheduler is intentionally not configured to repeatedly query external sites. Add schedules only after a permitted source connector and user opt-in are available. The worker currently exposes synthetic discovery and health tasks.

## Schema and migrations

The SQLAlchemy schema covers users, profiles, resumes and resume versions, the skills graph and evidence links, job sources, jobs and source mappings, job matches, applications, questions, saved answers, application events, platform accounts, automation tasks, notifications, audit logs, and system errors. Alembic initializes the schema; subsequent schema changes should be generated and reviewed as explicit migration revisions.

## Security and deployment notes

- Resume binaries are encrypted with Fernet before writing to private storage. The encryption key must be backed up securely; losing it makes stored resumes unrecoverable.
- Production must use TLS at the ingress, managed PostgreSQL with encryption at rest, encrypted backups, secret management/KMS, private object/file storage, and an edge rate limiter. Do not expose PostgreSQL or Redis publicly.
- The API uses bearer tokens for this initial vertical slice. The included dashboard keeps the token in tab-scoped `sessionStorage`; a production browser client should use secure, HttpOnly, SameSite cookies with CSRF defenses.
- Uploaded documents should be malware-scanned before parsing in a production environment. File type, extension, size, ownership, and private storage paths are validated here.
- The in-process API rate limit is a development safeguard; use a shared gateway limiter in a multi-replica deployment.
- Keep `/metrics` on the private service network or behind monitoring authentication; do not expose it publicly.
- `PlatformAccount` has no credential-writing API. Never send platform passwords to this application. Use official OAuth and encrypted, least-privilege tokens when available.
- The Docker Compose stack is a deployable starting point, not a hardened public SaaS release. Before production, add verified platform connectors, managed services, alerting, email delivery, admin RBAC, account/data export and deletion workflows, malware scanning, browser challenge pause/resume, and a security review.

## GitHub Pages frontend

GitHub Pages can publish the static dashboard in frontend/app; it cannot run this project's FastAPI API, PostgreSQL, Redis, Celery worker, or scheduler. The Pages workflow publishes the dashboard whenever main is updated. On GitHub Free, Pages requires a public repository, and the published site is public too. Keep resumes, environment files, API keys, and other private data out of the repository.

After creating the repository, set its Pages build source to GitHub Actions in Settings > Pages. The workflow then deploys the frontend on pushes to main.

To connect the dashboard, deploy the API and its database/worker services separately, then set NORTHSTAR_API_URL in frontend/app/config.js to the API's HTTPS origin. Replace the example API host in the Content-Security-Policy in frontend/app/index.html with that same origin, and add the Pages URL to the API's CORS_ORIGINS. Do not put secrets in config.js. Until an API is configured, the page explains that sign-in is unavailable and disables the form.

The existing Docker Compose stack remains the local full-stack route. GitHub Pages alone does not provide the full application for free: a separate API host and managed or self-hosted database/queue are still needed, and their free-tier availability and limits depend on the provider.

## Tests

Run from `backend/`:

```powershell
python -m pip install -r requirements.txt
python -m pytest
```

Tests use synthetic data and do not connect to real accounts or job sites.
