#!/bin/bash
# =============================================================================
# Multilingual Interview System — Start Script
# =============================================================================
# Launches the system. Open http://localhost:5000 in your browser.
# Press Ctrl+C to stop.
# =============================================================================

cd "$(dirname "$0")"

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Virtual environment not found. Please run setup.sh first."
    exit 1
fi

echo ""
echo "=========================================="
echo "  Multilingual Interview System"
echo "=========================================="
echo ""
echo "  Starting... Open your browser at:"
echo ""
echo "  http://localhost:5000"
echo ""
echo "  Press Ctrl+C to stop the system."
echo "=========================================="
echo ""

python app.py
