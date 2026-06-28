# =====================================================================
#  One-command deploy to Google Cloud Run (via Docker).
#
#  ONE-TIME setup before the first run:
#     1. Install Docker Desktop and START it (whale icon = running).
#     2. Install the Google Cloud CLI: https://cloud.google.com/sdk/docs/install
#     3. Run:  gcloud auth login
#
#  THEN, to deploy (now or any time after a code change), just run:
#     .\deploy.ps1
# =====================================================================

# NOTE: gcloud/docker print normal status to stderr; "Stop" would mistake that
# for a fatal error. We use "Continue" and check real failures via $LASTEXITCODE.
$ErrorActionPreference = "Continue"

# ---- settings (change REGION if you like) ----
$PROJECT = "key-period-473405-g2"
$REGION  = "asia-south1"                 # Mumbai — low latency for India
$REPO    = "nps"
$SERVICE = "nps-events"
$KEYFILE = "key-period-473405-g2-firebase-adminsdk-fbsvc-2d943f120e.json"
$REGHOST = "$REGION-docker.pkg.dev"
$IMAGE   = "$REGHOST/$PROJECT/$REPO/$SERVICE"
$TAG     = Get-Date -Format "yyyyMMdd-HHmmss"
$FULL    = "${IMAGE}:${TAG}"

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Die($m)  { Write-Host "`nERROR: $m" -ForegroundColor Red; exit 1 }
function CheckExit($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

# ---- pre-flight checks ----
Step "Checking prerequisites"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Die "Docker not installed." }
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Die "gcloud CLI not installed." }
docker info *> $null
if ($LASTEXITCODE -ne 0) { Die "Docker Desktop isn't running. Start it and re-run." }
if (-not (Test-Path $KEYFILE)) { Die "Firebase key file not found: $KEYFILE (run from the project folder)." }
$acct = (gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>$null)
if (-not $acct) { Die "Not logged in. Run:  gcloud auth login" }
Write-Host "   Logged in as: $acct"

# ---- project + APIs ----
Step "Setting project and enabling services"
gcloud config set project $PROJECT 2>$null; CheckExit "set project"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com 2>$null
CheckExit "enable services"

# ---- Artifact Registry repo (create if missing) ----
Step "Ensuring Artifact Registry repo '$REPO' exists"
gcloud artifacts repositories describe $REPO --location=$REGION *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "   creating repo '$REPO'..."
    gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION --description="NPS events app"
    CheckExit "create repo"
} else { Write-Host "   already exists" }

# ---- let Docker authenticate to the registry ----
Step "Configuring Docker auth for $REGHOST"
gcloud auth configure-docker $REGHOST --quiet 2>$null; CheckExit "configure-docker"

# ---- secrets (create if missing) ----
Step "Ensuring secrets exist"
gcloud secrets describe firebase-key *> $null
if ($LASTEXITCODE -ne 0) {
    gcloud secrets create firebase-key --data-file=$KEYFILE; CheckExit "create firebase-key"
    Write-Host "   created secret: firebase-key"
} else { Write-Host "   firebase-key exists" }
gcloud secrets describe app-secret-key *> $null
if ($LASTEXITCODE -ne 0) {
    $sk  = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))   # 64 hex chars
    $tmp = New-TemporaryFile
    [IO.File]::WriteAllText($tmp, $sk)
    gcloud secrets create app-secret-key --data-file=$tmp
    $rc = $LASTEXITCODE; Remove-Item $tmp -Force
    if ($rc -ne 0) { Die "create app-secret-key" }
    Write-Host "   created secret: app-secret-key"
} else { Write-Host "   app-secret-key exists" }

# ---- grant the Cloud Run runtime account access to the secrets ----
Step "Granting secret access to the runtime service account"
$PN = (gcloud projects describe $PROJECT --format="value(projectNumber)" 2>$null); CheckExit "get project number"
$SA = "$PN-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding firebase-key   --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" --quiet 2>$null | Out-Null
gcloud secrets add-iam-policy-binding app-secret-key --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" --quiet 2>$null | Out-Null

# ---- build + push ----
Step "Building image  $FULL"
docker build --platform linux/amd64 -t $FULL .; CheckExit "docker build"
Step "Pushing image to Artifact Registry"
docker push $FULL; CheckExit "docker push"

# ---- deploy ----
Step "Deploying to Cloud Run"
gcloud run deploy $SERVICE `
  --image $FULL `
  --region $REGION `
  --allow-unauthenticated `
  --min-instances 0 --max-instances 1 `
  --no-cpu-throttling `
  --concurrency 250 --timeout 3600 `
  --memory 512Mi --cpu 1 `
  --set-env-vars "WEB_CONCURRENCY=1,COOKIE_SECURE=true" `
  --set-secrets "SECRET_KEY=app-secret-key:latest,FIREBASE_KEY_JSON=firebase-key:latest"
CheckExit "cloud run deploy"

# ---- done ----
$URL = (gcloud run services describe $SERVICE --region $REGION --format="value(status.url)" 2>$null)
Write-Host "`n=====================================================" -ForegroundColor Green
Write-Host " DEPLOYED:  $URL" -ForegroundColor Green
Write-Host " Login: admin@nps.com / admin123  (change it after first login)" -ForegroundColor Green
Write-Host "=====================================================" -ForegroundColor Green
