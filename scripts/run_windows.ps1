$ErrorActionPreference = "Stop"
# Arabic replies and paths must survive PowerShell 5.1's default OEM code page.
$utf8 = New-Object System.Text.UTF8Encoding $false
try {
    [Console]::OutputEncoding = $utf8
    [Console]::InputEncoding = $utf8
    $OutputEncoding = $utf8
} catch { }

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
}

# Always reconcile dependencies. The old version ran pip only while creating the venv, so a
# failure halfway through left a venv that looked complete and was never repaired.
& ".venv\Scripts\python.exe" -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Error "pip upgrade failed."; exit $LASTEXITCODE }
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Error "Dependency install failed; remove .venv and try again."
    exit $LASTEXITCODE
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Fill in DISCORD_TOKEN, ANGEL_OWNER_ID, GEMINI_API_KEY and re-run." -ForegroundColor Yellow
    notepad ".env"
    exit 0
}

# Safe on a fresh install: the checkpoint reports "no database yet" and exits 0.
& ".venv\Scripts\python.exe" bot.py --checkpoint-db
if ($LASTEXITCODE -ne 0) {
    Write-Error "Database checkpoint failed; the bot was not started."
    exit $LASTEXITCODE
}

& ".venv\Scripts\python.exe" bot.py
exit $LASTEXITCODE
