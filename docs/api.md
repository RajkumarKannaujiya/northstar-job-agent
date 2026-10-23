# API quick reference

All authenticated routes use `Authorization: Bearer <token>`.

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/auth/register` | Create account and receive token |
| POST | `/api/auth/login` | Authenticate |
| GET / PUT | `/api/profile` | Read or update profile, preferences, and answer bank |
| POST / GET / DELETE | `/api/resumes/upload`, `/api/resumes`, `/api/resumes/{id}` | Manage encrypted resumes |
| POST / GET | `/api/jobs`, `/api/jobs?limit=100` | Ingest or list normalized jobs |
| POST | `/api/jobs/{id}/analyze` | Score fit and select resume |
| POST | `/api/jobs/{id}/resume` | Override the selected resume for one job |
| POST | `/api/jobs/discover-mock` | Run synthetic demo discovery |
| POST / GET | `/api/applications`, `/api/applications?job_id={id}` | Create manual tracking record or list applications |
| POST | `/api/applications/{id}/questions?question=...` | Classify and answer from verified data where possible |
| POST | `/api/applications/{id}/transition` | Move through valid application states |
| POST | `/api/applications/{id}/failure` | Record a failure reason and event |
| POST | `/api/applications/{id}/confirm-submission` | Record platform confirmation and mark submitted |
| GET / POST / DELETE | `/api/platforms`, `/api/platforms/connect`, `/api/platforms/{name}` | Connector status and manual-only source setup |
| GET | `/api/automation/status` | Read automation controls |
| POST | `/api/automation/start`, `/api/automation/stop` | Set discovery state |
| PATCH | `/api/preferences` | Update search preferences |
| GET | `/api/notifications`, `/api/dashboard` | Read notifications and metrics |

Interactive OpenAPI docs are available at `/docs`.
