$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
Write-Host "=== AngelBot Windows PowerShell Launcher ===" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python 3.12 not found in PATH. Install from https://www.python.org/downloads/"
    exit 1
}

$versionOk = & python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python 3.12 is required; found $(& python --version 2>&1)."
    exit 1
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "FFmpeg not found in PATH. Music/video transcoding needs FFmpeg. Install with: winget install Gyan.FFmpeg"
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create .venv."
        exit $LASTEXITCODE
    }
    & ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { Write-Error "pip upgrade failed."; exit $LASTEXITCODE }
    & ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Dependency install failed; remove .venv and try again."
        exit $LASTEXITCODE
    }
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Fill in DISCORD_TOKEN, MALAK_OWNER_ID, GEMINI_API_KEY and re-run." -ForegroundColor Yellow
    notepad ".env"
    exit 0
}

& ".venv\Scripts\python.exe" bot.py --checkpoint-db
if ($LASTEXITCODE -ne 0) {
    Write-Error "Database checkpoint failed; the bot was not started."
    exit $LASTEXITCODE
}

& ".venv\Scripts\python.exe" bot.py
exit $LASTEXITCODE
