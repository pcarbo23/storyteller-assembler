#!/usr/bin/env zsh

# Export system paths for GUI launcher environment
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

# Get the directory of this script
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "=== Starting AutoStoryPipe Ingestion Dashboard ==="
echo "Working directory: $DIR"

# Check if virtual environment exists
if [ -d ".venv" ]; then
    echo "Activating virtual environment (.venv)..."
    source .venv/bin/activate
else
    echo "Error: .venv virtual environment not found in $DIR"
    echo "Please create a virtual environment first: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    read -k 1 "?Press any key to exit..."
    exit 1
fi

# Launch Streamlit dashboard
echo "Launching Streamlit Dashboard in browser..."
streamlit run scripts/dashboard.py
