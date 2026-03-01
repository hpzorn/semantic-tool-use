#!/usr/bin/env bash
# Start the Ontology Server in HTTP mode.
#
# This is a development launcher. For production, use:
#   ./service/install.sh    (installs as system service)
#
# Usage:
#   ./start-ontology-server.sh              # Foreground
#   ./start-ontology-server.sh --stop       # Stop background server
#   ./start-ontology-server.sh --background # Run in background

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
DATA_DIR="$HOME/.semantic-tool-use"
PID_FILE="$DATA_DIR/ontology-server.pid"
LOG_FILE="$DATA_DIR/ontology-server.log"

# Configuration (override via environment)
HOST="${ONTOLOGY_HOST:-localhost}"
PORT="${ONTOLOGY_PORT:-8100}"
PERSIST_PATH="${ONTOLOGY_PERSIST:-$DATA_DIR/kg}"
IDEAS_DIR="${IDEAS_DIR:-$HOME/ideas}"
ONTOLOGY_PATH="${ONTOLOGY_PATH:-$SCRIPT_DIR/ontology/domain/visual-artifacts}"
SHAPES_PATH="${SHAPES_PATH:-$SCRIPT_DIR/src/ontology_server/shapes}"

stop_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Stopping ontology server (PID $PID)..."
            kill "$PID"
            rm -f "$PID_FILE"
            echo "Stopped."
        else
            echo "Server not running (stale PID file)."
            rm -f "$PID_FILE"
        fi
    else
        echo "No PID file found."
    fi
}

if [ "${1:-}" = "--stop" ]; then
    stop_server
    exit 0
fi

# Check if already running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Server already running (PID $PID)"
        echo "  URL: http://$HOST:$PORT"
        echo "  Stop: $0 --stop"
        exit 0
    else
        rm -f "$PID_FILE"
    fi
fi

# Ensure data directory exists
mkdir -p "$DATA_DIR"

# Activate virtual environment
source "$VENV/bin/activate"
export PYTHONPATH="$SCRIPT_DIR/src"

SERVER_ARGS=(
    --http
    --host "$HOST"
    --port "$PORT"
    --enable-abox
    --kg-persist "$PERSIST_PATH"
    --ontology-path "$ONTOLOGY_PATH"
    --shapes-path "$SHAPES_PATH"
    --log-level INFO
)

# Add ideas dir if it exists
if [ -d "$IDEAS_DIR" ]; then
    SERVER_ARGS+=(--ideas-dir "$IDEAS_DIR")
fi

if [ "${1:-}" = "--background" ]; then
    nohup python -m ontology_server "${SERVER_ARGS[@]}" >> "$LOG_FILE" 2>&1 &
    echo "$!" > "$PID_FILE"
    echo "Server started in background (PID $!)"
    echo "  URL:  http://$HOST:$PORT"
    echo "  Logs: tail -f $LOG_FILE"
    echo "  Stop: $0 --stop"
else
    echo "Starting Ontology Server..."
    echo "  HTTP: http://$HOST:$PORT"
    echo "  SSE:  http://$HOST:$PORT/sse"
    echo ""
    python -m ontology_server "${SERVER_ARGS[@]}" 2>&1 | tee "$LOG_FILE"
fi
