# One-time Cloud SQL bootstrap (MM-108). Run from the repo root in PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\cloudsql_bootstrap.ps1
#
# Starts the Cloud SQL Auth Proxy (your gcloud login = IAM check), then as the
# built-in `postgres` user: runs migrations, seeds demo data + users, grants
# the runtime service accounts the mm_app role, and runs the row-level
# security suite against Cloud SQL. The password is prompted for and only
# lives in this process's environment -- never written to disk or history.
# Idempotent: safe to re-run.

$ErrorActionPreference = "Stop"
$Instance = "marginmaestro-demo:us-central1:marginmaestro-pg"
$Port = 5433
$Python = ".venv\Scripts\python.exe"
$RuntimeUsers = @(
    "mm-api-sa@marginmaestro-demo.iam",
    "mm-agent-sa@marginmaestro-demo.iam",
    "mm-events-sa@marginmaestro-demo.iam",
    "mm-mcp-sa@marginmaestro-demo.iam"
)

$secure = Read-Host "Cloud SQL 'postgres' password" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))

# Prefer a proxy on PATH; fall back to %USERPROFILE%\bin (where it was
# downloaded -- that folder is on Git Bash's PATH but not PowerShell's).
$ProxyExe = (Get-Command cloud-sql-proxy -ErrorAction SilentlyContinue).Source
if (-not $ProxyExe) { $ProxyExe = Join-Path $env:USERPROFILE "bin\cloud-sql-proxy.exe" }
if (-not (Test-Path $ProxyExe)) { throw "cloud-sql-proxy not found (looked on PATH and in $ProxyExe)" }

Write-Host "Starting Cloud SQL Auth Proxy on 127.0.0.1:$Port ..."
$proxy = Start-Process -FilePath $ProxyExe -ArgumentList "--port", $Port, $Instance -PassThru -WindowStyle Hidden
try {
    $ready = $false
    foreach ($i in 1..30) {
        if ((Test-NetConnection 127.0.0.1 -Port $Port -WarningAction SilentlyContinue).TcpTestSucceeded) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "Proxy did not start listening on port $Port" }

    # Deployed-style settings: Postgres through the proxy, secrets from env
    # (not AWS). These override .env for this process only.
    $env:APP_ENV = "prod"
    $env:SECRETS_SOURCE = "env"
    $env:DB_DIALECT = "postgres"
    $env:DB_HOST = "127.0.0.1"
    $env:DB_PORT = "$Port"
    $env:DB_NAME = "marginmaestro"
    $env:DB_USER = "postgres"
    $env:DB_PASSWORD = $plain

    Write-Host "`n[1/5] Migrations"
    & .venv\Scripts\alembic.exe upgrade head
    if ($LASTEXITCODE -ne 0) { throw "alembic failed" }

    Write-Host "`n[2/5] Demo data (real prices + FRED rates)"
    & $Python -m persistence.batch_loader
    if ($LASTEXITCODE -ne 0) { throw "batch_loader failed" }

    Write-Host "`n[3/5] Demo users"
    & $Python -m persistence.seed_users
    if ($LASTEXITCODE -ne 0) { throw "seed_users failed" }

    Write-Host "`n[4/5] mm_app role for the runtime service accounts"
    & $Python -m persistence.db.grant_app_role @RuntimeUsers
    if ($LASTEXITCODE -ne 0) { throw "grant_app_role failed" }

    Write-Host "`n[5/5] Row-level security suite against Cloud SQL"
    $env:REQUIRE_DB = "1"
    & $Python -m pytest tests/integration/test_rls_live.py tests/integration/test_checkpoint_saver_live.py -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw "RLS / checkpoint tests failed" }

    Write-Host "`nCloud SQL bootstrap complete."
}
finally {
    Remove-Item Env:DB_PASSWORD -ErrorAction SilentlyContinue
    $plain = $null
    if ($proxy -and -not $proxy.HasExited) { Stop-Process -Id $proxy.Id -Force }
    Write-Host "Proxy stopped."
}
