#!/usr/bin/env bash
# Install ontology-server as a system service (macOS launchd or Linux systemd).
#
# Usage:
#   ./service/install.sh                    # Auto-detect OS, use defaults
#   ./service/install.sh --port 9000        # Custom port
#   ./service/install.sh --uninstall        # Remove the service
#   ./service/install.sh --dry-run          # Show what would be done
#
# All paths default to the current project directory. Override with env vars:
#   PROJECT_DIR, VENV_PATH, ONTOLOGY_PATH, SHAPES_PATH, DATA_DIR, PORT

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"

# Defaults
VENV_PATH="${VENV_PATH:-$PROJECT_DIR/.venv}"
ONTOLOGY_PATH="${ONTOLOGY_PATH:-$PROJECT_DIR/ontology/domain/visual-artifacts}"
SHAPES_PATH="${SHAPES_PATH:-$PROJECT_DIR/src/ontology_server/shapes}"
DATA_DIR="${DATA_DIR:-$HOME/.semantic-tool-use}"
PORT="${PORT:-8100}"
AUTH_ENABLED="${AUTH_ENABLED:-0}"
LABEL="org.semantic-tool-use.ontology-server"

DRY_RUN=false
UNINSTALL=false

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --auth) AUTH_ENABLED="1"; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --uninstall) UNINSTALL=true; shift ;;
        --ontology-path) ONTOLOGY_PATH="$2"; shift 2 ;;
        --data-dir) DATA_DIR="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--port PORT] [--auth] [--ontology-path PATH] [--data-dir DIR] [--dry-run] [--uninstall]"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

detect_os() {
    case "$(uname -s)" in
        Darwin) echo "macos" ;;
        Linux)  echo "linux" ;;
        *)      echo "unsupported" ;;
    esac
}

substitute() {
    local template="$1"
    sed -e "s|{{PROJECT_DIR}}|$PROJECT_DIR|g" \
        -e "s|{{VENV_PATH}}|$VENV_PATH|g" \
        -e "s|{{ONTOLOGY_PATH}}|$ONTOLOGY_PATH|g" \
        -e "s|{{SHAPES_PATH}}|$SHAPES_PATH|g" \
        -e "s|{{DATA_DIR}}|$DATA_DIR|g" \
        -e "s|{{PORT}}|$PORT|g" \
        -e "s|{{AUTH_ENABLED}}|$AUTH_ENABLED|g" \
        -e "s|{{USER}}|$(whoami)|g" \
        "$template"
}

install_launchd() {
    local template="$SCRIPT_DIR/launchd/$LABEL.plist"
    local target="$HOME/Library/LaunchAgents/$LABEL.plist"

    if $UNINSTALL; then
        echo "Uninstalling launchd service..."
        launchctl unload "$target" 2>/dev/null || true
        rm -f "$target"
        echo "Done. Service removed."
        return
    fi

    echo "Installing launchd service..."
    echo "  Project:  $PROJECT_DIR"
    echo "  Venv:     $VENV_PATH"
    echo "  Ontology: $ONTOLOGY_PATH"
    echo "  Data:     $DATA_DIR"
    echo "  Port:     $PORT"
    echo "  Auth:     $AUTH_ENABLED"

    mkdir -p "$DATA_DIR" "$HOME/Library/LaunchAgents"

    if $DRY_RUN; then
        echo ""
        echo "--- Would write to $target ---"
        substitute "$template"
        return
    fi

    # Stop existing service
    launchctl unload "$target" 2>/dev/null || true

    # Write and load
    substitute "$template" > "$target"
    launchctl load "$target"

    echo ""
    echo "Service installed and started."
    echo "  Status:  launchctl list | grep $LABEL"
    echo "  Logs:    tail -f $DATA_DIR/ontology-server.error.log"
    echo "  Stop:    launchctl unload $target"
    echo "  Remove:  $0 --uninstall"
}

install_systemd() {
    local template="$SCRIPT_DIR/systemd/ontology-server.service"
    local target="$HOME/.config/systemd/user/ontology-server.service"

    if $UNINSTALL; then
        echo "Uninstalling systemd service..."
        systemctl --user stop ontology-server 2>/dev/null || true
        systemctl --user disable ontology-server 2>/dev/null || true
        rm -f "$target"
        systemctl --user daemon-reload
        echo "Done. Service removed."
        return
    fi

    echo "Installing systemd user service..."
    echo "  Project:  $PROJECT_DIR"
    echo "  Venv:     $VENV_PATH"
    echo "  Ontology: $ONTOLOGY_PATH"
    echo "  Data:     $DATA_DIR"
    echo "  Port:     $PORT"
    echo "  Auth:     $AUTH_ENABLED"

    mkdir -p "$DATA_DIR" "$(dirname "$target")"

    if $DRY_RUN; then
        echo ""
        echo "--- Would write to $target ---"
        substitute "$template"
        return
    fi

    # Stop existing
    systemctl --user stop ontology-server 2>/dev/null || true

    # Write, reload, enable, start
    substitute "$template" > "$target"
    systemctl --user daemon-reload
    systemctl --user enable ontology-server
    systemctl --user start ontology-server

    echo ""
    echo "Service installed and started."
    echo "  Status:  systemctl --user status ontology-server"
    echo "  Logs:    journalctl --user -u ontology-server -f"
    echo "  Stop:    systemctl --user stop ontology-server"
    echo "  Remove:  $0 --uninstall"
}

OS=$(detect_os)
case "$OS" in
    macos) install_launchd ;;
    linux) install_systemd ;;
    *)
        echo "Unsupported OS: $(uname -s)"
        echo "Use Docker instead: docker compose up"
        exit 1 ;;
esac
