#!/bin/bash
# GeoLedger Startup Script for Linux/Mac

echo "============================================================"
echo "  GeoLedger - Intelligent Land Record System"
echo "============================================================"
echo ""

# Check Python
echo "[1/5] Checking Python..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    echo "  ✓ Found: $PYTHON_VERSION"
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_VERSION=$(python --version)
    echo "  ✓ Found: $PYTHON_VERSION"
    PYTHON_CMD="python"
else
    echo "  ✗ Python not found. Please install Python 3.10+"
    exit 1
fi

# Check virtual environment
echo "[2/5] Checking virtual environment..."
if [ -f "venv/bin/activate" ]; then
    echo "  ✓ Virtual environment exists"
    echo "  Activating..."
    source venv/bin/activate
else
    echo "  ⚠ Virtual environment not found. Creating..."
    $PYTHON_CMD -m venv venv
    source venv/bin/activate
    echo "  ✓ Virtual environment created and activated"
fi

# Install dependencies
echo "[3/5] Checking dependencies..."
if [ -f "requirements.txt" ]; then
    echo "  Installing/updating packages..."
    $PYTHON_CMD -m pip install --quiet --upgrade pip
    $PYTHON_CMD -m pip install --quiet -r requirements.txt
    echo "  ✓ Dependencies installed"
else
    echo "  ✗ requirements.txt not found"
    exit 1
fi

# Check .env
echo "[4/5] Checking configuration..."
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "  ⚠ .env not found. Copying from .env.example..."
        cp .env.example .env
        echo "  ✓ .env created (using defaults)"
    else
        echo "  ⚠ No .env file (using built-in defaults)"
    fi
else
    echo "  ✓ Configuration file exists"
fi

# Create directories
echo "[5/5] Creating directories..."
mkdir -p data uploads/originals uploads/processed logs reports
echo "  ✓ Directories ready"

echo ""
echo "============================================================"
echo "  Starting GeoLedger..."
echo "============================================================"
echo ""
echo "  API Server:  http://localhost:8000"
echo "  Frontend:    http://localhost:8000/index.html"
echo "  API Docs:    http://localhost:8000/docs"
echo ""
echo "  Default Login:"
echo "    Admin:     admin / admin123"
echo "    Verifier:  verifier / verifier123"
echo "    Viewer:    viewer / viewer123"
echo ""
echo "  Press Ctrl+C to stop the server"
echo ""

# Start the server
$PYTHON_CMD -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
