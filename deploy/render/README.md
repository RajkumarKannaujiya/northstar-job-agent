# Render Free + Supabase Free deployment

This is a $0 hobby deployment for the existing dashboard and API. GitHub Pages hosts the dashboard. Render Free runs the FastAPI API. Supabase Free supplies PostgreSQL and private S3-compatible resume storage. GitHub Actions calls the protected discovery endpoint every six hours, so this hosted route does not require Redis, Celery Beat, or a worker service.

This is not an always-on or production-grade service. Render Free web services use 512 MB RAM and 0.1 CPU, spin down after 15 minutes without traffic, and can take about a minute to wake. Their filesystem is ephemeral. Supabase Free includes 500 MB of database and 1 GB of file storage, and a low-activity project may pause after seven days. Keep an independent encrypted backup; do not make this the only copy of a resume. See [Render Free limitations](https://render.com/docs/free), [Render compute plans](https://render.com/docs/compute-plans), [Supabase pricing](https://supabase.com/pricing), and [Supabase project pausing](https://supabase.com/docs/guides/platform/free-project-pausing).

## 1. Create the Supabase project and private resume bucket

1. In your Supabase account, create a project under the **Free** plan. Singapore / Asia-Pacific is a good region for users in India; match the Render service region when practical.
2. Set a strong database password in Supabase and store it in a password manager. Do not send it in chat or commit it.
3. In Storage, create a **private** bucket named `northstar-resumes`.
4. Enable S3 access for Storage and create server-side S3 credentials. Keep those credentials only in Render's secret environment variables. Supabase's S3 credentials grant broad storage access.
5. From **Connect**, copy the **Session pooler** connection string (port `5432`). Use the IPv4 session pooler, not the transaction pooler on port `6543`. Change the URI scheme to `postgresql+psycopg://`, preserve `sslmode=require`, and URL-encode reserved characters in the database password.
6. Copy the S3 endpoint, region, and credentials shown in Supabase Storage settings. The endpoint resembles `https://<project-ref>.storage.supabase.co/storage/v1/s3`.

Northstar encrypts resume bytes with its Fernet key before sending them to this private bucket. Supabase documents [S3 compatibility](https://supabase.com/docs/guides/storage/s3/compatibility), [server-side S3 credentials](https://supabase.com/docs/guides/storage/s3/authentication), and [database connection modes](https://supabase.com/docs/guides/database/connecting-to-postgres).

## 2. Deploy the API to Render Free

1. Create or sign in to a Render account and choose **New → Web Service**. Connect the GitHub repository `RajkumarKannaujiya/northstar-job-agent`, then select branch `main`. Render needs GitHub access for automatic deploys when this repository changes; review the requested scope and grant access only to this repository if that option is available. Do not add a payment method for this $0 setup.
2. Configure the service:

   | Setting | Value |
   | --- | --- |
   | Name | `northstar-job-agent-api` |
   | Region | Singapore, or the region nearest the Supabase project |
   | Language | Python 3 |
   | Root Directory | `backend` |
   | Build Command | `pip install -r requirements-runtime.txt` |
   | Start Command | `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers` |
   | Instance Type | Free |
   | Health Check Path | `/ready` |

3. Add these environment variables in Render. Use its secret option for credentials and keys.

   | Variable | Value |
   | --- | --- |
   | `ENVIRONMENT` | `production` |
   | `PORT` | `10000` |
   | `DATABASE_URL` | Supabase Session Pooler URL using `postgresql+psycopg://` and `sslmode=require` |
   | `JWT_SECRET_KEY` | Unique random string of at least 32 characters |
   | `FILE_ENCRYPTION_KEY` | Newly generated Fernet key; back it up securely |
   | `STORAGE_BACKEND` | `s3` |
   | `S3_ENDPOINT_URL` | Supabase S3 endpoint from Storage settings |
   | `S3_REGION` | Supabase S3 region from Storage settings |
   | `S3_BUCKET` | `northstar-resumes` |
   | `S3_ACCESS_KEY_ID` | Supabase server-side S3 access key |
   | `S3_SECRET_ACCESS_KEY` | Matching Supabase server-side S3 secret |
   | `CORS_ORIGINS` | `https://rajkumarkannaujiya.github.io` |
   | `SCHEDULER_SHARED_SECRET` | Separate unique random string of at least 32 characters |
   | `MAX_RESUME_BYTES` | `10485760` |

4. Create the service on the Free plan. After its first successful deploy, check `https://<service-name>.onrender.com/ready` for `{"status":"ready","database":"ok"}` and `/health` for `{"status":"ok",...}`.

Render documents [FastAPI deployment](https://render.com/docs/deploy-fastapi), [public web services](https://render.com/docs/web-services), and [regions](https://render.com/docs/regions).

## 3. Connect Pages and scheduled discovery

In GitHub repository **Settings → Secrets and variables → Actions**:

- Add repository variable `NORTHSTAR_API_URL` with the Render HTTPS origin only, for example `https://northstar-job-agent-api.onrender.com` (no trailing slash or path).
- Add repository secret `NORTHSTAR_SCHEDULER_SECRET` with the same value as Render's `SCHEDULER_SHARED_SECRET`.

Run **Actions → Deploy GitHub Pages → Run workflow** once so the dashboard receives the API URL. The protected scheduler workflow calls the read-only company-board discovery endpoint every six hours. It processes only users who opted in and configured Greenhouse or Lever boards. The first request after Render sleeps can take about a minute.

## 4. Smoke test before real resume data

Use a synthetic test account and a synthetic PDF first:

1. Confirm `/ready` and `/health` are healthy.
2. Create an account, save profile preferences, configure one public Greenhouse or Lever board, and run discovery.
3. Upload the synthetic resume; verify download, export, preferred-resume selection, and account deletion.
4. Check Supabase Storage to confirm only an encrypted object is present in the private bucket.
5. Only after those checks pass, decide whether to upload a real resume. Keep a separate encrypted backup and preserve the Fernet key.

## Runtime differences from the full Docker Compose stack

- Render hosts only the API; Supabase hosts the database and encrypted resume objects. GitHub Pages continues to host the static dashboard.
- This hosted runtime intentionally excludes Celery, Redis, Playwright, and test packages. No endpoint currently enqueues a Celery task. The hosted schedule uses the protected synchronous API endpoint instead.
- Render Free has no persistent disk; the service's local files disappear on restart, deploy, and sleep. Resume storage must stay on S3-compatible storage.
- The API may sleep after 15 minutes without traffic and cold-start on the next request. Free plans have no uptime SLA or guaranteed backups.
- Applications are not submitted automatically. Greenhouse and Lever integrations only read published jobs; other job boards remain manual until an official permitted integration is available.
