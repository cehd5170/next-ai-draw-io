#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────
#  setup.sh — Docker Compose launcher for next-ai-draw-io
#
#  Commands:
#    ./setup.sh              → Start all services (production)
#    ./setup.sh dev          → Start with hot reload (dev mode)
#    ./setup.sh down         → Stop all services
#    ./setup.sh logs         → Tail logs from all services
# ─────────────────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

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

# ── Main ────────────────────────────────────────────────────
usage() {
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  (none)    Build and start all services (production)"
    echo "  dev       Build and start with hot reload (dev mode)"
    echo "  down      Stop all services"
    echo "  logs      Tail logs from all services"
    echo ""
    echo "Examples:"
    echo "  $0              # Start production"
    echo "  $0 dev          # Start with hot reload"
    echo "  $0 down         # Stop everything"
    echo "  $0 logs         # Tail all logs"
    echo ""
}

case "${1:-}" in
    ""|docker)
        ensure_env_file
        info "Starting all services (production)..."
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
        echo -e "║  Logs:  ./setup.sh logs                              ║"
        echo -e "║  Stop:  ./setup.sh down                              ║"
        echo -e "╚══════════════════════════════════════════════════════╝"
        echo ""
        docker compose ps
        ;;

    dev|docker-dev)
        ensure_env_file
        info "Starting all services (dev mode + hot reload)..."
        docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d

        echo ""
        echo -e "╔══════════════════════════════════════════════════════╗"
        echo -e "║  ${GREEN}Dev services starting (hot reload enabled)...${NC}      ║"
        echo -e "╠══════════════════════════════════════════════════════╣"
        echo -e "║                                                      ║"
        echo -e "║  Frontend:    ${CYAN}http://localhost:3000${NC}                  ║"
        echo -e "║  Backend API: ${CYAN}http://localhost:8000${NC}                  ║"
        echo -e "║  API Docs:    ${CYAN}http://localhost:8000/docs${NC}             ║"
        echo -e "║  Draw.io:     ${CYAN}http://localhost:8080${NC}                  ║"
        echo -e "║                                                      ║"
        echo -e "║  Logs:  ./setup.sh logs                              ║"
        echo -e "║  Stop:  ./setup.sh down                              ║"
        echo -e "╚══════════════════════════════════════════════════════╝"
        echo ""
        docker compose -f docker-compose.yml -f docker-compose.dev.yml ps
        ;;

    down)
        info "Stopping all services..."
        docker compose -f docker-compose.yml -f docker-compose.dev.yml down 2>/dev/null || docker compose down
        ok "All services stopped"
        ;;

    logs)
        docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f 2>/dev/null || docker compose logs -f
        ;;

    -h|--help)
        usage
        ;;

    *)
        err "Unknown command: $1"
        usage
        exit 1
        ;;
esac
