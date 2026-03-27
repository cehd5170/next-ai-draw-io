#!/bin/bash
# start_dev.sh — Start the Python backend and Next.js frontend together.
#
# Usage:
#   bash backend/scripts/start_dev.sh
#
# Both servers run in the background.  Press Ctrl+C to stop them both.
#
# Environment variables:
#   BACKEND_PORT   Python backend port (default: 8000)
#   FRONTEND_PORT  Next.js dev server port (default: 6002)

set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-6002}"

# Resolve the directory containing this script so the script can be invoked
# from any working directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${BACKEND_DIR}/.." && pwd)"

# ---------------------------------------------------------------------------
# Check for a conflicting process on the backend port before starting.
# ---------------------------------------------------------------------------
if command -v lsof &>/dev/null; then
    if lsof -ti tcp:"${BACKEND_PORT}" &>/dev/null; then
        echo "WARNING: Port ${BACKEND_PORT} is already in use."
        echo "         Stop the existing process or set BACKEND_PORT to a different value."
    fi
fi

# ---------------------------------------------------------------------------
# Start Python backend
# ---------------------------------------------------------------------------
echo "Starting Python backend on port ${BACKEND_PORT}..."
echo "  Directory: ${BACKEND_DIR}"

cd "${BACKEND_DIR}"

# Install the backend package in editable mode so imports resolve correctly.
# Suppress output on success to keep the terminal tidy.
if pip install -e . --quiet 2>/dev/null; then
    echo "  pip install -e . OK"
else
    echo "  WARNING: pip install -e . failed — attempting to start anyway."
fi

uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${BACKEND_PORT}" \
    --reload \
    --log-level info \
    &
BACKEND_PID=$!

# Give the backend a moment to bind to its port before starting the frontend.
sleep 1

# ---------------------------------------------------------------------------
# Start Next.js frontend
# ---------------------------------------------------------------------------
echo ""
echo "Starting Next.js frontend on port ${FRONTEND_PORT}..."
echo "  Directory: ${REPO_ROOT}"

cd "${REPO_ROOT}"

# NEXT_PUBLIC_PYTHON_API_URL makes the browser call the Python backend
# directly, which is more reliable for long-lived SSE chat streams.
# PORT tells the Next.js dev server which port to listen on.
NEXT_PUBLIC_PYTHON_API_URL="http://localhost:${BACKEND_PORT}" \
PORT="${FRONTEND_PORT}" \
    npm run dev \
    &
FRONTEND_PID=$!

# ---------------------------------------------------------------------------
# Print summary
# ---------------------------------------------------------------------------
echo ""
echo "-------------------------------------------------------"
echo "  Backend:   http://localhost:${BACKEND_PORT}  (PID: ${BACKEND_PID})"
echo "  Frontend:  http://localhost:${FRONTEND_PORT}  (PID: ${FRONTEND_PID})"
echo ""
echo "  API docs:  http://localhost:${BACKEND_PORT}/docs"
echo "  Health:    http://localhost:${BACKEND_PORT}/health"
echo "-------------------------------------------------------"
echo ""
echo "Press Ctrl+C to stop both servers."
echo ""

# ---------------------------------------------------------------------------
# Shutdown handler
# ---------------------------------------------------------------------------
_cleanup() {
    echo ""
    echo "Stopping servers..."
    kill "${BACKEND_PID}" 2>/dev/null || true
    kill "${FRONTEND_PID}" 2>/dev/null || true
    # Wait briefly so the ports are released before the script exits.
    wait "${BACKEND_PID}" 2>/dev/null || true
    wait "${FRONTEND_PID}" 2>/dev/null || true
    echo "Done."
    exit 0
}

trap _cleanup INT TERM

# Keep the script alive while both child processes are running.
wait
