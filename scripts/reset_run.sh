#!/usr/bin/env bash
# Procedimiento completo de reset de runs: para servicios en VPS, crea nuevas
# runs con capital reseteado, actualiza código y reinicia servicios.
#
# Usage:
#   ./scripts/reset_run.sh [version] [capital]
#
# Ejemplos:
#   ./scripts/reset_run.sh v2.0 1000          # reset completo
#   ./scripts/reset_run.sh v2.1 1000          # siguiente ciclo
#   ./scripts/reset_run.sh v3.0 2000          # nuevo ciclo con más capital

set -euo pipefail

VERSION="${1:-v2.0}"
CAPITAL="${2:-1000}"
VPS_IP="187.124.45.248"
VPS_USER="root"
PROJECT_DIR="/root/polymarket-copytrading-bot"
NOTES="Reset estructural ${VERSION}: nuevo sistema de gestión de riesgo"

echo "=============================================="
echo "  Reset de runs — versión=${VERSION} capital=\$${CAPITAL}"
echo "=============================================="

# ── 1. Parar servicios en VPS ─────────────────────────────
echo ""
echo "[1/5] Parando servicios en VPS (${VPS_IP})..."
ssh "${VPS_USER}@${VPS_IP}" \
    "systemctl stop polymarket-specialist polymarket-scalper 2>/dev/null || true && echo '  OK: servicios parados'"

# ── 2. Crear nuevas runs (BD Supabase, acceso local) ──────
echo ""
echo "[2/5] Creando nuevas runs (cerrando posiciones abiertas)..."
python -m scripts.new_run \
    --strategy ALL \
    --version "${VERSION}" \
    --capital "${CAPITAL}" \
    --close-positions \
    --notes "${NOTES}"

# ── 3. Actualizar código en VPS (deploy por archive — no hay git en VPS) ───
echo ""
echo "[3/5] Actualizando código en VPS..."
git archive HEAD | gzip | ssh "${VPS_USER}@${VPS_IP}" "tar xzf - -C ${PROJECT_DIR}/" && echo "  OK: código actualizado"

# ── 4. Reiniciar servicios Python (daemons) ────────────────
echo ""
echo "[4/5] Reiniciando daemons (specialist + scalper)..."
ssh "${VPS_USER}@${VPS_IP}" \
    "systemctl restart polymarket-specialist polymarket-scalper && echo '  OK: servicios reiniciados'"

# ── 5. Rebuild + restart dashboard (Next.js + PM2) ─────────
# El dashboard corre en PM2 y sirve el build prerenderizado de .next/. Un
# `git archive` copia src/ pero Next sigue sirviendo el build viejo hasta
# que rebuildemos y reiniciemos PM2.
echo ""
echo "[5/5] Rebuild + restart dashboard (PM2)..."
./scripts/deploy_dashboard.sh --no-sync

# ── Verificación ──────────────────────────────────────────
echo ""
echo "=============================================="
echo "  Listo. Verificación de logs:"
echo "=============================================="
echo ""
ssh "${VPS_USER}@${VPS_IP}" \
    "journalctl -u polymarket-specialist -n 20 --no-pager 2>/dev/null || echo '  (sin logs disponibles)'"

echo ""
echo "Para ver logs en tiempo real:"
echo "  ssh ${VPS_USER}@${VPS_IP} 'journalctl -u polymarket-specialist -f'"
