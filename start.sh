#!/bin/bash
# =============================================================================
# Multilingual Interview System — Start Script
# =============================================================================
# Just run:   bash start.sh
# Opens automatically in your browser.
# Press Ctrl+C to stop everything.
# =============================================================================

cd "$(dirname "$0")"

# Check setup has been done
if [ ! -d "venv" ]; then
    echo ""
    echo "  The system hasn't been set up yet."
    echo "  Please run this first:   bash setup.sh"
    echo ""
    exit 1
fi

source venv/bin/activate

echo ""
echo "=========================================="
echo "  Multilingual Interview System"
echo "=========================================="
echo ""

# ------------------------------------------------------------------
# Start LibreTranslate in the background (for real-time translation)
# ------------------------------------------------------------------
echo "  Starting translation service..."

# Kill any existing LibreTranslate process
pkill -f "libretranslate" 2>/dev/null || true

# Start LibreTranslate on port 5555 in the background
if command -v libretranslate &> /dev/null || python -c "import libretranslate" 2>/dev/null; then
    libretranslate --port 5555 --host 127.0.0.1 --load-only en,vi,th,ar,hi,ur,fa,am,lo,he,tl,zh,ko,ja,fr,es,pt,ru,de,it,tr,pl,nl,sv,id,ms,my &>/dev/null &
    TRANSLATE_PID=$!
    echo "  Translation service starting (may take a moment on first run)..."
    echo "  (First time: it will download language packs — be patient!)"
else
    echo "  Translation service not found — demo mode will still work."
    echo "  To install: source venv/bin/activate && pip install libretranslate"
    TRANSLATE_PID=""
fi

# ------------------------------------------------------------------
# Start the interview system
# ------------------------------------------------------------------
echo ""
echo "  Starting interview system..."
echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║                                      ║"
echo "  ║   Open your browser and go to:       ║"
echo "  ║                                      ║"
echo "  ║   http://localhost:5000              ║"
echo "  ║                                      ║"
echo "  ║   Press Ctrl+C to stop               ║"
echo "  ║                                      ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Try to open browser automatically
if command -v open &> /dev/null; then
    sleep 2
    open "http://localhost:5000" &
fi

# Run the app — when user presses Ctrl+C, clean up
cleanup() {
    echo ""
    echo "  Shutting down..."
    if [ -n "$TRANSLATE_PID" ]; then
        kill $TRANSLATE_PID 2>/dev/null
    fi
    pkill -f "libretranslate" 2>/dev/null || true
    echo "  Goodbye!"
    exit 0
}

trap cleanup INT TERM

python app.py
