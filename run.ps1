# GeoLedger Startup Script for Windows PowerShell
# Run this script to start the GeoLedger application

Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 58) -ForegroundColor Cyan
Write-Host "  GeoLedger - Intelligent Land Record System" -ForegroundColor Cyan
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 58) -ForegroundColor Cyan
Write-Host ""

# Check Python
Write-Host "[1/5] Checking Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  ✓ Found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Python not found. Please install Python 3.10+" -ForegroundColor Red
    exit 1
}

# Check virtual environment
Write-Host "[2/5] Checking virtual environment..." -ForegroundColor Yellow
$venvActivate = if (Test-Path ".venv\Scripts\Activate.ps1") {
    ".venv\Scripts\Activate.ps1"
} elseif (Test-Path "venv\Scripts\Activate.ps1") {
    "venv\Scripts\Activate.ps1"
} else {
    $null
}

if ($venvActivate) {
    Write-Host "  ✓ Virtual environment exists" -ForegroundColor Green
    Write-Host "  Activating..." -ForegroundColor Gray
    & $venvActivate
} else {
    Write-Host "  ⚠ Virtual environment not found. Creating..." -ForegroundColor Yellow
    python -m venv .venv
    & ".venv\Scripts\Activate.ps1"
    Write-Host "  ✓ Virtual environment created and activated" -ForegroundColor Green
}

# Install dependencies
Write-Host "[3/5] Checking dependencies..." -ForegroundColor Yellow
if (Test-Path "requirements.txt") {
    Write-Host "  Installing/updating packages..." -ForegroundColor Gray
    python -m pip install --quiet --upgrade pip
    python -m pip install --quiet -r requirements.txt
    Write-Host "  ✓ Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "  ✗ requirements.txt not found" -ForegroundColor Red
    exit 1
}

# Check .env
Write-Host "[4/5] Checking configuration..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Write-Host "  ⚠ .env not found. Copying from .env.example..." -ForegroundColor Yellow
        Copy-Item ".env.example" ".env"
        Write-Host "  ✓ .env created (using defaults)" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ No .env file (using built-in defaults)" -ForegroundColor Yellow
    }
} else {
    Write-Host "  ✓ Configuration file exists" -ForegroundColor Green
}

# Create directories
Write-Host "[5/5] Creating directories..." -ForegroundColor Yellow
$dirs = @("data", "uploads", "uploads/originals", "uploads/processed", "logs", "reports")
foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}
Write-Host "  ✓ Directories ready" -ForegroundColor Green

Write-Host ""
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 58) -ForegroundColor Cyan
Write-Host "  Starting GeoLedger..." -ForegroundColor Cyan
Write-Host "=" -NoNewline -ForegroundColor Cyan
Write-Host ("=" * 58) -ForegroundColor Cyan
Write-Host ""
Write-Host "  API Server:  " -NoNewline -ForegroundColor White
Write-Host "http://localhost:8000" -ForegroundColor Green
Write-Host "  Frontend:    " -NoNewline -ForegroundColor White
Write-Host "http://localhost:8000/index.html" -ForegroundColor Green
Write-Host "  API Docs:    " -NoNewline -ForegroundColor White
Write-Host "http://localhost:8000/docs" -ForegroundColor Green
Write-Host ""
Write-Host "  Default Login:" -ForegroundColor Yellow
Write-Host "    Admin:     admin / admin123" -ForegroundColor Gray
Write-Host "    Verifier:  verifier / verifier123" -ForegroundColor Gray
Write-Host "    Viewer:    viewer / viewer123" -ForegroundColor Gray
Write-Host ""
Write-Host "  Press Ctrl+C to stop the server" -ForegroundColor Gray
Write-Host ""

# Start the optional per-user PostgreSQL runtime created by local setup.
# Hosted PostgreSQL installations and default SQLite setups are unaffected.
$pgCtl = Join-Path $PSScriptRoot ".runtime\postgresql\pgsql\bin\pg_ctl.exe"
$pgData = Join-Path $PSScriptRoot ".runtime\postgresql\data"
$pgLog = Join-Path $PSScriptRoot "logs\postgresql.log"
if ((Test-Path $pgCtl) -and (Test-Path $pgData)) {
    Write-Host "  Checking local PostgreSQL..." -ForegroundColor Yellow
    & $pgCtl -D $pgData status *> $null
    if ($LASTEXITCODE -ne 0) {
        & $pgCtl -D $pgData -l $pgLog -o "-h 127.0.0.1 -p 5432" -w start
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ✗ PostgreSQL did not start. See logs\postgresql.log" -ForegroundColor Red
            exit 1
        }
    }
}

# Start the server
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
