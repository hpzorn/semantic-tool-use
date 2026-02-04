#!/bin/bash
# Start the Ontology Server in HTTP mode with A-Box enabled
#
# This runs a shared server that multiple Claude sessions can connect to.
# Data is persisted to ~/.semantic-tool-use/kg
#
# Usage:
#   ./start-ontology-server.sh           # Foreground
#   ./start-ontology-server.sh &         # Background
#   ./start-ontology-server.sh --stop    # Stop running server
#   ./start-ontology-server.sh --restart # Restart (launchd or manual)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PID_FILE="$HOME/.semantic-tool-use/ontology-server.pid"
LOG_FILE="$HOME/.semantic-tool-use/ontology-server.log"

# Configuration
HOST="${ONTOLOGY_HOST:-localhost}"
PORT="${ONTOLOGY_PORT:-8100}"
PERSIST_PATH="$HOME/.semantic-tool-use/kg"
IDEAS_DIR="${IDEAS_DIR:-$HOME/ideas}"
ONTOLOGY_PATH="$SCRIPT_DIR/ontology/domain/visual-artifacts"
SHAPES_PATH="$SCRIPT_DIR/src/ontology_server/shapes"
LAUNCHD_LABEL="org.semantic-tool-use.ontology-server"

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
        echo "No PID file found. Server may not be running."
    fi
}

if [ "$1" = "--stop" ]; then
    stop_server
    exit 0
fi

if [ "$1" = "--restart" ]; then
    echo "Restarting ontology server..."
    # Prefer launchd if the service is loaded
    if launchctl list "$LAUNCHD_LABEL" >/dev/null 2>&1; then
        echo "  Using launchd service: $LAUNCHD_LABEL"
        launchctl stop "$LAUNCHD_LABEL"
        sleep 2
        launchctl start "$LAUNCHD_LABEL"
        # Wait for server to become available (use /facts endpoint, not /sse which streams)
        echo -n "  Waiting for server"
        for i in $(seq 1 15); do
            if curl -sf "http://$HOST:$PORT/facts?limit=1" --max-time 2 -o /dev/null 2>/dev/null; then
                echo " ready."
                echo "  URL: http://$HOST:$PORT/sse"
                exit 0
            fi
            echo -n "."
            sleep 1
        done
        echo " timeout."
        echo "  WARNING: Server did not respond within 15s. Check logs:" >&2
        echo "    $LOG_FILE" >&2
        exit 1
    else
        # Fallback: manual stop + background start
        echo "  launchd service not loaded; using manual restart"
        stop_server
        sleep 1
        # Start in background
        source "$VENV/bin/activate"
        export PYTHONPATH="$SCRIPT_DIR/src"
        nohup python -m ontology_server \
            --http \
            --host "$HOST" \
            --port "$PORT" \
            --enable-abox \
            --ideas-dir "$IDEAS_DIR" \
            --ontology-path "$ONTOLOGY_PATH" \
            --shapes-path "$SHAPES_PATH" \
            --log-level INFO \
            >> "$LOG_FILE" 2>&1 &
        NEW_PID=$!
        echo "$NEW_PID" > "$PID_FILE"
        echo -n "  Waiting for server (PID $NEW_PID)"
        for i in $(seq 1 15); do
            if curl -sf "http://$HOST:$PORT/facts?limit=1" --max-time 2 -o /dev/null 2>/dev/null; then
                echo " ready."
                echo "  URL: http://$HOST:$PORT/sse"
                exit 0
            fi
            echo -n "."
            sleep 1
        done
        echo " timeout."
        echo "  WARNING: Server did not respond within 15s. Check logs:" >&2
        echo "    $LOG_FILE" >&2
        exit 1
    fi
fi

# Check if already running
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Server already running (PID $PID)"
        echo "  URL: http://$HOST:$PORT/sse"
        echo "  Stop with: $0 --stop"
        exit 0
    else
        rm -f "$PID_FILE"
    fi
fi

# Activate virtual environment
source "$VENV/bin/activate"
export PYTHONPATH="$SCRIPT_DIR/src"

echo "Starting Ontology Server..."
echo "  HTTP endpoint: http://$HOST:$PORT"
echo "  SSE endpoint:  http://$HOST:$PORT/sse"
echo "  Ideas dir:     $IDEAS_DIR (reloaded on startup)"
echo "  Persistence:   in-memory (ideas from files)"
echo "  Ontologies:    $ONTOLOGY_PATH"
echo "  Log file:      $LOG_FILE"
echo ""

# Run the server
# Note: --kg-persist disabled due to Oxigraph RocksDB panic on macOS
# Ideas are re-loaded from --ideas-dir on each startup
python -m ontology_server \
    --http \
    --host "$HOST" \
    --port "$PORT" \
    --enable-abox \
    --ideas-dir "$IDEAS_DIR" \
    --ontology-path "$ONTOLOGY_PATH" \
    --shapes-path "$SHAPES_PATH" \
    --log-level INFO \
    2>&1 | tee "$LOG_FILE"
