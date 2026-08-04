#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# One-shot setup for the OCR extraction project (backend + frontend).
# Run from the repo root:
#     ./setup.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { printf "${GREEN}==>${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}!! ${NC} %s\n" "$*"; }
error() { printf "${RED}XX ${NC} %s\n" "$*"; }

# ── 1. Environment file ─────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  info "Created .env from .env.example — edit it and fill in your API keys."
else
  info ".env already exists — leaving it untouched."
fi

# ── 2. Backend Python dependencies ──────────────────────────────────────────
if command -v uv >/dev/null 2>&1; then
  info "Using uv (recommended) to install backend dependencies..."
  uv sync
  BACKEND_PY=".venv/bin/python"
else
  info "uv not found — falling back to python3 venv + pip."
  if [ ! -d .venv ]; then
    python3 -m venv .venv
  fi
  info "Installing backend dependencies with pip (this can take a while)..."
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
  BACKEND_PY=".venv/bin/python"
fi

if [ ! -x "$BACKEND_PY" ]; then
  error "Backend interpreter not found at $BACKEND_PY"
  exit 1
fi
info "Backend dependencies installed ($BACKEND_PY)."

# ── 3. System dependencies (Debian/Ubuntu) ──────────────────────────────────
# pytesseract needs the tesseract binary; OpenCV needs libGL; PyMuPDF may want poppler.
if [ -f /etc/os-release ] && grep -qiE 'debian|ubuntu' /etc/os-release; then
  MISSING=""
  command -v tesseract >/dev/null 2>&1 || MISSING="$MISSING tesseract-ocr"
  command -v pdftoppm >/dev/null 2>&1 || MISSING="$MISSING poppler-utils"
  python3 -c "import ctypes; ctypes.CDLL('libGL.so.1')" 2>/dev/null || MISSING="$MISSING libgl1"
  if [ -n "$MISSING" ]; then
    warn "Missing system packages:${MISSING}"
    if [ "$(id -u)" -eq 0 ]; then
      info "Installing system packages..."
      apt-get update -y
      apt-get install -y tesseract-ocr poppler-utils libgl1
    elif command -v sudo >/dev/null 2>&1; then
      info "Installing system packages via sudo..."
      sudo apt-get update -y
      sudo apt-get install -y tesseract-ocr poppler-utils libgl1
    else
      warn "Run manually:  sudo apt-get install -y tesseract-ocr poppler-utils libgl1"
    fi
  else
    info "System dependencies present."
  fi
fi

# ── 4. Frontend dependencies ────────────────────────────────────────────────
if [ -f frontend/package.json ]; then
  if ! command -v npm >/dev/null 2>&1; then
    error "npm not found — install Node.js (https://nodejs.org) then re-run ./setup.sh"
    exit 1
  fi
  info "Installing frontend dependencies..."
  (cd frontend && npm install)
  info "Frontend dependencies installed."
else
  warn "frontend/package.json not found — skipping frontend install."
fi

# ── 5. Verify imports ───────────────────────────────────────────────────────
info "Verifying backend imports..."
"$BACKEND_PY" -c "import sys; sys.path.insert(0, 'src'); import src.server; print('Backend imports OK')" 2>/dev/null \
  || warn "Import check failed (usually missing env vars) — review your .env"

cat <<EOF

${GREEN}Setup complete!${NC}
────────────────────────────────────────────────────────────────────────
Run the backend:
    ${GREEN}.venv/bin/python -m src.server${NC}        # uvicorn on http://0.0.0.0:8000
    # or:  .venv/bin/uvicorn src.server:app --host 0.0.0.0 --port 8000

Run the frontend (separate terminal):
    ${GREEN}cd frontend && npm run dev${NC}            # vite on http://localhost:5173

Open http://localhost:5173 and upload a PDF.
────────────────────────────────────────────────────────────────────────
EOF
