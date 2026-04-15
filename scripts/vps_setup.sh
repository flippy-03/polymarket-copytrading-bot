#!/usr/bin/env bash
# =============================================================================
# Polymarket CopyTrading Bot — Setup inicial del VPS
# =============================================================================
# Ejecutado automáticamente por deploy.sh --setup desde local.
# No necesitas clonarlo ni llamarlo directamente.
#
# Qué hace:
#   1. Verifica que el código ya esté en INSTALL_DIR (lo pone deploy.sh)
#   2. Crea .venv e instala dependencias
#   3. Ejecuta los builds iniciales (basket + scalper pool + rotación forzada)
#   4. Instala y activa los servicios systemd
# =============================================================================

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/root/polymarket-copytrading-bot}"
PYTHON="${PYTHON:-python3}"

echo "=== Polymarket CopyTrading Bot — VPS Setup ==="
echo "  Directorio: $INSTALL_DIR"
echo "  Python: $($PYTHON --version)"
echo ""

# ── 1. Verificar código ───────────────────────────────────────────────────────
echo "[1/4] Verificando código…"
if [ ! -f "$INSTALL_DIR/requirements.txt" ]; then
  echo "ERROR: Código no encontrado en $INSTALL_DIR"
  echo "Asegúrate de ejecutar este script desde deploy.sh --setup"
  exit 1
fi
cd "$INSTALL_DIR"
echo "  OK"

# ── 2. Entorno virtual ────────────────────────────────────────────────────────
echo "[2/4] Creando entorno virtual e instalando deps…"
if [ ! -d ".venv" ]; then
  $PYTHON -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q --disable-pip-version-check
echo "  Dependencias instaladas"

# ── 3. Builds iniciales ───────────────────────────────────────────────────────
echo "[3/4] Ejecutando builds iniciales…"
echo "  → Basket build (puede tardar 2-5 min)…"
$PYTHON scripts/run_basket_strategy.py --build-only
echo "  → Scalper pool build…"
$PYTHON scripts/run_scalper_strategy.py --build-pool
echo "  → Rotación inicial (--force)…"
$PYTHON scripts/run_scalper_rotation.py --force
echo "  Builds completados"

# ── 4. Servicios systemd ──────────────────────────────────────────────────────
echo "[4/4] Instalando servicios systemd…"

VENV_PYTHON="$INSTALL_DIR/.venv/bin/python"
CURRENT_USER="$(whoami)"
SYSTEMD_DIR="/etc/systemd/system"

cat > /tmp/polymarket-basket.service << EOF
[Unit]
Description=Polymarket Basket Consensus Strategy
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_PYTHON scripts/run_basket_strategy.py --run
EnvironmentFile=$INSTALL_DIR/.env
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=polymarket-basket

[Install]
WantedBy=multi-user.target
EOF

cat > /tmp/polymarket-scalper.service << EOF
[Unit]
Description=Polymarket Scalper Rotator Strategy
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_PYTHON scripts/run_scalper_strategy.py --run
EnvironmentFile=$INSTALL_DIR/.env
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=polymarket-scalper

[Install]
WantedBy=multi-user.target
EOF

cp /tmp/polymarket-basket.service "$SYSTEMD_DIR/"
cp /tmp/polymarket-scalper.service "$SYSTEMD_DIR/"
systemctl daemon-reload
systemctl enable polymarket-basket polymarket-scalper
systemctl start polymarket-basket polymarket-scalper

# ── Resumen ───────────────────────────────────────────────────────────────────
echo ""
echo "=== Setup completado ==="
echo ""
echo "Estado de servicios:"
for svc in polymarket-basket polymarket-scalper; do
  STATUS=$(systemctl is-active "$svc" 2>/dev/null || echo "error")
  echo "  $svc: $STATUS"
done
echo ""
echo "Comandos útiles desde local:"
echo "  Ver logs:    bash scripts/vps_logs.sh"
echo "  Deploy:      bash deploy.sh"
