#!/usr/bin/env bash
# Deploy dashboard changes to the VPS.
#
# The dashboard is a Next.js app managed by PM2 on the VPS (process name
# "polymarket-dashboard", port 3001). `git archive` copies source files, but
# Next serves a prerendered `.next/` build — so every dashboard change needs
# `npm run build` + `pm2 restart` on the VPS to take effect.
#
# Usage:
#   ./scripts/deploy_dashboard.sh
#
# Skips the git archive step if --no-sync is passed (useful when called right
# after reset_run.sh which already synced the code).

set -euo pipefail

VPS_IP="187.124.45.248"
VPS_USER="root"
PROJECT_DIR="/root/polymarket-copytrading-bot"
PM2_APP="polymarket-dashboard"

SYNC=1
if [[ "${1:-}" == "--no-sync" ]]; then
    SYNC=0
fi

echo "=============================================="
echo "  Deploy dashboard → ${VPS_IP}"
echo "=============================================="

if [[ "${SYNC}" == "1" ]]; then
    echo ""
    echo "[1/3] Sincronizando código..."
    git archive HEAD | gzip | ssh "${VPS_USER}@${VPS_IP}" "tar xzf - -C ${PROJECT_DIR}/"
    echo "  OK: código sincronizado"
else
    echo ""
    echo "[1/3] Omitido (--no-sync): asume que el código ya está sincronizado"
fi

echo ""
echo "[2/3] Rebuild (npm run build)..."
ssh "${VPS_USER}@${VPS_IP}" "cd ${PROJECT_DIR}/dashboard && npm run build 2>&1 | tail -5"

echo ""
echo "[3/3] Reiniciando PM2 ${PM2_APP}..."
ssh "${VPS_USER}@${VPS_IP}" "pm2 restart ${PM2_APP} --update-env 2>&1 | tail -3"

# Smoke test: puerto 3001 debe responder 200 OK
sleep 2
STATUS=$(ssh "${VPS_USER}@${VPS_IP}" "curl -s -o /dev/null -w '%{http_code}' http://localhost:3001/")
echo ""
echo "  Smoke test /: HTTP ${STATUS}"
if [[ "${STATUS}" != "200" ]]; then
    echo "  ⚠ Dashboard no respondió 200 — revisar con: pm2 logs ${PM2_APP} --lines 20"
    exit 1
fi

echo ""
echo "=============================================="
echo "  ✓ Dashboard actualizado"
echo "=============================================="
echo "  Hard refresh en el navegador: Ctrl+Shift+R"
