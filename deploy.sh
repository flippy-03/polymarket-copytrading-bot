#!/usr/bin/env bash
# =============================================================================
# Polymarket CopyTrading Bot — Deploy local → VPS
# =============================================================================
# Uso:
#   ./deploy.sh              # push a GitHub + envía código al VPS + restart
#   ./deploy.sh --setup      # igual + ejecuta vps_setup.sh (primera vez)
#   ./deploy.sh --no-push    # solo envía código + restart (sin git push)
#   ./deploy.sh --logs       # tail de los servicios tras el deploy
#
# El código se transfiere vía git archive | ssh tar (sin credenciales GitHub).
# =============================================================================

set -euo pipefail

# ─────────────────────────── CONFIGURACIÓN ───────────────────────────────────
VPS_HOST="${VPS_HOST:-root@187.124.45.248}"
VPS_DIR="${VPS_DIR:-/root/polymarket-copytrading-bot}"
# ─────────────────────────────────────────────────────────────────────────────

SETUP=false
SKIP_PUSH=false
SHOW_LOGS=false

for arg in "$@"; do
  case $arg in
    --setup)     SETUP=true     ;;
    --no-push)   SKIP_PUSH=true ;;
    --logs)      SHOW_LOGS=true ;;
  esac
done

# ── 1. Git push ───────────────────────────────────────────────────────────────
if [ "$SKIP_PUSH" = false ]; then
  echo "▶ [1/4] git push origin main…"
  git push origin main
else
  echo "▶ [1/4] git push omitido (--no-push)"
fi

# ── 2. Enviar código al VPS (git archive → ssh tar) ──────────────────────────
echo "▶ [2/4] Enviando código → $VPS_HOST:$VPS_DIR …"
ssh "$VPS_HOST" "mkdir -p '$VPS_DIR'"
git archive --format=tar.gz HEAD | ssh "$VPS_HOST" "tar xzf - -C '$VPS_DIR'"
# .env nunca va en git → lo enviamos aparte
scp -q .env "$VPS_HOST:$VPS_DIR/.env"
echo "  código + .env enviados"

# ── 3. Setup inicial o pip install ───────────────────────────────────────────
if [ "$SETUP" = true ]; then
  echo "▶ [3/4] Ejecutando setup inicial en VPS…"
  ssh "$VPS_HOST" "INSTALL_DIR='$VPS_DIR' bash '$VPS_DIR/scripts/vps_setup.sh'"
else
  echo "▶ [3/4] pip install en VPS…"
  ssh "$VPS_HOST" bash <<REMOTE
set -e
cd "$VPS_DIR"
source .venv/bin/activate
pip install -r requirements.txt -q --disable-pip-version-check
echo "  deps OK"
REMOTE
fi

# ── 4. Restart servicios (solo en deploys normales, setup ya los arranca) ────
if [ "$SETUP" = false ]; then
  echo "▶ [4/4] Reiniciando servicios…"
  ssh "$VPS_HOST" "systemctl restart polymarket-basket polymarket-scalper 2>/dev/null && echo '  OK' || echo '  (no instalados aún)'"
fi

# ── Estado final ──────────────────────────────────────────────────────────────
echo ""
echo "✓ Deploy completo. Estado de servicios:"
ssh "$VPS_HOST" bash <<'STATUS'
for svc in polymarket-basket polymarket-scalper; do
  if systemctl is-active --quiet "$svc" 2>/dev/null; then
    echo "  ✓ $svc: running"
  else
    echo "  ✗ $svc: stopped / no instalado"
  fi
done
STATUS

# ── Logs opcionales ───────────────────────────────────────────────────────────
if [ "$SHOW_LOGS" = true ]; then
  echo ""
  echo "── logs (Ctrl+C para salir) ─────────────────────────────────────────────"
  ssh "$VPS_HOST" "journalctl -u polymarket-basket -u polymarket-scalper -f --output=cat"
fi
