#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
#  setup.sh — One-command setup for next-ai-draw-io
#
#  Supports three modes:
#    ./setup.sh docker      → Docker Compose (production-like)
#    ./setup.sh dev         → Local dev servers with hot reload
#    ./setup.sh docker-dev  → Docker Compose with hot reload
# ─────────────────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-6002}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*"; }

# ── .env bootstrap ──────────────────────────────────────────
ensure_env_file() {
    if [ ! -f "$REPO_ROOT/.env" ]; then
        if [ -f "$REPO_ROOT/env.example" ]; then
            cp "$REPO_ROOT/env.example" "$REPO_ROOT/.env"
            warn ".env not found — created from env.example"
            warn "Edit .env to add your API keys before starting"
        else
            touch "$REPO_ROOT/.env"
            warn ".env not found — created empty file"
        fi
    else
        ok ".env exists"
    fi
}

# ── Check required tools ────────────────────────────────────
check_command() {
    if ! command -v "$1" &>/dev/null; then
        err "$1 is required but not installed"
        return 1
    fi
    ok "$1 found: $(command -v "$1")"
}

# ── Mode: Docker Compose (production) ───────────────────────
run_docker() {
    info "Starting with Docker Compose (production mode)..."
    ensure_env_file
    check_command docker

    info "Building and starting all services..."
    cd "$REPO_ROOT"
    docker compose up --build -d

    echo ""
    echo -e "╔══════════════════════════════════════════════════════╗"
    echo -e "║  ${GREEN}All services are starting...${NC}                        ║"
    echo -e "╠══════════════════════════════════════════════════════╣"
    echo -e "║                                                      ║"
    echo -e "║  Frontend:    ${CYAN}http://localhost:3000${NC}                  ║"
    echo -e "║  Backend API: ${CYAN}http://localhost:8000${NC}                  ║"
    echo -e "║  API Docs:    ${CYAN}http://localhost:8000/docs${NC}             ║"
    echo -e "║  Draw.io:     ${CYAN}http://localhost:8080${NC}                  ║"
    echo -e "║                                                      ║"
    echo -e "║  Architecture:                                       ║"
    echo -e "║  Browser → Next.js(:3000) → proxy → Python(:8000)   ║"
    echo -e "║                                                      ║"
    echo -e "║  Logs:    docker compose logs -f                     ║"
    echo -e "║  Stop:    docker compose down                        ║"
    echo -e "╚══════════════════════════════════════════════════════╝"
    echo ""

    info "Waiting for services to be healthy..."
    docker compose ps
}

# ── Mode: Docker Compose (dev with hot reload) ──────────────
run_docker_dev() {
    info "Starting with Docker Compose (dev mode + hot reload)..."
    ensure_env_file
    check_command docker

    cd "$REPO_ROOT"
    docker compose -f docker-compose.dev.yml up --build -d

    echo ""
    echo -e "╔══════════════════════════════════════════════════════╗"
    echo -e "║  ${GREEN}Dev services starting (hot reload enabled)...${NC}      ║"
    echo -e "╠══════════════════════════════════════════════════════╣"
    echo -e "║  Frontend:    ${CYAN}http://localhost:3000${NC}                  ║"
    echo -e "║  Backend API: ${CYAN}http://localhost:8000${NC}                  ║"
    echo -e "║  API Docs:    ${CYAN}http://localhost:8000/docs${NC}             ║"
    echo -e "║                                                      ║"
    echo -e "║  Logs:  docker compose -f docker-compose.dev.yml logs -f  ║"
    echo -e "║  Stop:  docker compose -f docker-compose.dev.yml down     ║"
    echo -e "╚══════════════════════════════════════════════════════╝"
}

# ── Mode: Local dev (no Docker) ─────────────────────────────
run_dev() {
    info "Starting local dev servers..."
    ensure_env_file

    # ── Check prerequisites ──
    local missing=0
    check_command python3 || missing=1
    check_command node    || missing=1
    check_command npm     || missing=1

    if [ "$missing" -eq 1 ]; then
        err "Missing required tools. Install python3, node, and npm first."
        exit 1
    fi

    # ── Check ports ──
    if command -v lsof &>/dev/null; then
        for port in $BACKEND_PORT $FRONTEND_PORT; do
            if lsof -i :"$port" -sTCP:LISTEN &>/dev/null; then
                err "Port $port is already in use"
                exit 1
            fi
        done
    elif command -v ss &>/dev/null; then
        for port in $BACKEND_PORT $FRONTEND_PORT; do
            if ss -tlnp 2>/dev/null | grep -q ":$port "; then
                err "Port $port is already in use"
                exit 1
            fi
        done
    else
        warn "Neither lsof nor ss found — skipping port availability check"
    fi

    # ── Install Python backend dependencies ──
    info "Installing Python backend dependencies..."
    cd "$BACKEND_DIR"
    if [ -f "pyproject.toml" ]; then
        python3 -m pip install -e "." --quiet 2>/dev/null || {
            warn "pip install failed — trying with --break-system-packages"
            python3 -m pip install -e "." --quiet --break-system-packages 2>/dev/null || {
                err "Failed to install Python dependencies"
                exit 1
            }
        }
        ok "Python dependencies installed"
    else
        err "backend/pyproject.toml not found"
        exit 1
    fi

    # ── Install Node.js dependencies ──
    info "Installing Node.js dependencies..."
    cd "$REPO_ROOT"
    if [ ! -d "node_modules" ]; then
        npm install --silent 2>/dev/null || npm install
    fi
    ok "Node.js dependencies ready"

    # ── Copy shape library docs to backend ──
    if [ -d "$REPO_ROOT/docs/shape-libraries" ]; then
        mkdir -p "$BACKEND_DIR/docs"
        cp -r "$REPO_ROOT/docs/shape-libraries" "$BACKEND_DIR/docs/shape-libraries" 2>/dev/null || true
    fi

    # ── Start backend ──
    info "Starting Python backend on port $BACKEND_PORT..."
    cd "$BACKEND_DIR"
    python3 -m uvicorn app.main:app \
        --host 0.0.0.0 \
        --port "$BACKEND_PORT" \
        --reload \
        --reload-dir app &
    BACKEND_PID=$!

    # Wait for backend to be ready
    info "Waiting for backend to start..."
    local retries=0
    while [ $retries -lt 30 ]; do
        # Fail fast if the process died
        if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
            err "Backend process exited unexpectedly"
            exit 1
        fi
        if curl -sf "http://localhost:$BACKEND_PORT/health" &>/dev/null; then
            ok "Backend is healthy"
            break
        fi
        retries=$((retries + 1))
        sleep 1
    done
    if [ $retries -ge 30 ]; then
        err "Backend failed to start within 30s"
        kill "$BACKEND_PID" 2>/dev/null
        exit 1
    fi

    # ── Start frontend ──
    info "Starting Next.js frontend on port $FRONTEND_PORT..."
    cd "$REPO_ROOT"
    PYTHON_API_URL="http://localhost:$BACKEND_PORT" \
    PORT="$FRONTEND_PORT" \
        npm run dev &
    FRONTEND_PID=$!

    echo ""
    echo -e "╔══════════════════════════════════════════════════════════╗"
    echo -e "║  ${GREEN}Both servers are running!${NC}                               ║"
    echo -e "╠══════════════════════════════════════════════════════════╣"
    echo -e "║                                                          ║"
    echo -e "║  Frontend:    ${CYAN}http://localhost:$FRONTEND_PORT${NC}                      ║"
    echo -e "║  Backend API: ${CYAN}http://localhost:$BACKEND_PORT${NC}                      ║"
    echo -e "║  API Docs:    ${CYAN}http://localhost:$BACKEND_PORT/docs${NC}                  ║"
    echo -e "║                                                          ║"
    echo -e "║  Architecture:                                           ║"
    echo -e "║  Browser → Next.js(:$FRONTEND_PORT) ─proxy─→ Python(:$BACKEND_PORT)     ║"
    echo -e "║                                                          ║"
    echo -e "║  Press ${YELLOW}Ctrl+C${NC} to stop both servers                        ║"
    echo -e "╚══════════════════════════════════════════════════════════╝"
    echo ""

    # ── Cleanup on exit ──
    cleanup() {
        echo ""
        info "Shutting down..."
        kill "$BACKEND_PID" 2>/dev/null
        kill "$FRONTEND_PID" 2>/dev/null
        wait "$BACKEND_PID" 2>/dev/null
        wait "$FRONTEND_PID" 2>/dev/null
        ok "All servers stopped"
    }
    trap cleanup INT TERM EXIT

    # Wait for either process to exit
    wait -n "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    cleanup
}

# ── Verify connection ───────────────────────────────────────
run_verify() {
    info "Verifying backend-frontend connection..."

    local backend_url="${1:-http://localhost:$BACKEND_PORT}"
    local frontend_url="${2:-http://localhost:$FRONTEND_PORT}"

    echo ""
    echo "Checking backend ($backend_url)..."

    # Health
    if curl -sf "$backend_url/health" &>/dev/null; then
        ok "Backend /health"
    else
        err "Backend /health — is the backend running?"
        return 1
    fi

    # Config endpoint
    local config_resp
    config_resp=$(curl -sf "$backend_url/api/config" 2>/dev/null) || true
    if echo "$config_resp" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'maxFileSize' in d" 2>/dev/null; then
        ok "Backend /api/config returns expected fields"
    else
        err "Backend /api/config — unexpected response: $config_resp"
    fi

    # Chat endpoint (SSE format check)
    local chat_resp
    chat_resp=$(curl -sf -X POST "$backend_url/api/chat" \
        -H "Content-Type: application/json" \
        -d '{"messages":[{"role":"user","parts":[{"type":"text","text":"hello"}]}],"xml":""}' \
        --max-time 5 2>/dev/null | head -1) || true
    if echo "$chat_resp" | grep -q '"type"'; then
        ok "Backend /api/chat returns SSE events"
    else
        warn "Backend /api/chat — could not verify SSE (may need API key)"
    fi

    echo ""
    echo "Checking frontend ($frontend_url)..."

    if curl -sf "$frontend_url" &>/dev/null; then
        ok "Frontend is reachable"
    else
        err "Frontend is not reachable — is it running?"
        return 1
    fi

    # Check proxy works (frontend /api/config should proxy to backend)
    local proxy_resp
    proxy_resp=$(curl -sf "$frontend_url/api/config" 2>/dev/null) || true
    if echo "$proxy_resp" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'maxFileSize' in d" 2>/dev/null; then
        ok "Frontend /api/config proxies to backend correctly"
    else
        warn "Frontend /api/config proxy — not working (check PYTHON_API_URL)"
    fi

    echo ""
    ok "Verification complete"
}

# ── Main ────────────────────────────────────────────────────
usage() {
    echo ""
    echo "Usage: $0 <mode>"
    echo ""
    echo "Modes:"
    echo "  docker       Build and start all services via Docker Compose"
    echo "  docker-dev   Docker Compose with hot reload (dev mode)"
    echo "  dev          Local dev servers (python + node, no Docker)"
    echo "  verify       Check that backend and frontend are connected"
    echo ""
    echo "Environment variables:"
    echo "  BACKEND_PORT   Python backend port (default: 8000)"
    echo "  FRONTEND_PORT  Next.js frontend port (default: 6002)"
    echo ""
    echo "Examples:"
    echo "  $0 dev                        # Start local dev"
    echo "  $0 docker                     # Start with Docker"
    echo "  $0 verify                     # Test connection"
    echo "  BACKEND_PORT=9000 $0 dev      # Custom port"
    echo ""
}

case "${1:-}" in
    docker)     run_docker ;;
    docker-dev) run_docker_dev ;;
    dev)        run_dev ;;
    verify)     run_verify "${2:-}" "${3:-}" ;;
    -h|--help)  usage ;;
    *)
        err "Unknown mode: ${1:-<none>}"
        usage
        exit 1
        ;;
esac
