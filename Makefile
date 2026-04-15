# =============================================================================
# Polymarket CopyTrading Bot — Makefile
# =============================================================================
# Requiere: GNU make, bash, git, ssh configurado para el VPS
#
# Variables de entorno (sobreescribibles):
#   VPS_HOST   — usuario@IP del VPS  (por defecto lee deploy.sh)
#
# Uso rápido:
#   make deploy           → push + actualizar VPS + restart servicios
#   make deploy-env       → igual + sube .env (primera vez o tras cambiar secrets)
#   make logs             → tail de ambos daemons desde local
#   make status           → estado rápido de los servicios
#   make setup-vps        → setup inicial del VPS (ejecutar una vez)
# =============================================================================

.PHONY: deploy deploy-env deploy-nopush logs logs-basket logs-scalper \
        status setup-vps typecheck build-basket build-scalper

# ── Deploy ────────────────────────────────────────────────────────────────────

deploy:
	bash deploy.sh

deploy-env:
	bash deploy.sh --sync-env

deploy-nopush:
	bash deploy.sh --no-push

deploy-logs:
	bash deploy.sh --logs

# ── VPS setup (una sola vez) ──────────────────────────────────────────────────

setup-vps:
	@echo "Sube el .env al VPS primero:"
	@echo "  scp .env \$$VPS_HOST:~/.env_polymarket"
	@echo ""
	@echo "Luego ejecuta en el VPS:"
	@echo "  bash -s < scripts/vps_setup.sh"

# ── Logs y estado ─────────────────────────────────────────────────────────────

logs:
	bash scripts/vps_logs.sh

logs-basket:
	bash scripts/vps_logs.sh basket

logs-scalper:
	bash scripts/vps_logs.sh scalper

status:
	bash scripts/vps_logs.sh status

# ── Builds locales (para probar antes de subir) ───────────────────────────────

build-basket:
	python scripts/run_basket_strategy.py --build-only

build-scalper:
	python scripts/run_scalper_strategy.py --build-pool

rotate:
	python scripts/run_scalper_rotation.py --force

# ── Dashboard ─────────────────────────────────────────────────────────────────

typecheck:
	cd dashboard && npx tsc --noEmit

dev:
	cd dashboard && npm run dev
