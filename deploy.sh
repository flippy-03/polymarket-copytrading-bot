#!/usr/bin/env bash
# =============================================================================
# Polymarket CopyTrading Bot — Deploy local → VPS
# =============================================================================
# Uso:
#   ./deploy.sh              # push + pull remoto + restart servicios
#   ./deploy.sh --sync-env   # igual + sube .env al VPS (primera vez o tras cambios)
#   ./deploy.sh --no-push    # solo actualiza el VPS (útil si ya pusheaste)
#   ./deploy.sh --logs       # tail de ambos servicios tras el deploy
#
# Prerequisito: haber ejecutado scripts/vps_setup.sh en el VPS al menos una vez.
# =============================================================================

set -euo pipefail

# ─────────────────────────── CONFIGURACIÓN ───────────────────────────────────
VPS_HOST="${VPS_HOST:-ubuntu@YOUR_VPS_IP}"           # usuario@IP del VPS
VPS_DIR="${VPS_DIR:-/home/ubuntu/polymarket-copytrading-bot}"
# ─────────────────────────────────────────────────────────────────────────────

SYNC_ENV=false
SKIP_PUSH=false
SHOW_LOGS=false

for arg in "$@"; do
  case $arg in
    --sync-env)  SYNC_ENV=true  ;;
    --no-push)   SKIP_PUSH=true ;;
    --logs)      SHOW_LOGS=true ;;
  esac
done

# ── 0. Validación rápida ──────────────────────────────────────────────────────
if [[ "$VPS_HOST" == *"YOUR_VPS_IP"* ]]; then
  echo "ERROR: Edita VPS_HOST en deploy.sh (o exporta la variable)."
  echo "  export VPS_HOST=ubuntu@1.2.3.4"
  exit 1
fi

# ── 1. Git push ───────────────────────────────────────────────────────────────
if [ "$SKIP_PUSH" = false ]; then
  echo "▶ [1/4] git push origin main…"
  git push origin main
else
  echo "▶ [1/4] git push omitido (--no-push)"
fi

# ── 2. Sync .env (opcional) ───────────────────────────────────────────────────
if [ "$SYNC_ENV" = true ]; then
  echo "▶ [2/4] Subiendo .env al VPS…"
  scp .env "$VPS_HOST:$VPS_DIR/.env"
else
  echo "▶ [2/4] .env no sincronizado (pasa --sync-env si cambiaron secrets)"
fi

# ── 3. Update remoto ──────────────────────────────────────────────────────────
echo "▶ [3/4] Actualizando VPS…"
ssh "$VPS_HOST" bash <<REMOTE
set -e
cd "$VPS_DIR"
echo "  git pull..."
git pull origin main
echo "  pip install..."
source .venv/bin/activate
pip install -r requirements.txt -q --disable-pip-version-check
echo "  VPS actualizado"
REMOTE

# ── 4. Restart servicios ──────────────────────────────────────────────────────
echo "▶ [4/4] Reiniciando servicios…"
ssh "$VPS_HOST" "sudo -n systemctl restart polymarket-basket polymarket-scalper 2>/dev/null || systemctl --user restart polymarket-basket polymarket-scalper"

# ── Estado final ──────────────────────────────────────────────────────────────
echo ""
echo "✓ Deploy completo. Estado de servicios:"
ssh "$VPS_HOST" bash <<'STATUS'
for svc in polymarket-basket polymarket-scalper; do
  if systemctl is-active --quiet "$svc" 2>/dev/null || systemctl --user is-active --quiet "$svc" 2>/dev/null; then
    echo "  ✓ $svc: running"
  else
    echo "  ✗ $svc: STOPPED/FAILED"
  fi
done
STATUS

# ── Logs opcionales ───────────────────────────────────────────────────────────
if [ "$SHOW_LOGS" = true ]; then
  echo ""
  echo "── logs (Ctrl+C para salir) ─────────────────────────────────────────────"
  ssh "$VPS_HOST" "journalctl -u polymarket-basket -u polymarket-scalper -f --output=cat" \
    2>/dev/null || \
  ssh "$VPS_HOST" "journalctl --user -u polymarket-basket -u polymarket-scalper -f --output=cat"
fi
