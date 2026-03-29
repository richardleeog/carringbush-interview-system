#!/bin/bash
# =============================================================================
# Multilingual Interview System — One-Click Setup for macOS
# =============================================================================
# Just run:   bash setup.sh
# Everything is installed automatically. No questions asked.
# After setup, run:   bash start.sh
# =============================================================================

set -e

echo ""
echo "=========================================="
echo "  Multilingual Interview System"
echo "  Setting up — please wait..."
echo "=========================================="
echo ""

# ------------------------------------------------------------------
# Step 1: Check for Python
# ------------------------------------------------------------------
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo ""
    echo "  Python is not installed on your Mac."
    echo ""
    echo "  To install it:"
    echo "    1. Open Safari and go to: https://www.python.org/downloads/"
    echo "    2. Click the big yellow Download button"
    echo "    3. Open the downloaded file and follow the steps"
    echo "    4. Once installed, run this script again"
    echo ""
    exit 1
fi

PY_VERSION=$($PYTHON_CMD --version 2>&1)
echo "  Found $PY_VERSION — good."

# ------------------------------------------------------------------
# Step 2: Check for Homebrew (needed for LibreTranslate)
# ------------------------------------------------------------------
if ! command -v brew &> /dev/null; then
    echo ""
    echo "  Installing Homebrew (a tool that helps install software)..."
    echo "  You may be asked for your Mac password — this is normal."
    echo ""
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Add Homebrew to PATH for Apple Silicon Macs
    if [ -f "/opt/homebrew/bin/brew" ]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    fi
fi

echo "  Homebrew ready."

# ------------------------------------------------------------------
# Step 3: Install ffmpeg (needed by Whisper for audio processing)
# ------------------------------------------------------------------
if ! command -v ffmpeg &> /dev/null; then
    echo "  Installing ffmpeg (for audio processing)..."
    brew install ffmpeg --quiet
fi
echo "  ffmpeg ready."

# ------------------------------------------------------------------
# Step 4: Create virtual environment
# ------------------------------------------------------------------
echo "  Creating a safe space for the system's software..."
if [ -d "venv" ]; then
    rm -rf venv
fi
$PYTHON_CMD -m venv venv
source venv/bin/activate

pip install --upgrade pip --quiet 2>/dev/null

# ------------------------------------------------------------------
# Step 5: Install everything
# ------------------------------------------------------------------
echo "  Installing the interview system (this takes a few minutes)..."
pip install flask flask-sqlalchemy python-docx gunicorn --quiet 2>/dev/null
echo "  Core system installed."

echo "  Installing speech recognition (Whisper — this is the big one)..."
pip install setuptools --quiet 2>/dev/null
pip install openai-whisper --quiet 2>/dev/null
echo "  Speech recognition installed."

echo "  Installing translation service..."
pip install libretranslatepy --quiet 2>/dev/null
echo "  Translation service installed."

# ------------------------------------------------------------------
# Step 6: Install LibreTranslate (the actual translation server)
# ------------------------------------------------------------------
echo "  Installing LibreTranslate (free translation engine)..."
pip install libretranslate --quiet 2>/dev/null
echo "  LibreTranslate installed."

# ------------------------------------------------------------------
# Step 7: Set up the database
# ------------------------------------------------------------------
echo "  Setting up database..."
$PYTHON_CMD -c "
from app import app, db
with app.app_context():
    db.create_all()
print('  Database ready.')
"

# Create student files directory
mkdir -p student_files

# ------------------------------------------------------------------
# Done!
# ------------------------------------------------------------------
echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "  Everything is installed and ready to go."
echo ""
echo "  To start the system, run:"
echo ""
echo "      bash start.sh"
echo ""
echo "  Then open your browser and go to:"
echo ""
echo "      http://localhost:5000"
echo ""
echo "=========================================="
echo ""
