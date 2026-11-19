$ErrorActionPreference = "Stop"
Write-Host "=== AngelBot Windows PowerShell Launcher ===" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python 3.12 not found in PATH. Install from https://www.python.org/downloads/"
    exit 1
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "FFmpeg not found in PATH. Music/video transcoding needs FFmpeg. Install with: winget install Gyan.FFmpeg"
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
    & ".venv\Scripts\python.exe" -m pip install --upgrade pip
    & ".venv\Scripts\python.exe" -m pip install -r requirements.txt
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Fill in DISCORD_TOKEN, MALAK_OWNER_ID, GEMINI_API_KEY and re-run." -ForegroundColor Yellow
    notepad ".env"
    exit 0
}

& ".venv\Scripts\python.exe" bot.py --checkpoint-db
& ".venv\Scripts\python.exe" bot.py
