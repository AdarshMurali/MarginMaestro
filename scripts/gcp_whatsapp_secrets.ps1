# Add the WhatsApp keys (G6, MM-118/MM-133) to the GCP JSON secret
# `marginmaestro-prod` as a new version. Run from the repo root in PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\gcp_whatsapp_secrets.ps1
#
# - WHATSAPP_TOKEN        copied from AWS Secrets Manager `marginmaestro/prod`
#                         (ap-south-1, profile lavanya), key `whatsapptoken`
# - WHATSAPP_APP_SECRET   prompted: Meta app dashboard > App settings > Basic > App secret
#                         (verifies X-Hub-Signature-256 on the webhook)
# - WHATSAPP_VERIFY_TOKEN prompted: any long random string; enter the same one
#                         in Meta's webhook configuration
# - WHATSAPP_RECIPIENT    prompted: the verified test phone, digits with country
#                         code (demo: every counterparty maps to it)
#
# Unlike gcp_secret_from_aws.ps1 (which writes a fresh set of keys), this one
# MERGES: it reads the latest version, keeps every existing key and adds or
# replaces only the four above. Values stay in this process's memory and are
# piped to gcloud on stdin -- never printed or written to disk; only key names
# and value lengths are shown.

$ErrorActionPreference = "Stop"
$Project = "marginmaestro-demo"
$Secret = "marginmaestro-prod"

function Read-Secret([string]$prompt) {
    $secure = Read-Host $prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}

# gcloud / aws print UTF-8; decode their output as UTF-8 too.
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false

# 1. The access token from AWS.
$env:AWS_PROFILE = "lavanya"
$raw = aws secretsmanager get-secret-value --region ap-south-1 --secret-id marginmaestro/prod --query SecretString --output text
if ($LASTEXITCODE -ne 0) { throw "could not read the AWS secret" }
$token = ($raw | ConvertFrom-Json).whatsapptoken
$raw = $null
if ([string]::IsNullOrEmpty($token)) { throw "AWS secret has no value for whatsapptoken" }

# 2. The values only you have.
$new = [ordered]@{
    "WHATSAPP_TOKEN"        = $token
    "WHATSAPP_APP_SECRET"   = Read-Secret "Meta App Secret"
    "WHATSAPP_VERIFY_TOKEN" = Read-Secret "Webhook verify token (same value goes into Meta's webhook form)"
    "WHATSAPP_RECIPIENT"    = (Read-Secret "Verified test phone (digits with country code)") -replace "[^0-9]", ""
}
$token = $null
foreach ($key in $new.Keys) {
    if ([string]::IsNullOrEmpty($new[$key])) { throw "$key is empty" }
}

# 3. Merge into the latest version of the GCP secret.
$current = (gcloud secrets versions access latest --secret $Secret --project $Project) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "could not read the latest version of $Secret" }
$merged = [ordered]@{}
($current | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $merged[$_.Name] = $_.Value }
$current = $null
foreach ($key in $new.Keys) { $merged[$key] = $new[$key] }

Write-Host "Keys in the new version (name, value length):"
foreach ($key in $merged.Keys) {
    $marker = if ($new.Contains($key)) { "  <- added/replaced" } else { "" }
    Write-Host ("  {0,-26} length {1}{2}" -f $key, ([string]$merged[$key]).Length, $marker)
}

$json = $merged | ConvertTo-Json -Compress
$merged = $null
$new = $null
# Windows PowerShell 5.1 pipes to native commands as ASCII by default; use UTF-8
# (no BOM) so any non-ASCII character in a value survives.
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
# gcloud reads the payload from stdin (--data-file=-), so it never hits disk.
$json | gcloud secrets versions add $Secret --project $Project --data-file=-
if ($LASTEXITCODE -ne 0) { throw "gcloud secrets versions add failed" }
$json = $null
Write-Host "Added a new version of $Secret. Cloud Run reads it on the next cold start (or redeploy)."
