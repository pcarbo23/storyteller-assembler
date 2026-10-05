#!/usr/bin/env bash
# ==============================================================================
# storyteller-assembler Environment Setup & Dependency Verification
# ==============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "========================================================================"
echo "  📚 Storyteller Assembler Environment Setup (v2.0.0)"
echo "========================================================================"

# 1. Check Python version
echo -n "[1/5] Checking Python interpreter... "
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    echo "Found Python $PY_VER ($(which python3))"
else
    echo "ERROR: python3 not found on PATH."
    exit 1
fi

# 2. Virtual Environment Setup
echo -n "[2/5] Verifying virtual environment (.venv)... "
if [ ! -d ".venv" ]; then
    echo "Creating .venv..."
    python3 -m venv .venv
else
    echo "Existing .venv detected."
fi

echo "Activating .venv and verifying dependencies..."
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "  ✓ Python dependencies up to date."

# 3. System Tools Check
echo "[3/5] Verifying system CLI dependencies:"
for tool in ffmpeg espeak-ng java; do
    if command -v "$tool" &>/dev/null; then
        echo "  ✓ $tool: found at $(which $tool)"
    else
        echo "  ⚠ $tool: NOT found on PATH. Please install via Homebrew or apt."
    fi
done

if command -v docker &>/dev/null; then
    if docker info &>/dev/null; then
        echo "  ✓ docker: running and responsive"
    else
        echo "  ⚠ docker: CLI installed, but daemon is not running"
    fi
else
    echo "  ⚠ docker: NOT found on PATH (required for Docker-based forced alignment fallback)"
fi

# 4. NLS Validator Configuration (NLS_VALIDATOR_JAR)
echo "[4/5] Checking NLS Compliance Validator (NLS_VALIDATOR_JAR):"
VALIDATOR_PATH="$NLS_VALIDATOR_JAR"

if [ -n "$VALIDATOR_PATH" ] && [ -f "$VALIDATOR_PATH" ]; then
    echo "  ✓ NLS_VALIDATOR_JAR is configured: $VALIDATOR_PATH"
    if command -v java &>/dev/null; then
        VAL_VER=$(java -cp "$VALIDATOR_PATH" ZedVal -v 2>&1 | tr '\n' ' ' | sed 's/^[ \t]*//')
        echo "    $VAL_VER"
    fi
elif [ -f "$HOME/validators/AllVal.jar" ]; then
    echo "  Found AllVal.jar in standard location: $HOME/validators/AllVal.jar"
    export NLS_VALIDATOR_JAR="$HOME/validators/AllVal.jar"
    
    # Prompt to persist to ~/.zshrc if not already present
    ZSHRC="$HOME/.zshrc"
    if [ -f "$ZSHRC" ] && ! grep -q "NLS_VALIDATOR_JAR" "$ZSHRC"; then
        echo "  Appending export NLS_VALIDATOR_JAR to $ZSHRC..."
        echo "" >> "$ZSHRC"
        echo "# NLS Compliance Validator Suite" >> "$ZSHRC"
        echo "export NLS_VALIDATOR_JAR=\"$HOME/validators/AllVal.jar\"" >> "$ZSHRC"
    fi
    echo "  ✓ Configured NLS_VALIDATOR_JAR=$HOME/validators/AllVal.jar"
else
    echo "  ⚠ NLS_VALIDATOR_JAR is not set and ~/validators/AllVal.jar was not found."
    echo "    (Compliance verification will be skipped in production until NLS_VALIDATOR_JAR is configured)."
    if [ -t 0 ]; then
        read -r -p "    Enter path to AllVal.jar (or press Enter to skip): " USER_INPUT_JAR
        if [ -n "$USER_INPUT_JAR" ] && [ -f "$USER_INPUT_JAR" ]; then
            ABS_JAR=$(cd "$(dirname "$USER_INPUT_JAR")" && pwd)/$(basename "$USER_INPUT_JAR")
            export NLS_VALIDATOR_JAR="$ABS_JAR"
            ZSHRC="$HOME/.zshrc"
            if [ -f "$ZSHRC" ] && ! grep -q "NLS_VALIDATOR_JAR" "$ZSHRC"; then
                echo "export NLS_VALIDATOR_JAR=\"$ABS_JAR\"" >> "$ZSHRC"
            fi
            echo "  ✓ Configured NLS_VALIDATOR_JAR=$ABS_JAR in $ZSHRC"
        fi
    fi
fi

# 5. Summary & Completion
echo "[5/5] Checking project folder placeholders..."
mkdir -p data/ingest data/processing data/output data/reports data/debug

echo ""
echo "========================================================================"
echo "  ✓ Environment setup complete!"
echo "  To run the dashboard: source .venv/bin/activate && streamlit run scripts/dashboard.py"
echo "  To run the watcher:   source .venv/bin/activate && python scripts/run_ingest_watcher.py"
echo "========================================================================"
