# $0 hobby deployment: GitHub Pages + Oracle Always Free

This keeps the existing Python/FastAPI/PostgreSQL/Redis/Celery stack. GitHub Pages serves the static dashboard; one Oracle Always Free VM runs the API, database, worker, scheduler, encrypted resume volume, and Caddy HTTPS proxy. A free DuckDNS hostname gives the API a TLS-capable hostname. This is a hobby deployment, not a production uptime guarantee.

## Free-tier limits and signup

Oracle currently lists up to 2 Ampere A1 OCPUs, 12 GB memory, and up to 200 GB combined block volumes in its Always Free tier. Oracle may require a phone number and payment card to verify signup; the card is not charged unless the account is upgraded. Always Free capacity can be unavailable in the selected region. See [Oracle Free Tier](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm) and [Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

DuckDNS provides a free dynamic DNS subdomain and HTTPS update API; keep its account token in the VM's private `.env`, never in GitHub or this repository. See the [DuckDNS API specification](https://www.duckdns.org/spec.jsp). Caddy obtains and renews the HTTPS certificate automatically after the hostname resolves to the VM and ports 80/443 are reachable.

## Provisioning outline

1. Create an Oracle Cloud Free Tier account yourself and provision an Ubuntu Ampere A1 VM in the account's home region. Choose no more than 2 OCPUs and 12 GB RAM. Attach only Always Free resources. A card may be required for account verification.
2. Allocate a public IPv4 address. In the VCN security list and the VM firewall, allow TCP 80/443; allow SSH only from your own IP. Do not open PostgreSQL 5432 or Redis 6379.
3. Create a DuckDNS subdomain and point it to the VM public IPv4. Keep the DuckDNS token private. Repoint it if the VM address changes.
4. Install Docker Engine and the Docker Compose plugin on the VM. Clone the public repository there after it is published.
5. Copy `.env.example` to `.env`, set file permissions to owner-only, and replace every sample value with generated secrets. Set at least:
   - `POSTGRES_PASSWORD`: a unique random password.
   - `JWT_SECRET_KEY`: a unique random value of at least 32 characters.
   - `FILE_ENCRYPTION_KEY`: output of `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
   - `SCHEDULER_SHARED_SECRET`: a separate random value of at least 32 characters.
   - `NORTHSTAR_API_DOMAIN`: the DuckDNS hostname, without `https://`.
   - `CORS_ORIGINS`: `https://rajkumarkannaujiya.github.io,http://localhost:3000` (origin only; no repository path).
   - `STORAGE_BACKEND=local`; the Compose encrypted-resume volume persists on the VM's block storage.
6. Start the stack from the repository root with `docker compose -f docker-compose.yml -f deploy/oracle/compose.public.yaml up -d --build`. Check `https://<your-duckdns-host>/ready` and verify the certificate in a browser.
7. In GitHub repository settings, enable Pages with the GitHub Actions source. Set the repository variable `NORTHSTAR_API_URL` to `https://<your-duckdns-host>` and the secret `NORTHSTAR_SCHEDULER_SECRET` to exactly the value stored as `SCHEDULER_SHARED_SECRET`. Push `main` to publish the dashboard and enable its scheduled discovery workflow.
8. In Northstar, add the public board token for each Greenhouse or Lever company you want to follow. Start scheduled discovery explicitly. Naukri, Indeed, LinkedIn, Apna, and other boards stay manual unless their owners provide an official API and approve access.

The free VM and free DNS hostname have no uptime or data durability SLA. Keep a separate encrypted backup of the PostgreSQL data and resume volume. Never store the only copy of an important resume here. The Pages workflow publishes the dashboard publicly; do not add a resume, account data, `.env`, or credentials to Git.

## Connector boundaries

Greenhouse and Lever are read-only public listing connectors. Application forms remain on the employer's site. LinkedIn's API access documentation says most API permissions and partner programs require explicit approval; use only connectors officially available to the account. No CAPTCHA, OTP, MFA, or bot challenge is bypassed. No job application is submitted automatically.
