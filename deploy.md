# Deploy on InMotion cPanel

This guide deploys the AI Website Health Monitor on InMotion cPanel using
Passenger / Setup Python App.

The app is FastAPI, but cPanel runs Python web apps through Passenger as WSGI.
This repo already includes the adapter:

```text
passenger_wsgi.py
requirements.txt  # includes a2wsgi
```

## 1. Recommended Hosting Setup

Use one of these URL layouts:

```text
https://monitor.yourdomain.com
```

or:

```text
https://yourdomain.com/monitor
```

A subdomain is cleaner and usually easier to troubleshoot.

Keep the app outside `public_html`:

```text
/home/YOUR_CPANEL_USER/amipi-monitor
```

Do not upload these local-only folders/files:

```text
venv/
__pycache__/
.pytest_cache/
reports/*.html
reports/*.json
reports/*.csv
reports/*.pdf
```

Keep `.env` private on the server. Do not commit or expose it under
`public_html`.

## 2. Upload The Files

Recommended: create a clean cPanel zip so local `venv/`, caches, reports,
and the private `.env` file are not uploaded by accident:

```bash
python scripts/create_cpanel_package.py
```

Upload and extract:

```text
dist/amipi-monitor-cpanel.zip
```

into:

```text
/home/YOUR_CPANEL_USER/amipi-monitor
```

Create `.env` separately on the server from the template in this guide.

Make sure these files exist on the server:

```text
app/
frontend/
reports/.gitkeep
scripts/cpanel_weekly_audit.py
scripts/verify_playwright.py
passenger_wsgi.py
requirements.txt
.env
```

Create runtime folders if they do not exist:

```bash
cd /home/YOUR_CPANEL_USER/amipi-monitor
mkdir -p reports logs tmp
```

## 3. Create The Python App In cPanel

In cPanel:

1. Open **Setup Python App**.
2. Click **Create Application**.
3. Choose **Python 3.11** or **Python 3.12**.
4. Set **Application root**:

```text
amipi-monitor
```

5. Set **Application URL**:

```text
monitor.yourdomain.com
```

or:

```text
yourdomain.com/monitor
```

6. Set **Application startup file**:

```text
passenger_wsgi.py
```

7. Set **Application Entry point**:

```text
application
```

8. Click **Create**.

After cPanel creates the app, copy the virtualenv activation command shown
inside Setup Python App. It will look similar to:

```bash
source /home/YOUR_CPANEL_USER/virtualenv/amipi-monitor/3.11/bin/activate
```

## 4. Install Python Dependencies

Open **cPanel Terminal** and run:

```bash
cd /home/YOUR_CPANEL_USER/amipi-monitor
source /home/YOUR_CPANEL_USER/virtualenv/amipi-monitor/3.11/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If cPanel offers **Run Pip Install** inside Setup Python App, you can use
that too, but Terminal gives clearer error output.

## 5. Configure `.env`

Create or edit:

```text
/home/YOUR_CPANEL_USER/amipi-monitor/.env
```

Use this production template:

```ini
SITE_BASE_URL=https://www.amipi.com
MAX_PAGES=200
CRAWL_DELAY_SECONDS=0.5
USE_PLAYWRIGHT_FOR_JS=false
REQUEST_TIMEOUT=15
USER_AGENT=AIWebsiteHealthMonitor/1.0 (+internal audit bot; contact: you@example.com)

AI_API_KEY=your_nvidia_api_key
AI_API_BASE=https://integrate.api.nvidia.com/v1
AI_MODEL=nvidia/nemotron-3-ultra-550b-a55b

PAGESPEED_API_KEY=your_pagespeed_api_key

SEO_API_KEY=your_dataforseo_login:your_dataforseo_password
DATAFORSEO_LOGIN=
DATAFORSEO_PASSWORD=
DATAFORSEO_LOCATION_CODE=2840
DATAFORSEO_LANGUAGE_CODE=en

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_TIMEOUT=120
SMTP_USE_SSL=false
SMTP_USE_STARTTLS=true
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_gmail_app_password
EMAIL_FROM=your_email@gmail.com
EMAIL_RECIPIENTS=recipient@example.com,another@example.com

# Monday 6:00 AM New York time.
WEEKLY_CRON=0 6 * * MON
WEEKLY_CRON_TIMEZONE=America/New_York
SCHEDULER_TEST_MODE=false

# Shared cPanel often needs this for Chromium.
PLAYWRIGHT_CHROMIUM_ARGS=--no-sandbox

REPORTS_DIR=reports
```

For Gmail, use a Gmail **App Password**, not your normal Gmail password.

For InMotion/domain SMTP on port `465`, use SSL instead of STARTTLS:

```ini
SMTP_HOST=your_inmotion_mail_host
SMTP_PORT=465
SMTP_TIMEOUT=120
SMTP_USE_SSL=true
SMTP_USE_STARTTLS=false
SMTP_USERNAME=your_mailbox@yourdomain.com
SMTP_PASSWORD=your_mailbox_password
EMAIL_FROM=your_mailbox@yourdomain.com
```

## 6. Install Playwright Chromium

The dashboard and audits can run without Chromium if `USE_PLAYWRIGHT_FOR_JS=false`,
but these features need Chromium:

- PDF download
- email PDF attachment
- optional JS-rendered crawling

Run this in cPanel Terminal:

```bash
cd /home/YOUR_CPANEL_USER/amipi-monitor
source /home/YOUR_CPANEL_USER/virtualenv/amipi-monitor/3.11/bin/activate
python -m playwright install chromium
```

Then verify Chromium can launch and generate a PDF:

```bash
python scripts/verify_playwright.py
```

Expected output:

```text
Playwright Chromium check passed: PDF generation works.
```

### If Playwright Fails

If `python -m playwright install chromium` fails while downloading, check:

- cPanel Terminal has outbound internet access.
- The account has enough disk space.
- The command is running inside the cPanel-created virtualenv.

If `python scripts/verify_playwright.py` fails with missing Linux libraries,
shared hosting may not provide the system packages Chromium needs. On shared
cPanel you usually cannot run:

```bash
python -m playwright install --with-deps chromium
```

because it needs system-level package installation. Ask InMotion support to
confirm whether your plan supports Playwright/Chromium. If not, deploy this
app on an InMotion VPS or other server where you can install system packages.

If Chromium fails with a sandbox error, keep this in `.env`:

```ini
PLAYWRIGHT_CHROMIUM_ARGS=--no-sandbox
```

## 7. Restart The App

From cPanel:

1. Open **Setup Python App**.
2. Select the app.
3. Click **Restart**.

Or from Terminal:

```bash
cd /home/YOUR_CPANEL_USER/amipi-monitor
mkdir -p tmp
touch tmp/restart.txt
```

## 8. Verify The Web App

Open:

```text
https://monitor.yourdomain.com/health
```

Expected response:

```json
{"status":"ok","site":"https://www.amipi.com"}
```

Then open:

```text
https://monitor.yourdomain.com
```

Click **Run audit now**.

After the audit completes, test:

```text
https://monitor.yourdomain.com/audit/latest
https://monitor.yourdomain.com/audit/latest/pdf
```

Then click **Email Report** from the dashboard.

## 9. Add A cPanel Cron Job

The app starts an APScheduler job when Passenger loads it, but shared cPanel
apps may sleep or restart. For reliable weekly email delivery, add a cPanel
Cron Job that runs the audit directly.

In cPanel:

1. Open **Cron Jobs**.
2. Set cron email to your admin email, or leave it blank and redirect output
   to a log file as shown below.
3. Add this schedule for Monday 6:00 AM New York time.

The in-app APScheduler uses `WEEKLY_CRON_TIMEZONE=America/New_York`, but cPanel
cron uses the server timezone. Set the cPanel cron time according to the
timezone shown in your cPanel account.

If your cPanel server timezone is already New York/Eastern time, use:

```text
Minute: 0
Hour: 6
Day: *
Month: *
Weekday: 1
```

If your cPanel server timezone is UTC, New York changes with daylight saving:

- During Eastern Daylight Time, Monday 6:00 AM New York is Monday 10:00 AM UTC.
- During Eastern Standard Time, Monday 6:00 AM New York is Monday 11:00 AM UTC.

For EDT, use:

```text
Minute: 0
Hour: 10
Day: *
Month: *
Weekday: 1
```

For EST, use:

```text
Minute: 0
Hour: 11
Day: *
Month: *
Weekday: 1
```

Use this command, replacing `YOUR_CPANEL_USER` and Python version:

```bash
cd /home/YOUR_CPANEL_USER/amipi-monitor && /home/YOUR_CPANEL_USER/virtualenv/amipi-monitor/3.11/bin/python scripts/cpanel_weekly_audit.py >> /home/YOUR_CPANEL_USER/amipi-monitor/logs/weekly_audit.log 2>&1
```

The script uses a lock file at:

```text
reports/.weekly_audit.lock
```

so a second cron run will skip itself if the previous audit is still running.

### Test The Cron Command Manually

Before saving the cron job, run the same command in Terminal:

```bash
cd /home/YOUR_CPANEL_USER/amipi-monitor && /home/YOUR_CPANEL_USER/virtualenv/amipi-monitor/3.11/bin/python scripts/cpanel_weekly_audit.py >> /home/YOUR_CPANEL_USER/amipi-monitor/logs/weekly_audit.log 2>&1
```

Check:

```text
reports/latest.html
reports/latest.json
reports/latest.pdf
logs/weekly_audit.log
```

## 10. Optional Keep-Alive Cron

If Passenger sleeps between requests and you want the dashboard to stay warm,
add a lightweight keep-alive cron every 15 minutes:

```bash
/usr/bin/curl -fsS https://monitor.yourdomain.com/health > /dev/null 2>&1
```

This is not a replacement for the weekly audit cron. It only keeps the web
process warm.

## 11. Deployment Checklist

Before considering the deployment complete:

- `passenger_wsgi.py` exists in the app root.
- cPanel startup file is `passenger_wsgi.py`.
- cPanel entry point is `application`.
- `python -m pip install -r requirements.txt` completed.
- `.env` exists on the server and contains production secrets.
- `python -m playwright install chromium` completed.
- `python scripts/verify_playwright.py` passed.
- `/health` returns `{"status":"ok", ...}`.
- Dashboard loads.
- Manual audit completes.
- `/audit/latest/pdf` downloads a PDF.
- Email Report sends successfully.
- cPanel weekly cron command works when run manually.

## 12. Troubleshooting

### 500 Error On `/audit/latest/pdf`

Run:

```bash
cd /home/YOUR_CPANEL_USER/amipi-monitor
source /home/YOUR_CPANEL_USER/virtualenv/amipi-monitor/3.11/bin/activate
python scripts/verify_playwright.py
```

If this fails, Chromium is not working on the host.

### Email Fails With `Server not connected`

Check the port/security pairing first:

```ini
# Port 587
SMTP_USE_SSL=false
SMTP_USE_STARTTLS=true

# Port 465
SMTP_USE_SSL=true
SMTP_USE_STARTTLS=false
```

Also keep `SMTP_TIMEOUT=120`. If it still fails, reduce attachments, use your
domain SMTP server, or ask InMotion whether outbound SMTP is throttled.

### Cron Does Not Run

Use absolute paths in the cron command. cPanel cron does not automatically
use your Python app virtualenv.

Check:

```text
/home/YOUR_CPANEL_USER/amipi-monitor/logs/weekly_audit.log
```

### App Changes Do Not Appear

Restart Passenger:

```bash
cd /home/YOUR_CPANEL_USER/amipi-monitor
touch tmp/restart.txt
```

### Setup Python App Is Missing

Ask InMotion support whether your account/server supports Python apps through
cPanel Setup Python App / Passenger. If not, use an InMotion VPS.

## References

- cPanel Cron Jobs documentation: https://docs.cpanel.net/cpanel/advanced/cron-jobs/
- cPanel Passenger Applications documentation: https://docs.cpanel.net/knowledge-base/web-services/using-passenger-applications/
