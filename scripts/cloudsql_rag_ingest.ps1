# Load the RAG corpus into Cloud SQL's pgvector store (MM-123). Run from the
# repo root in PowerShell, with Cloud SQL running (demo_online = true):
#   powershell -ExecutionPolicy Bypass -File scripts\cloudsql_rag_ingest.ps1
#
# Reads the source documents from the GCS bucket, redacts them (Sensitive
# Data Protection), embeds them with gemini-embedding-001 and upserts into
# rag_chunks -- the same pipeline the app uses, so retrieval on Cloud Run
# finds them. Idempotent: chunk ids are stable, re-running replaces them.
# The `postgres` password is prompted for and only lives in this process.

$ErrorActionPreference = "Stop"
$Instance = "marginmaestro-demo:us-central1:marginmaestro-pg"
$Port = 5433

$secure = Read-Host "Cloud SQL 'postgres' password" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))

$ProxyExe = (Get-Command cloud-sql-proxy -ErrorAction SilentlyContinue).Source
if (-not $ProxyExe) { $ProxyExe = Join-Path $env:USERPROFILE "bin\cloud-sql-proxy.exe" }
if (-not (Test-Path $ProxyExe)) { throw "cloud-sql-proxy not found (looked on PATH and in $ProxyExe)" }

$proxy = Start-Process -FilePath $ProxyExe -ArgumentList "--port", $Port, $Instance -PassThru -WindowStyle Hidden
try {
    $ready = $false
    foreach ($i in 1..30) {
        if ((Test-NetConnection 127.0.0.1 -Port $Port -WarningAction SilentlyContinue).TcpTestSucceeded) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "Proxy did not start listening on port $Port" }

    $env:APP_ENV = "prod"
    $env:SECRETS_SOURCE = "env"
    $env:GCP_PROJECT_ID = "marginmaestro-demo"
    $env:DB_DIALECT = "postgres"
    $env:DB_HOST = "127.0.0.1"
    $env:DB_PORT = "$Port"
    $env:DB_NAME = "marginmaestro"
    $env:DB_USER = "postgres"
    $env:DB_PASSWORD = $plain
    $env:VECTOR_STORE = "pgvector"
    $env:EMBEDDING_PROVIDER = "vertex"
    $env:DOCUMENT_STORE = "gcs"
    $env:GCS_DOCUMENTS_BUCKET = "marginmaestro-demo-documents"
    $env:REDACTOR_PROVIDER = "sdp"

    & .venv\Scripts\python.exe -m rag.ingest
    if ($LASTEXITCODE -ne 0) { throw "rag.ingest failed" }
}
finally {
    Remove-Item Env:DB_PASSWORD -ErrorAction SilentlyContinue
    if ($proxy -and -not $proxy.HasExited) { Stop-Process -Id $proxy.Id -Force }
}
