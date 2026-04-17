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
# Limpiar directorios que git archive no borra (pages/routes eliminados siguen en VPS).
# Borramos y re-extraemos dashboard/src/app y src/strategies para garantizar paridad con git HEAD.
ssh "$VPS_HOST" "rm -rf '$VPS_DIR/dashboard/src/app' '$VPS_DIR/dashboard/src/components' '$VPS_DIR/src/strategies'"
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

# ── 4. Instalar units (si no existen) + restart servicios ────────────────────
if [ "$SETUP" = false ]; then
  echo "▶ [4/5] Instalando/reiniciando servicios Python…"
  ssh "$VPS_HOST" bash <<REMOTE
set -e
cd "$VPS_DIR"
# Instalar unit specialist si no existe aún
if [ ! -f /etc/systemd/system/polymarket-specialist.service ]; then
  cp deploy/polymarket-specialist.service /etc/systemd/system/polymarket-specialist.service
  systemctl daemon-reload
  systemctl enable polymarket-specialist
  echo "  unit polymarket-specialist instalado y habilitado"
fi
# Instalar unit profile-enricher si no existe aún
if [ ! -f /etc/systemd/system/polymarket-profile-enricher.service ]; then
  cp deploy/polymarket-profile-enricher.service /etc/systemd/system/polymarket-profile-enricher.service
  systemctl daemon-reload
  systemctl enable polymarket-profile-enricher
  echo "  unit polymarket-profile-enricher instalado y habilitado"
fi
# Instalar roadmap updater timer si no existe aún
if [ ! -f /etc/systemd/system/polymarket-roadmap-updater.timer ]; then
  cp deploy/polymarket-roadmap-updater.service /etc/systemd/system/polymarket-roadmap-updater.service
  cp deploy/polymarket-roadmap-updater.timer /etc/systemd/system/polymarket-roadmap-updater.timer
  systemctl daemon-reload
  systemctl enable polymarket-roadmap-updater.timer
  systemctl start polymarket-roadmap-updater.timer
  echo "  timer polymarket-roadmap-updater instalado (daily 06:00 UTC)"
fi
# Reiniciar servicios activos
systemctl restart polymarket-scalper 2>/dev/null && echo "  polymarket-scalper restarted" || echo "  polymarket-scalper: no instalado"
systemctl restart polymarket-specialist 2>/dev/null && echo "  polymarket-specialist restarted" || echo "  polymarket-specialist: no instalado"
systemctl restart polymarket-profile-enricher 2>/dev/null && echo "  polymarket-profile-enricher restarted" || echo "  polymarket-profile-enricher: no instalado"
REMOTE
fi

# ── 5. Build + restart dashboard (Next.js via PM2) ───────────────────────────
echo "▶ [5/5] Build dashboard + pm2 restart…"
ssh "$VPS_HOST" bash <<REMOTE
set -e
cd "$VPS_DIR/dashboard"
npm run build
pm2 restart polymarket-dashboard 2>/dev/null && echo "  dashboard restarted" || pm2 start npm --name polymarket-dashboard -- start
REMOTE

# ── Estado final ──────────────────────────────────────────────────────────────
echo ""
echo "✓ Deploy completo. Estado de servicios:"
ssh "$VPS_HOST" bash <<'STATUS'
for svc in polymarket-scalper polymarket-specialist polymarket-profile-enricher; do
  if systemctl is-active --quiet "$svc" 2>/dev/null; then
    echo "  ✓ $svc: running"
  else
    echo "  ✗ $svc: stopped / no instalado"
  fi
done
pm2 jlist 2>/dev/null | python3 -c "
import json,sys
procs = json.load(sys.stdin)
for p in procs:
    status = p['pm2_env']['status']
    name = p['name']
    print(f'  {chr(10003) if status==\"online\" else chr(10007)} {name}: {status}')
" 2>/dev/null || pm2 list --no-color 2>/dev/null | grep polymarket-dashboard || true
STATUS

# ── Logs opcionales ───────────────────────────────────────────────────────────
if [ "$SHOW_LOGS" = true ]; then
  echo ""
  echo "── logs (Ctrl+C para salir) ─────────────────────────────────────────────"
  ssh "$VPS_HOST" "journalctl -u polymarket-scalper -u polymarket-specialist -u polymarket-profile-enricher -f --output=cat"
fi
