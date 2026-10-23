# Architecture and data flow

```text
Web dashboard → FastAPI → PostgreSQL
                       ├─ Resume parser → encrypted private file storage
                       ├─ Normalizer/deduper → canonical jobs + source mappings
                       ├─ Matcher/decision rules → explanations + review state
                       ├─ Application state and audit events
                       └─ Redis/Celery worker boundary → permitted adapters only
```

## Trust boundaries

- Resume text, job descriptions, recruiter-provided content, and application questions are untrusted data.
- Answers come from verified profile fields, resume evidence, or a user-maintained answer bank. Unknown, legal, demographic, and unsupported fields require user input.
- `SUBMITTED` is a terminally meaningful state and requires a platform confirmation signal and reference. Form filling and file upload do not count as submission.
- Challenge detection halts browser work. CAPTCHA, OTP, MFA, account blocks, and rate limits are never bypassed.

## Database entities

`users` own `profiles`, `resumes`, `job_sources`, `job_matches`, `applications`, `application_answers`, and `notifications`. `jobs` are canonical and link to source-specific IDs through `job_sources_mapping`. Applications connect a user, canonical job, chosen resume, match score, state, and immutable-style event history. `audit_logs` record sensitive operations.

## Service decomposition

`resume_parser` extracts text and evidence-backed fields; `matching` uses configurable weighted components; `decisions` applies eligibility constraints; `questions` maps only known facts; `platforms` defines source-specific integrations; `workers` provides a queue boundary. AI providers are injected via `AIProvider` so the product can run without external model calls.
