# =============================================================================
# agent-sandbox — Makefile
#
# Two runtimes, same codebase:
#   local   — native macOS (no Docker): Chrome headless + uvicorn API + MCP
#   docker  — containerised (OrbStack / remote server): full stack with VNC
#
# Local lifecycle:
#   make login   →  headed Chrome for one-time auth (WhatsApp, Messages, Outlook)
#   make start   →  headless Chrome + API + MCP
#   make stop    →  kill all local processes
#   make restart →  stop + start
#   make status  →  show which ports are alive
#   make logs    →  tail all three log files
#   make test    →  run e2e suite against the running local stack
#   make setup   →  create .venv-local and install Python deps (auto-run by start)
#   make clean   →  remove venv + Chrome profile data
#
# Docker lifecycle:
#   make docker-build   →  build image from scratch
#   make docker-up      →  start container (build if needed)
#   make docker-down    →  stop and remove container
#   make docker-restart →  down + up
#   make docker-logs    →  follow container logs
#   make docker-test    →  run e2e suite against the running container
#   make docker-shell   →  open bash inside the container
# =============================================================================

SHELL := /bin/bash

# --- paths ---
REPO_ROOT   := $(shell pwd)
VENV        := $(REPO_ROOT)/.venv-local
PYTHON      := $(VENV)/bin/python3
PIP         := $(VENV)/bin/pip
UVICORN     := $(VENV)/bin/uvicorn

# --- ports ---
CDP_PORT  ?= 9222
API_PORT  ?= 8091
MCP_PORT  ?= 8079

# --- Chrome ---
CHROME_BIN  := /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
CHROME_DATA := $(HOME)/.config/agent-sandbox-local

# --- logs ---
LOG_CHROME := /tmp/agent-sandbox-chrome.log
LOG_API    := /tmp/agent-sandbox-api.log
LOG_MCP    := /tmp/agent-sandbox-mcp.log
LOG_MAIN   := /tmp/agent-sandbox-main.log

.DEFAULT_GOAL := help

# =============================================================================
# Help
# =============================================================================

.PHONY: help
help:
	@echo ""
	@echo "agent-sandbox — local (native macOS) targets:"
	@echo "  make setup      Create .venv-local and install Python deps"
	@echo "  make login      Open headed Chrome for one-time service login/QR pairing"
	@echo "  make start      Start headless Chrome + REST API + MCP server"
	@echo "  make stop       Kill all local sandbox processes"
	@echo "  make restart    stop + start"
	@echo "  make status     Show which ports are live"
	@echo "  make logs       Tail Chrome + API + MCP logs"
	@echo "  make logs-chrome  Tail Chrome log only"
	@echo "  make logs-api     Tail API log only"
	@echo "  make logs-mcp     Tail MCP log only"
	@echo "  make test       Run e2e suite against the running local stack"
	@echo "  make clean      Remove .venv-local and Chrome profile data"
	@echo ""
	@echo "Docker targets:"
	@echo "  make docker-build    Build image from scratch (--no-cache)"
	@echo "  make docker-up       Start container (build if image missing)"
	@echo "  make docker-down     Stop and remove container"
	@echo "  make docker-restart  docker-down + docker-up"
	@echo "  make docker-logs     Follow container logs"
	@echo "  make docker-test     Run e2e suite against the running container"
	@echo "  make docker-shell    Open bash inside the container"
	@echo ""
	@echo "Messaging sidecar targets (native protocol — no browser needed):"
	@echo "  make messaging-up      Start both WhatsApp + Google Messages sidecars"
	@echo "  make messaging-down    Stop both sidecars"
	@echo "  make whatsapp-up       Build + start WhatsApp MCP sidecar"
	@echo "  make whatsapp-down     Stop WhatsApp MCP sidecar"
	@echo "  make whatsapp-logs     Follow WhatsApp MCP logs (shows QR on first run)"
	@echo "  make whatsapp-qr       Alias for whatsapp-logs (for QR scanning)"
	@echo "  make whatsapp-repair   Clear session + re-pair (messages preserved)"
	@echo "  make gmessages-up      Build + start Google Messages MCP sidecar"
	@echo "  make gmessages-down    Stop Google Messages MCP sidecar"
	@echo "  make gmessages-logs    Follow Google Messages MCP logs"
	@echo ""

# =============================================================================
# Local — setup
# =============================================================================

.PHONY: setup
setup: $(VENV)

$(VENV):
	python3 -m venv $(VENV)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q \
		-r $(REPO_ROOT)/core/api/requirements.txt \
		-r $(REPO_ROOT)/core/mcp_server/requirements.txt
	@echo "Virtualenv ready at $(VENV)"

# =============================================================================
# Local — login (one-time, headed Chrome)
# =============================================================================

.PHONY: login
login:
	@bash $(REPO_ROOT)/scripts/login.sh

# =============================================================================
# Local — start / stop / restart
# =============================================================================

.PHONY: start
start: setup
	@bash $(REPO_ROOT)/scripts/run-local.sh

.PHONY: stop
stop:
	@echo "Stopping local sandbox..."
	@lsof -ti:$(API_PORT) -ti:$(MCP_PORT) -ti:$(CDP_PORT) | xargs kill -9 2>/dev/null || true
	@pkill -f "agent-sandbox-local" 2>/dev/null || true
	@echo "Done."

.PHONY: restart
restart: stop start

# =============================================================================
# Local — status
# =============================================================================

.PHONY: status
status:
	@echo "Checking local sandbox ports..."
	@for port in $(CDP_PORT) $(API_PORT) $(MCP_PORT); do \
		if lsof -ti:$$port >/dev/null 2>&1; then \
			echo "  :$$port  UP"; \
		else \
			echo "  :$$port  DOWN"; \
		fi; \
	done
	@echo ""
	@echo "Service URLs (when up):"
	@echo "  REST API : http://localhost:$(API_PORT)/v1/docs"
	@echo "  MCP SSE  : http://localhost:$(MCP_PORT)/mcp/sse"
	@echo "  CDP      : http://localhost:$(CDP_PORT)"

# =============================================================================
# Local — logs
# =============================================================================

.PHONY: logs
logs:
	@tail -f $(LOG_CHROME) $(LOG_API) $(LOG_MCP)

.PHONY: logs-chrome
logs-chrome:
	@tail -f $(LOG_CHROME)

.PHONY: logs-api
logs-api:
	@tail -f $(LOG_API)

.PHONY: logs-mcp
logs-mcp:
	@tail -f $(LOG_MCP)

# =============================================================================
# Local — test (e2e against running local stack)
# =============================================================================

.PHONY: test
test: setup
	@echo "Running e2e tests against local stack..."
	@$(PYTHON) tests/e2e.py \
		--api http://localhost:$(API_PORT) \
		--mcp http://localhost:$(MCP_PORT)

# =============================================================================
# Local — clean
# =============================================================================

.PHONY: clean
clean: stop
	@echo "Removing virtualenv and Chrome profile..."
	@rm -rf $(VENV)
	@rm -rf $(CHROME_DATA)
	@rm -f $(LOG_CHROME) $(LOG_API) $(LOG_MCP) $(LOG_MAIN)
	@echo "Clean done. Run 'make login' then 'make start' to rebuild."

# =============================================================================
# Docker — build / up / down / restart
# =============================================================================

.PHONY: docker-build
docker-build:
	docker compose build --no-cache sandbox

.PHONY: docker-up
docker-up:
	docker compose up -d sandbox
	@echo "Container starting. Dashboard: http://localhost:8080"

.PHONY: docker-down
docker-down:
	docker compose down

.PHONY: docker-restart
docker-restart: docker-down docker-up

# =============================================================================
# Docker — logs / shell / test
# =============================================================================

.PHONY: docker-logs
docker-logs:
	docker compose logs -f sandbox

.PHONY: docker-shell
docker-shell:
	docker compose exec sandbox bash

.PHONY: docker-test
docker-test:
	@echo "Running e2e tests against Docker container..."
	python3 tests/e2e.py

# =============================================================================
# Messaging sidecars — WhatsApp (whatsmeow) + Google Messages (OpenMessage)
# Both require the core sandbox to be running first (shared agent-sandbox-net).
# =============================================================================

.PHONY: messaging-up
messaging-up: whatsapp-up gmessages-up

.PHONY: messaging-down
messaging-down: whatsapp-down gmessages-down

# --- WhatsApp MCP (pesnik/whatsapp-mcp Go bridge + FastMCP SSE) ---

.PHONY: whatsapp-up
whatsapp-up:
	@echo "Building + starting WhatsApp MCP sidecar..."
	docker compose -f docker-compose.yml -f docker-compose.whatsapp-mcp.yml up -d --build whatsapp-mcp
	@echo "MCP SSE: http://localhost:8081/sse  |  via nginx: http://localhost:8080/whatsapp-mcp/sse"

.PHONY: whatsapp-down
whatsapp-down:
	docker compose -f docker-compose.yml -f docker-compose.whatsapp-mcp.yml stop whatsapp-mcp
	docker compose -f docker-compose.yml -f docker-compose.whatsapp-mcp.yml rm -f whatsapp-mcp

.PHONY: whatsapp-logs
whatsapp-logs:
	docker logs -f agent-whatsapp-mcp

.PHONY: whatsapp-qr
whatsapp-qr:
	@echo "Ensuring WhatsApp MCP sidecar is running..."
	docker compose -f docker-compose.yml -f docker-compose.whatsapp-mcp.yml up -d whatsapp-mcp
	@echo "Tailing logs — scan the QR with WhatsApp → Settings → Linked Devices → Link a Device"
	docker logs -f agent-whatsapp-mcp

.PHONY: whatsapp-repare
whatsapp-repare:
	@echo "⚠️  This will clear the WhatsApp session and re-pair."
	@echo "    Your message history (messages.db) will be backed up and restored."
	@echo "    You will need to re-scan the QR code from WhatsApp → Linked Devices."
	@read -p "Continue? [y/N] " ans && [ "$${ans}" = "y" ] || { echo "Aborted."; exit 1; }
	@echo "Backing up messages.db..."
	docker exec agent-whatsapp-mcp cp /data/store/messages.db /data/store/messages.db.bak 2>/dev/null || true
	@echo "Removing session store..."
	docker exec agent-whatsapp-mcp rm -f /data/store/whatsapp.db /data/store/whatsapp.db-journal
	@echo "Restarting container..."
	docker restart agent-whatsapp-mcp
	@echo ""
	@echo "⏳ Waiting for bridge to initialise (10s)..."
	@sleep 10
	@echo "Restoring messages.db backup..."
	docker exec agent-whatsapp-mcp sh -c 'if [ -f /data/store/messages.db.bak ]; then cp /data/store/messages.db.bak /data/store/messages.db && echo "✅ Messages restored"; else echo "⚠️  No backup found"; fi'
	@echo ""
	@echo "Scan the QR code below with WhatsApp → Settings → Linked Devices → Link a Device"
	docker logs -f agent-whatsapp-mcp

# --- Google Messages MCP (OpenMessage / libgm) ---

.PHONY: gmessages-up
gmessages-up:
	@echo "Building + starting Google Messages MCP sidecar..."
	docker compose -f docker-compose.yml -f docker-compose.gmessages-mcp.yml up -d --build gmessages-mcp
	@echo "Google Messages MCP starting."
	@echo "Open http://localhost:8080/gmessages/ to scan QR code (first run only)."
	@echo "MCP SSE: http://localhost:7007/mcp/sse  |  via nginx: http://localhost:8080/gmessages/mcp/sse"

.PHONY: gmessages-down
gmessages-down:
	docker compose -f docker-compose.yml -f docker-compose.gmessages-mcp.yml stop gmessages-mcp
	docker compose -f docker-compose.yml -f docker-compose.gmessages-mcp.yml rm -f gmessages-mcp

.PHONY: gmessages-logs
gmessages-logs:
	docker logs --tail 40 -f agent-gmessages-mcp

.PHONY: gmessages-restart
gmessages-restart:
	docker compose -f docker-compose.yml -f docker-compose.gmessages-mcp.yml restart gmessages-mcp
	docker logs --tail 40 -f agent-gmessages-mcp
