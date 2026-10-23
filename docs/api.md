# API quick reference

All user routes use `Authorization: Bearer <token>`.

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/auth/register` | Create account and receive token |
| POST | `/api/auth/login` | Authenticate |
| GET / PUT | `/api/profile` | Read or update profile, preferences, and answer bank |
| POST / GET / DELETE | `/api/resumes/upload`, `/api/resumes`, `/api/resumes/{id}` | Manage encrypted resumes |
| GET | `/api/resumes/{id}/download` | Download an owned resume after decryption |
| PUT | `/api/resumes/{id}/preferred` | Choose the preferred resume |
| GET / DELETE | `/api/me/export`, `/api/me` | Export account data or permanently delete owned data |
| POST / GET | `/api/jobs`, `/api/jobs?limit=100` | Ingest or list normalized jobs |
| POST | `/api/jobs/{id}/analyze` | Score fit and select resume |
| POST | `/api/jobs/{id}/resume` | Override the selected resume for one job |
| POST | `/api/jobs/discover-mock` | Run synthetic demo discovery |
| GET / PUT | `/api/platforms/company-careers` | Read or save up to 10 Greenhouse/Lever company board tokens |
| POST | `/api/jobs/discover-company-careers` | Fetch published jobs from configured career boards |
| POST / GET | `/api/applications`, `/api/applications?job_id={id}` | Create manual tracking record or list applications |
| POST | `/api/applications/{id}/questions?question=...` | Classify and answer from verified data where possible |
| POST | `/api/applications/{id}/transition` | Move through valid application states |
| POST | `/api/applications/{id}/failure` | Record a failure reason and event |
| POST | `/api/applications/{id}/confirm-submission` | Record user-verified platform confirmation |
| GET / POST / DELETE | `/api/platforms`, `/api/platforms/connect`, `/api/platforms/{name}` | Connector status and manual-only source setup |
| GET | `/api/automation/status` | Read automation controls |
| POST | `/api/automation/start`, `/api/automation/stop` | Opt in/out of scheduled company-board refresh |
| PATCH | `/api/preferences` | Update search preferences |
| GET / PATCH / POST | `/api/notifications`, `/api/notifications/{id}`, `/api/notifications/read-all` | Read and update notifications |
| GET | `/api/dashboard` | Read dashboard counts and match metrics |

Celery Beat schedules refresh every six hours when the full Compose stack is running. Hosted APIs can use the protected, hidden `POST /api/internal/scheduled-discovery` route by setting `SCHEDULER_SHARED_SECRET` and the matching GitHub Actions secret. The job refreshes only opted-in users with configured company boards.

Greenhouse and Lever are read-only sources; their application links open employer-hosted forms. Other listed platforms currently use manual link tracking. Northstar does not log in to those accounts or submit applications for them.

Interactive OpenAPI docs are available at `/docs`.
