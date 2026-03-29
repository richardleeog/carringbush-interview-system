#!/bin/bash
# =============================================================================
# Multilingual Interview System — Setup Script for macOS
# =============================================================================
# Run this script once to set everything up on a MacBook.
# After setup, use start.sh to launch the system.
# =============================================================================

set -e

echo ""
echo "=========================================="
echo "  Multilingual Interview System Setup"
echo "=========================================="
echo ""

# Check Python version
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "ERROR: Python is not installed."
    echo "Please install Python 3.9 or later from https://www.python.org/downloads/"
    exit 1
fi

PY_VERSION=$($PYTHON_CMD --version 2>&1)
echo "Found: $PY_VERSION"

# Check if pip is available
if ! $PYTHON_CMD -m pip --version &> /dev/null; then
    echo "ERROR: pip is not available. Please install pip."
    exit 1
fi

# Create virtual environment
echo ""
echo "Creating virtual environment..."
$PYTHON_CMD -m venv venv
source venv/bin/activate

echo "Virtual environment activated."

# Upgrade pip
pip install --upgrade pip --quiet

# Install core dependencies (without Whisper first — it's large)
echo ""
echo "Installing core dependencies..."
pip install flask flask-sqlalchemy python-docx gunicorn libretranslatepy --quiet

echo "Core dependencies installed."

# Ask about Whisper
echo ""
echo "=========================================="
echo "  Speech Recognition Setup"
echo "=========================================="
echo ""
echo "OpenAI Whisper provides speech-to-text transcription."
echo "It requires about 1-3 GB of disk space for the model."
echo ""
read -p "Install Whisper now? (y/n): " INSTALL_WHISPER

if [[ "$INSTALL_WHISPER" =~ ^[Yy]$ ]]; then
    echo "Installing Whisper (this may take a few minutes)..."
    pip install openai-whisper --quiet
    echo "Whisper installed successfully."
else
    echo "Skipping Whisper. You can install it later with:"
    echo "  source venv/bin/activate && pip install openai-whisper"
fi

# Ask about Claude API
echo ""
echo "=========================================="
echo "  AI Document Generation Setup"
echo "=========================================="
echo ""
echo "The system can use Claude AI to polish documents."
echo "This requires an API key from Anthropic (free tier available)."
echo ""
read -p "Do you have an Anthropic API key? (y/n): " HAS_API_KEY

if [[ "$HAS_API_KEY" =~ ^[Yy]$ ]]; then
    read -p "Enter your API key: " API_KEY
    pip install anthropic --quiet
    echo "export ANTHROPIC_API_KEY='$API_KEY'" >> venv/bin/activate
    echo "API key saved. Claude will be used for document generation."
else
    echo "No API key — the system will use template-based document"
    echo "generation (still produces professional documents)."
    echo "You can add an API key later by running:"
    echo "  export ANTHROPIC_API_KEY='your-key-here'"
fi

# Create the database
echo ""
echo "Setting up database..."
$PYTHON_CMD -c "
from app import app, db, init_services
with app.app_context():
    db.create_all()
    init_services()
print('Database created.')
"

# Create student files directory
mkdir -p student_files

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "To start the system, run:"
echo ""
echo "  ./start.sh"
echo ""
echo "Then open your web browser and go to:"
echo ""
echo "  http://localhost:5000"
echo ""
echo "=========================================="
