# Zero-Touch Site Assessor — Developer Makefile
# IMPORTANT: All Python commands run inside .venv (CLAUDE.md mandatory rule).

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
UVICORN := $(VENV)/bin/uvicorn

FRONTEND_DIR := src/web/frontend

.PHONY: help setup test test-live test-live-video lint typecheck dev frontend clean

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  setup      Create .venv and install all dependencies"
	@echo "  test       Run full test suite (offline, no API keys needed)"
	@echo "  test-live       Run live integration tests (requires GEMINI_API_KEY)"
	@echo "  test-live-video Run 3D pipeline live test (requires GEMINI_API_KEY + VIDEO_PATH)"
	@echo "  lint       Run ruff linter"
	@echo "  typecheck  Run mypy strict type check"
	@echo "  dev        Start FastAPI backend (hot-reload, port 8000)"
	@echo "  frontend   Start Next.js dev server (port 3000)"
	@echo "  clean      Remove __pycache__ and .pytest_cache"

# ── Environment setup ────────────────────────────────────────────────────────

setup:
	python3 -m venv $(VENV)
	$(PIP) install -e ".[dev]"
	@echo ""
	@echo "✓ .venv ready. Activate with: source $(VENV)/bin/activate"

# ── Tests ────────────────────────────────────────────────────────────────────

test:
	$(PYTEST) tests/ --ignore=tests/test_integration_live.py -v

test-live:
	@if [ -z "$$GEMINI_API_KEY" ]; then \
		echo "Error: GEMINI_API_KEY is not set"; exit 1; \
	fi
	$(PYTEST) tests/test_integration_live.py -v

test-live-video:
	@if [ -z "$$GEMINI_API_KEY" ]; then \
		echo "Error: GEMINI_API_KEY is not set"; exit 1; \
	fi
	@if [ -z "$$VIDEO_PATH" ]; then \
		echo "Error: VIDEO_PATH is not set (e.g. make test-live-video VIDEO_PATH=/path/to/roof.mp4)"; exit 1; \
	fi
	$(PYTEST) tests/test_integration_live.py -v -k "video" \
		--video-path="$$VIDEO_PATH"

# ── Quality checks ───────────────────────────────────────────────────────────

lint:
	$(VENV)/bin/ruff check src/ tests/

typecheck:
	$(VENV)/bin/mypy src/

# ── Dev servers ──────────────────────────────────────────────────────────────

dev:
	$(UVICORN) src.web.app:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd $(FRONTEND_DIR) && npm run dev

# ── Cleanup ──────────────────────────────────────────────────────────────────

clean:
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache
