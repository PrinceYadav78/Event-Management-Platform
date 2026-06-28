# Deploying to Google Cloud Run (via Docker)

Deployment runs on **your** machine under **your** Google account (it builds under
your billing and needs your interactive `gcloud auth login`). Use the one-command
script.

## One-time setup
1. Install **Docker Desktop** and start it (whale icon = running).
2. Install the **Google Cloud CLI**: https://cloud.google.com/sdk/docs/install
3. Sign in (opens a browser):
   ```powershell
   gcloud auth login
   ```

## Deploy (now and after every code change)
From the project folder (`e:\Sanah\app`):
```powershell
.\deploy.ps1
```
The script: enables the needed APIs, creates the image registry, stores your
Firebase key + a generated `SECRET_KEY` in Secret Manager, builds the Docker
image, pushes it, grants permissions, and deploys. It prints the live URL at the end.

> First login: `admin@nps.com` / `admin123` — **change it immediately** on the Account page.

## Settings the script uses
- Project `key-period-473405-g2`, region `asia-south1` (edit the top of `deploy.ps1` to change)
- `--min-instances 0 --max-instances 1` (scale-to-zero, single instance — required by the SQLite mirror)
- `--no-cpu-throttling` (CPU always on while running → real-time listeners work)
- `--concurrency 250 --timeout 3600` (headroom for live/SSE connections)
- Env: `COOKIE_SECURE=true`, `WEB_CONCURRENCY=1`; secrets: `FIREBASE_KEY_JSON`, `SECRET_KEY`

## Check logs after deploy
```powershell
gcloud run services logs read nps-events --region asia-south1 --limit 50
```
Expect `[firestore] hydrated N document(s)` and no errors.

## If a secret-access error appears
The script grants it automatically, but if needed you can re-grant:
```powershell
$PN = gcloud projects describe key-period-473405-g2 --format="value(projectNumber)"
gcloud secrets add-iam-policy-binding firebase-key   --member="serviceAccount:$PN-compute@developer.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding app-secret-key --member="serviceAccount:$PN-compute@developer.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
```
