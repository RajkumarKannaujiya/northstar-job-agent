# Northstar — AI Job Search & Application Assistant

Northstar is a modular job-search platform foundation. It includes an authenticated API, PostgreSQL schema, encrypted resume file storage, a local dashboard, resume parsing, job matching, deduplication, policy checks, application tracking, Celery worker services, and synthetic portal fixtures.

The synthetic portal is kept for repeatable demos. The backend also reads published jobs from employer-configured Greenhouse and Lever boards through their public job-board APIs. These are read-only integrations: applications open on the employer's site and must be completed there. Naukri, Indeed, LinkedIn, Apna, Foundit, Internshala, Wellfound, Cutshort, Shine, TimesJobs, and Glassdoor are manual link sources until an official, permitted integration is available.

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
- Multiple resume support, best-fit resume ranking, user-selected preferred resume, authenticated resume download, and deletion.
- Parsed personal, education, experience, and explicit-skill fields are added to empty profile fields; existing user-entered values are not overwritten.
- Per-job manual resume override.
- Normalized jobs, source mappings, canonical company/title/location deduplication, match explanations, and missing explicit skills.
- Configurable decision thresholds, freshness/salary/location filters, daily/hourly/company tracking caps, duplicate protection, and an application state model.
- Unknown application questions stay unanswered and become manual actions; job descriptions and forms are treated as untrusted input.
- Application status can be recorded as `SUBMITTED` only with a supported confirmation signal and reference.
- Connector protocol, registry, Playwright lifecycle/form inspection boundary, and synthetic mock portal.
- Read-only Greenhouse and Lever company-board discovery, normalization, matching, deduplication, and 6-hour opt-in refresh through Celery Beat or the protected GitHub Actions scheduler.
- Redis/Celery workers, structured JSON logs, audit events, user notifications, notification read state, account export/deletion, and Docker Compose services.
- Encrypted resume storage on local persistent volumes or private S3-compatible object storage (including Cloudflare R2).
- Prometheus text metrics at the internal API route `/metrics`.
- Responsive local web dashboard for account setup, resume upload, mock discovery, matches, and tracking.

## Connector and model extension points

Implement `JobPlatformAdapter` in `backend/app/platforms/protocol.py`; register it in `registry.py`. Greenhouse and Lever adapters only fetch published listings. Their application submission APIs require employer authorization; Northstar does not submit through them. For other boards, use only supported APIs or platform-permitted browser automation. A CAPTCHA, OTP, MFA, bot challenge, blocked automation, ambiguous field, or account restriction must stop the workflow and produce a manual action.

Implement the `AIProvider` protocol in `backend/app/services/ai_provider.py` for a selected provider. The default `RuleBasedProvider` is offline and conservative. It does not fabricate cover letters or unsupported answers. Job descriptions and user-provided application forms are untrusted content and must never override system policy or verified user facts.

Company-board discovery is read-only and limited to configured public Greenhouse and Lever boards. Refresh can run every six hours through Celery Beat in the full Compose stack, or through the protected GitHub Actions scheduler. Users must opt in, and no applications are submitted automatically. Other platforms remain manual link-out sources.

## Schema and migrations

The SQLAlchemy schema covers users, profiles, resumes and resume versions, the skills graph and evidence links, job sources, jobs and source mappings, job matches, applications, questions, saved answers, application events, platform accounts, automation tasks, notifications, audit logs, and system errors. Alembic initializes the schema; subsequent schema changes should be generated and reviewed as explicit migration revisions.

## Security and deployment notes

- Resume binaries are encrypted with Fernet before writing to private storage. The encryption key must be backed up securely; losing it makes stored resumes unrecoverable.
- For a host with an ephemeral filesystem, set `STORAGE_BACKEND=s3` and configure a private S3-compatible bucket. Northstar encrypts the object contents before upload; object-storage credentials and the Fernet key belong in the provider's secret manager.
- Production must use TLS at the ingress, managed PostgreSQL with encryption at rest, encrypted backups, secret management/KMS, private object/file storage, and an edge rate limiter. Do not expose PostgreSQL or Redis publicly.
- The API uses bearer tokens for this initial vertical slice. The included dashboard keeps the token in tab-scoped `sessionStorage`; a production browser client should use secure, HttpOnly, SameSite cookies with CSRF defenses.
- Uploaded documents should be malware-scanned before parsing in a production environment. File type, extension, size, ownership, and private storage paths are validated here.
- The in-process API rate limit is a development safeguard; use a shared gateway limiter in a multi-replica deployment.
- Keep `/metrics` on the private service network or behind monitoring authentication; do not expose it publicly.
- Account export is available at `GET /api/me/export`; authenticated account and associated-data deletion is `DELETE /api/me`.
- `PlatformAccount` has no credential-writing API. Never send platform passwords to this application. Use official OAuth and encrypted, least-privilege tokens when available.
- The Docker Compose stack is a deployable starting point, not a hardened public SaaS release. Before production, add verified platform connectors, managed services, alerting, email delivery, admin RBAC, account/data export and deletion workflows, malware scanning, browser challenge pause/resume, and a security review.

## GitHub Pages frontend

GitHub Pages can publish the static dashboard in frontend/app; it cannot run this project's FastAPI API, PostgreSQL, Redis, Celery worker, or scheduler. The Pages workflow publishes the dashboard whenever main is updated. On GitHub Free, Pages requires a public repository, and the published site is public too. Keep resumes, environment files, API keys, and other private data out of the repository. See [GitHub's Pages requirements](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site).

After creating the repository, set its Pages build source to GitHub Actions in Settings > Pages. The workflow then deploys the frontend on pushes to main. Set the repository variable `NORTHSTAR_API_URL` to the deployed HTTPS API origin; the workflow injects it into `config.js` at build time.

To connect the dashboard, deploy the API and its database/worker services separately, then set the API origin and `CORS_ORIGINS` to include the Pages URL. Do not put secrets in config.js. Until an API is configured, the page explains that sign-in is unavailable and disables the form. For periodic discovery without a continuously running Celery Beat service, configure `SCHEDULER_SHARED_SECRET` on the API and the matching GitHub Actions secret `NORTHSTAR_SCHEDULER_SECRET`. The scheduled workflow calls only the authenticated internal refresh endpoint; the user must opt in within the dashboard.

The existing Docker Compose stack is the local full-stack route. A public GitHub Pages site can host only the dashboard. No hosted provider offers this entire stateful FastAPI, PostgreSQL, Redis, Celery, scheduler, and persistent resume-storage stack with a production uptime guarantee at $0. Free plans have limits: for example, Render free web services sleep after 15 minutes of inactivity, free Postgres expires after 30 days, local disks/background workers are unavailable on free compute, and Supabase free projects pause after a week of inactivity. These can support a hobby preview, not reliable long-running job automation or sole-copy resume storage. See [Render free-instance limits](https://render.com/docs/free) and [Supabase pricing](https://supabase.com/pricing). Use backups and durable database/storage before storing irreplaceable personal data.

## Tests

Run from `backend/`:

```powershell
python -m pip install -r requirements.txt
python -m pytest
```

Tests use synthetic data and do not connect to real accounts or job sites.
