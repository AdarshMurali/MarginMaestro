# Copy the app secrets Cloud Run needs from AWS Secrets Manager
# (`marginmaestro/prod`) into GCP Secret Manager (`marginmaestro-prod`) as a
# new version (MM-123). Run from the repo root in PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\gcp_secret_from_aws.ps1
#
# Only the keys the GCP deployment reads are copied. The Azure DB_* keys, the
# OpenAI key and the S3 keys are left out on purpose: the JSON secret takes
# precedence over env vars, so they would override Cloud Run's GCP settings.
# Values are piped from AWS to GCP inside this process and never printed or
# written to disk; only key names and value lengths are shown.
#
# The new version holds ONLY these keys: re-running this drops keys added
# since (the WhatsApp keys, G6) -- run scripts\gcp_whatsapp_secrets.ps1 again
# afterwards.

$ErrorActionPreference = "Stop"
$Keys = @(
    "AUTH_BACKEND_SECRET",
    "SLACK_BOT_TOKEN",
    "SLACK_CHANNEL_ID",
    "SERVICENOW_INSTANCE_URL",
    "SERVICENOW_USERNAME",
    "SERVICENOW_PASSWORD"
)

$env:AWS_PROFILE = "lavanya"
$raw = aws secretsmanager get-secret-value --secret-id marginmaestro/prod --query SecretString --output text
if ($LASTEXITCODE -ne 0) { throw "could not read the AWS secret" }
$source = $raw | ConvertFrom-Json

$selected = [ordered]@{}
foreach ($key in $Keys) {
    $value = $source.$key
    if ([string]::IsNullOrEmpty($value)) { throw "AWS secret has no value for $key" }
    $selected[$key] = $value
    Write-Host ("  {0,-26} length {1}" -f $key, $value.Length)
}

$json = $selected | ConvertTo-Json -Compress
# Windows PowerShell 5.1 pipes to native commands as ASCII by default; use UTF-8
# (no BOM) so any non-ASCII character in a value survives.
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
# gcloud reads the payload from stdin (--data-file=-), so it never hits disk.
$json | gcloud secrets versions add marginmaestro-prod --project marginmaestro-demo --data-file=-
if ($LASTEXITCODE -ne 0) { throw "gcloud secrets versions add failed" }
Write-Host "Added a new version of marginmaestro-prod with $($Keys.Count) keys."
