# Run locally and deploy on one low-cost EC2 instance

Prepared October 4, 2026 for this workspace. No AWS resources have been created.

Use one CPU-only **t4g.small (2 GiB RAM)** in **Mumbai, ap-south-1**, Ubuntu Server
24.04 LTS **Arm64**, and a **20 GiB encrypted gp3** root disk. The existing Compose
stack runs Nginx, Next.js, and FastAPI on that machine; PostgreSQL stays in Supabase
and inference stays on NVIDIA. Your current Supabase pooler is in Mumbai.

The container memory limits total 1,088 MiB before Linux and Docker overhead.
A micro/nano instance is too small for this configuration. This is a starting
configuration for light use; monitor memory and OCR workload before increasing traffic.

AWS currently offers 750 aggregate t4g.small instance-hours/month through December
31, 2026, including Mumbai and existing accounts. This covers instance compute, not
the whole deployment. Public IPv4 is $0.005/hour, approximately $3.65 for 730 hours.
Add 20 GiB of Mumbai gp3 storage, applicable traffic, snapshots, tax, and any domain,
Supabase, or NVIDIA charges. After the trial, add the current EC2 On-Demand rate.
Check account eligibility and the regional quote before launching.

Sources: [AWS T4g trial terms](https://aws.amazon.com/ec2/faqs/),
[public IPv4 pricing](https://aws.amazon.com/vpc/pricing/),
[EBS pricing](https://aws.amazon.com/ebs/pricing/),
[AWS calculator](https://calculator.aws/).

Backend dependency resolution succeeded for Python 3.12 on Linux ARM64. Local
Linux AMD64 Docker builds, container startup, native Tesseract execution, Supabase
readiness, and NVIDIA embedding inference have passed. ARM64 runtime, EC2, and
production HTTPS still need verification on the target machine. If ARM-specific issues
appear, use **t3a.small + Ubuntu x86_64** as the alternative; it has separate pricing.

## 1. Run locally

Install and start [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/)
with its WSL2 Linux-container backend. The current source-mode app uses port 3000;
the Compose gateway uses port 80.

In PowerShell:

```powershell
Set-Location "C:\Users\jayak\Music\ClaimShield AI"
docker compose version
```

In the existing local `.env`, use these settings and retain the configured keys,
database URI, administrator credentials, and JWT secret:

```dotenv
APP_ENV=development
COOKIE_SECURE=false
ALLOWED_ORIGINS=["http://localhost"]
PUBLIC_PORT=80
DATABASE_SSL=true
DATABASE_POOL_SIZE=1
```

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
curl.exe --fail http://localhost/api/health
```

Open http://localhost. Sign in using `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`.
The backend performs migrations at startup. Existing database users keep their
existing passwords; changing `ADMIN_PASSWORD` does not reset an existing account.

## 2. Launch EC2

In the AWS console:

1. Select **Asia Pacific (Mumbai)**. Launch **one** Ubuntu Server 24.04 LTS **Arm64**
   instance, type **t4g.small**, purchase option **On-Demand**.
2. Create/download a `.pem` SSH key. Keep it on your Windows machine.
3. Use the default VPC and a public subnet with an Internet Gateway. Enable a public
   IPv4 address. A NAT gateway or load balancer is unnecessary for this deployment.
4. Choose **20 GiB gp3**, encrypted, default baseline IOPS/throughput.
5. Security group inbound: **22 only from your IP**, **80 and 443 from 0.0.0.0/0**.
   Ports 3000, 8000, and 5432 do not need public inbound rules. Keep normal outbound
   access for package downloads, HTTPS to NVIDIA, and TCP 5432 to Supabase.
6. Under the instance's **Actions → Instance settings → Change credit specification**,
   choose **Standard** to avoid surplus CPU-credit charges. Sustained builds/OCR may
   slow down when credits run out. T4g otherwise defaults to Unlimited.
7. Allocate and associate **one Elastic IP** if you need a stable address for DNS.
   This replaces the auto-assigned address; use the Elastic IP in subsequent commands.
   Retained Elastic IPs and EBS disks still cost money when the instance is stopped.
8. Set a monthly AWS budget notification appropriate to your chosen quote.

Use your existing DNS provider to create an **A record**, for example
`claimshield.yourdomain.com`, pointing to that IP. Keep it DNS-only during certificate
issuance. Remove any stale AAAA record pointing elsewhere. Wait for DNS propagation.
Replace every example domain/IP/key path below with your own values.

## 3. Upload this workspace

A clean source archive has been prepared at `data/deploy/claimshield-source.tar.gz`.
It excludes `.env`, virtual environments, node_modules, build output, uploaded
documents, and test artifacts. Transfer the existing `.env` separately over SSH.
This copies configuration, not the local upload volume.

In Windows PowerShell, connect first:

```powershell
ssh -i "C:\path\claimshield.pem" ubuntu@PUBLIC_IP
```

On EC2:

```bash
mkdir -p /home/ubuntu/claimshield
chmod 700 /home/ubuntu/claimshield
touch /home/ubuntu/claimshield/.env
chmod 600 /home/ubuntu/claimshield/.env
exit
```

Back in Windows PowerShell:

```powershell
Set-Location "C:\Users\jayak\Music\ClaimShield AI"
scp -i "C:\path\claimshield.pem" ".\data\deploy\claimshield-source.tar.gz" ubuntu@PUBLIC_IP:/home/ubuntu/
scp -i "C:\path\claimshield.pem" ".\.env" ubuntu@PUBLIC_IP:/home/ubuntu/claimshield/.env
ssh -i "C:\path\claimshield.pem" ubuntu@PUBLIC_IP
```

On EC2:

```bash
cd /home/ubuntu/claimshield
tar -xzf /home/ubuntu/claimshield-source.tar.gz
chmod 600 .env
```

## 4. Install Docker and add build swap

Run on EC2. These use [Docker's Ubuntu repository](https://docs.docker.com/engine/install/ubuntu/).

```bash
sudo apt update
sudo apt install -y ca-certificates curl certbot
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker compose version
```

On this fresh instance, add a 2 GiB swap file once. If `/swapfile` already exists,
inspect it instead of recreating it. Swap helps builds survive temporary memory
pressure; it does not replace runtime RAM.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

Bound Docker logs so they do not fill the small disk. On a fresh Docker install,
create `/etc/docker/daemon.json` with the following contents. If it already exists,
merge the settings instead of overwriting it:

```bash
sudo nano /etc/docker/daemon.json
```

```json
{"log-driver":"local","log-opts":{"max-size":"10m","max-file":"3"}}
```

```bash
sudo systemctl restart docker
```

## 5. Configure the EC2 copy of .env

```bash
cd /home/ubuntu/claimshield
nano .env
```

Change these entries, replacing the domain:

```dotenv
APP_ENV=production
AI_PROVIDER=nvidia
COOKIE_SECURE=true
ALLOWED_ORIGINS=["https://claimshield.yourdomain.com"]
DATABASE_SSL=true
DATABASE_POOL_SIZE=1
LOW_MEMORY_MODE=true
DEMO_MODE=false
PUBLIC_PORT=80
```

Retain the verified `DATABASE_URL` with `postgresql+asyncpg://` and the Supabase
**session pooler on port 5432**, and retain the tested NVIDIA model settings.
Supabase anon/service-role keys cannot replace this SQL URI. Keep all keys on the
backend; never add them to `NEXT_PUBLIC_*` variables.

Use a strong `JWT_SECRET` and strong administrator credentials. To create a new
production JWT secret, run `openssl rand -hex 32` and paste the result into `.env`.
A changed secret invalidates existing sessions. The existing Supabase database is
shared with your local app, including its existing accounts and test records.

## 6. Build sequentially and obtain HTTPS

Build on EC2 so Docker selects native ARM64 images. Stop after any failed command
and inspect its error before continuing. Do not copy Windows node_modules to EC2.

```bash
sudo docker compose config --quiet
sudo docker compose build backend
sudo docker compose build frontend
```

Obtain a certificate before starting Nginx. This requires your real domain to
resolve to EC2 and port 80 to be reachable. If you already started the HTTP stack,
run `sudo docker compose stop nginx` first.

```bash
DOMAIN=claimshield.yourdomain.com
CERT_EMAIL=you@yourdomain.com
sudo certbot certonly --standalone --non-interactive --agree-tos --email "$CERT_EMAIL" --cert-name "$DOMAIN" -d "$DOMAIN"
mkdir -p deploy/certs
sudo install -m 644 "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" deploy/certs/fullchain.pem
sudo install -m 600 "/etc/letsencrypt/live/$DOMAIN/privkey.pem" deploy/certs/privkey.pem
sudo docker compose -f compose.yaml -f compose.tls.yaml config --quiet
sudo docker compose -f compose.yaml -f compose.tls.yaml up -d
```

The supplied TLS override enables port 443 and redirects HTTP to HTTPS. Use
**both Compose files** for production operations. Secure cookies require HTTPS.

## 7. Configure certificate renewal

The supplied Nginx configuration does not serve ACME challenge files. Certbot
standalone therefore needs Nginx stopped briefly during renewal, then restarted
with the renewed certificates. Backend/frontend continue running.
See [Certbot standalone and renewal documentation](https://eff-certbot.readthedocs.io/en/stable/using.html).

Create the pre-hook:

```bash
sudo install -d /etc/letsencrypt/renewal-hooks/pre /etc/letsencrypt/renewal-hooks/post
sudo tee /etc/letsencrypt/renewal-hooks/pre/claimshield-stop >/dev/null <<'EOF'
#!/bin/sh
set -eu
cd /home/ubuntu/claimshield
/usr/bin/docker compose -f compose.yaml -f compose.tls.yaml stop nginx
EOF
```

Create the post-hook **with your real domain in both certificate paths**:

```bash
sudo tee /etc/letsencrypt/renewal-hooks/post/claimshield-start >/dev/null <<'EOF'
#!/bin/sh
set -eu
cd /home/ubuntu/claimshield
install -m 644 /etc/letsencrypt/live/claimshield.yourdomain.com/fullchain.pem deploy/certs/fullchain.pem
install -m 600 /etc/letsencrypt/live/claimshield.yourdomain.com/privkey.pem deploy/certs/privkey.pem
/usr/bin/docker compose -f compose.yaml -f compose.tls.yaml up -d nginx
EOF
sudo chmod 755 /etc/letsencrypt/renewal-hooks/pre/claimshield-stop /etc/letsencrypt/renewal-hooks/post/claimshield-start
sudo systemctl enable --now certbot.timer
sudo certbot renew --dry-run
```

Confirm the dry run passes and the site returns afterward. These hook scripts are
for this single-site instance; they also briefly interrupt HTTPS during the dry run.

## 8. Verify the actual deployment

```bash
cd /home/ubuntu/claimshield
sudo docker compose -f compose.yaml -f compose.tls.yaml ps
sudo docker compose -f compose.yaml -f compose.tls.yaml logs --tail=100 backend
sudo docker compose -f compose.yaml -f compose.tls.yaml exec backend tesseract --version
curl --fail https://claimshield.yourdomain.com/api/health
curl -I http://claimshield.yourdomain.com
sudo docker stats --no-stream
df -h /
```

Expect the backend healthy, all three containers running, readiness HTTP 200, and
HTTP redirecting to HTTPS. Readiness checks PostgreSQL; it does not prove NVIDIA
inference is available. In your browser, sign in, use **Provider & usage → Check
provider**, then create a fictional claim, upload a small text/PDF and scanned image,
wait for processing, run analysis/chat/appeal, and download the appeal and originals.
Confirm review notes persist after a backend restart. Use fictional documents for
this deployment check. This validates ARM runtime, OCR, NVIDIA, HTTPS cookies, and
the persistent upload volume together.

## 9. Updates and data persistence

Uploads live in the `claimshield_uploads` Docker volume on EC2; structured records
and embeddings live in Supabase. Fresh EC2 deployment does not copy local originals.
If you need existing originals on EC2, migrate their upload storage as well.

Back up **both** the upload volume/root disk and the Supabase database. An EC2 disk
snapshot alone is not a database backup. Set snapshot retention to control costs.
Do not run `docker compose down -v`: it deletes this instance's uploaded originals.

For an update, upload updated source while preserving `.env` and `deploy/certs`, then:

```bash
cd /home/ubuntu/claimshield
sudo docker compose -f compose.yaml -f compose.tls.yaml build backend
sudo docker compose -f compose.yaml -f compose.tls.yaml build frontend
sudo docker compose -f compose.yaml -f compose.tls.yaml up -d
curl --fail https://claimshield.yourdomain.com/api/health
```

The restart policy and enabled Docker service bring containers back after reboot.
One instance has downtime during host failures or restarts. CPU credit throttling,
memory limits, provider quotas, and disk usage determine when to increase capacity.
