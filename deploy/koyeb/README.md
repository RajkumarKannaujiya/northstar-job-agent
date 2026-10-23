# Koyeb + Supabase hobby deployment

This publishes the existing GitHub Pages dashboard and runs the FastAPI API on one Koyeb Free Web Service. Supabase Free supplies PostgreSQL and private S3-compatible resume storage. The existing GitHub Actions scheduler calls the API directly, so this hosted route does not need Redis, Celery Beat, or a separate worker service.

This is a $0 hobby setup within each provider's free limits, not an always-on or durable production guarantee. Koyeb's one Free Instance is limited to 512 MB RAM, 0.1 vCPU, and 2 GB SSD; it scales to zero after one hour without traffic, and free instances cannot run Worker Services or attach persistent volumes. Supabase Free includes 500 MB of database and 1 GB of file storage; a low-activity project may pause after a week. Keep an independent encrypted backup of important data. See [Koyeb instance limits](https://www.koyeb.com/docs/reference/instances), [Supabase pricing](https://supabase.com/pricing), and [Supabase project pausing](https://supabase.com/docs/guides/platform/free-project-pausing).

## 1. Create the Supabase project and private resume bucket

1. Create a Supabase Free project. Choose a region reasonably close to Koyeb's free region.
2. In Storage, create a **private** bucket named `northstar-resumes`.
3. Enable S3 access for Storage and create server-side S3 credentials. Supabase's S3 credentials grant broad storage access, so keep them only in Koyeb's secret environment variables.
4. From **Connect**, copy the **Session pooler** URL (port `5432`). Koyeb's Free Service uses the IPv4 shared pooler; session mode supports prepared statements and is also suitable for the startup migration. Replace the URL scheme with `postgresql+psycopg://` and preserve `sslmode=require`. URL-encode reserved characters in the database password. Do not use the transaction pooler on port `6543` for this app's migration connection.
5. Keep the Supabase database password and S3 access keys private. Do not commit them or send them in chat.

The S3 endpoint has this shape: `https://<project-ref>.storage.supabase.co/storage/v1/s3`. Copy the exact endpoint, region, and credentials from the Supabase Storage S3 settings. Northstar encrypts resume bytes with its Fernet key before sending them to the private bucket.

Supabase documents S3 compatibility at [S3 Compatibility](https://supabase.com/docs/guides/storage/s3/compatibility), server-side key handling at [S3 Authentication](https://supabase.com/docs/guides/storage/s3/authentication), and connection modes at [Connect to your database](https://supabase.com/docs/guides/database/connecting-to-postgres).

## 2. Deploy the API to Koyeb

1. Sign in to Koyeb and create an app/service from the public GitHub repository `RajkumarKannaujiya/northstar-job-agent`.
2. Choose **Dockerfile** as the builder. Set the work directory/build context to `backend` and the Dockerfile to `Dockerfile.koyeb`.
3. Select the **Free** instance in Frankfurt or Washington, D.C. Expose port `8000` over HTTP. Set a custom HTTP health check to `GET /ready`.
4. Add these environment variables. Enter secrets through Koyeb's secret fields; never put their values in this guide, GitHub files, or chat.

   | Variable | Value |
   | --- | --- |
   | `ENVIRONMENT` | `production` |
   | `PORT` | `8000` |
   | `DATABASE_URL` | Supabase Session Pooler URL using `postgresql+psycopg://` and `sslmode=require` |
   | `JWT_SECRET_KEY` | Unique random secret, at least 32 characters |
   | `FILE_ENCRYPTION_KEY` | A newly generated Fernet key; back it up securely |
   | `STORAGE_BACKEND` | `s3` |
   | `S3_ENDPOINT_URL` | Supabase S3 endpoint from Storage settings |
   | `S3_REGION` | Supabase S3 region from Storage settings |
   | `S3_BUCKET` | `northstar-resumes` |
   | `S3_ACCESS_KEY_ID` | Supabase server-side S3 access key |
   | `S3_SECRET_ACCESS_KEY` | Matching Supabase server-side S3 secret |
   | `CORS_ORIGINS` | `https://rajkumarkannaujiya.github.io` |
   | `SCHEDULER_SHARED_SECRET` | A separate unique random secret, at least 32 characters |
   | `MAX_RESUME_BYTES` | `10485760` |

5. Wait for the deployment to become healthy, then verify `https://<service-name>-<org>.koyeb.app/ready` returns `{"status":"ready","database":"ok"}` and `/health` returns `{"status":"ok",...}`. Koyeb provides HTTPS for the public Web Service domain.

Koyeb's GitHub and Dockerfile deployment options are documented in [Build and Deploy](https://www.koyeb.com/docs/build-and-deploy); its health probe can be configured as HTTP `/ready` in [Health Checks](https://www.koyeb.com/docs/run-and-scale/health-checks).

## 3. Connect GitHub Pages and scheduled discovery

In GitHub repository **Settings → Secrets and variables → Actions**:

- Add repository variable `NORTHSTAR_API_URL` with the Koyeb HTTPS origin only, for example `https://northstar-api-example.koyeb.app` (no trailing slash or path).
- Add repository secret `NORTHSTAR_SCHEDULER_SECRET` with the same value as Koyeb's `SCHEDULER_SHARED_SECRET`.

Then go to **Actions → Deploy GitHub Pages → Run workflow** once. When that run succeeds, reload the Pages site; sign-in and account creation should be enabled. The protected GitHub Actions scheduler calls the read-only company-board discovery endpoint every six hours. It processes only users who opted in and configured Greenhouse or Lever boards. The API has a cold start after idle periods, and the scheduled call is what wakes it for refresh.

## 4. Smoke test before real resume data

Use a synthetic test account and a synthetic PDF first:

1. Confirm `/ready` and `/health` are healthy.
2. Create an account, save profile preferences, configure one public Greenhouse or Lever board, and run discovery.
3. Upload the synthetic resume; verify download, export, preferred-resume selection, and account deletion.
4. Check Supabase Storage to confirm only an encrypted object is present in the private bucket.
5. Only after those checks pass, decide whether to upload a real resume. Keep a separate encrypted backup and preserve the Fernet key.

## Runtime differences from the full Docker Compose stack

- Koyeb hosts only the API; Supabase hosts the database and encrypted resume objects. GitHub Pages continues to host the static dashboard.
- The Koyeb image intentionally excludes Celery, Redis, Playwright, and test packages. No endpoint currently enqueues a Celery task. The hosted schedule uses the protected synchronous API endpoint instead.
- Koyeb free service may sleep after one hour of inactivity and cold-start on the next request. Free limits can change; monitor each provider's dashboard.
- These tiers provide no uptime SLA or guaranteed backups. Do not use this as the only copy of an important resume.
- Applications are not submitted automatically. Greenhouse/Lever integrations only read published jobs; other job boards remain manual until an official permitted integration is available.
