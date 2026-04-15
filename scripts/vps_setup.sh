#!/usr/bin/env bash
# =============================================================================
# Polymarket CopyTrading Bot — Setup inicial del VPS
# =============================================================================
# Ejecutar UNA VEZ en el VPS desde local:
#
#   scp scripts/vps_setup.sh ubuntu@TU_VPS_IP:~
#   scp .env ubuntu@TU_VPS_IP:~/.env_polymarket
#   ssh ubuntu@TU_VPS_IP 'bash ~/vps_setup.sh'
#
# O si tienes ssh directo desde Claude Code:
#   ssh ubuntu@TU_VPS_IP 'bash -s' < scripts/vps_setup.sh
#
# Qué hace este script:
#   1. Clona el repo (o actualiza si ya existe)
#   2. Crea .venv e instala dependencias
#   3. Copia el .env si existe ~/. env_polymarket
#   4. Ejecuta los builds iniciales (basket + scalper pool + rotación)
#   5. Instala y activa los servicios systemd
#   6. Configura sudoers para restart sin contraseña
# =============================================================================

set -euo pipefail

REPO_URL="https://github.com/flippy-03/polymarket-copytrading-bot.git"
INSTALL_DIR="${INSTALL_DIR:-$HOME/polymarket-copytrading-bot}"
PYTHON="${PYTHON:-python3}"
SYSTEMD_USER=false   # true = systemd --user (no sudo), false = system (sudo)

echo "=== Polymarket CopyTrading Bot — VPS Setup ==="
echo "  Directorio: $INSTALL_DIR"
echo "  Python: $($PYTHON --version)"
echo ""

# ── 1. Clonar / actualizar ────────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "[1/6] Repositorio ya existe, actualizando…"
  git -C "$INSTALL_DIR" pull origin main
else
  echo "[1/6] Clonando repositorio…"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ── 2. Entorno virtual ────────────────────────────────────────────────────────
echo "[2/6] Creando entorno virtual…"
if [ ! -d ".venv" ]; then
  $PYTHON -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q --disable-pip-version-check
echo "  Dependencias instaladas"

# ── 3. Archivo .env ───────────────────────────────────────────────────────────
echo "[3/6] Configurando .env…"
if [ -f "$HOME/.env_polymarket" ]; then
  cp "$HOME/.env_polymarket" .env
  echo "  .env copiado desde ~/.env_polymarket"
elif [ ! -f ".env" ]; then
  cp .env.example .env
  echo ""
  echo "  AVISO: .env creado desde .env.example."
  echo "  Edita $INSTALL_DIR/.env antes de continuar:"
  echo "    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, POLYMARKETSCAN_API_KEY, FALCON_BEARER_TOKEN"
  echo ""
  read -r -p "  Pulsa ENTER cuando hayas configurado el .env…"
fi

# ── 4. Builds iniciales ───────────────────────────────────────────────────────
echo "[4/6] Ejecutando builds iniciales…"
echo "  → Basket build (puede tardar 2-5 min)…"
$PYTHON scripts/run_basket_strategy.py --build-only
echo "  → Scalper pool build…"
$PYTHON scripts/run_scalper_strategy.py --build-pool
echo "  → Rotación inicial (--force)…"
$PYTHON scripts/run_scalper_rotation.py --force
echo "  Builds completados"

# ── 5. Servicios systemd ──────────────────────────────────────────────────────
echo "[5/6] Instalando servicios systemd…"

VENV_PYTHON="$INSTALL_DIR/.venv/bin/python"
CURRENT_USER="$(whoami)"

if [ "$SYSTEMD_USER" = true ]; then
  SYSTEMD_DIR="$HOME/.config/systemd/user"
  SYSTEMCTL="systemctl --user"
  mkdir -p "$SYSTEMD_DIR"
else
  SYSTEMD_DIR="/etc/systemd/system"
  SYSTEMCTL="sudo systemctl"
fi

# Generar servicio basket
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
WantedBy=$([ "$SYSTEMD_USER" = true ] && echo "default.target" || echo "multi-user.target")
EOF

# Generar servicio scalper
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
WantedBy=$([ "$SYSTEMD_USER" = true ] && echo "default.target" || echo "multi-user.target")
EOF

if [ "$SYSTEMD_USER" = true ]; then
  cp /tmp/polymarket-basket.service "$SYSTEMD_DIR/"
  cp /tmp/polymarket-scalper.service "$SYSTEMD_DIR/"
  loginctl enable-linger "$CURRENT_USER" 2>/dev/null || true
  $SYSTEMCTL daemon-reload
  $SYSTEMCTL enable polymarket-basket polymarket-scalper
  $SYSTEMCTL start polymarket-basket polymarket-scalper
else
  sudo cp /tmp/polymarket-basket.service "$SYSTEMD_DIR/"
  sudo cp /tmp/polymarket-scalper.service "$SYSTEMD_DIR/"
  sudo systemctl daemon-reload
  sudo systemctl enable polymarket-basket polymarket-scalper
  sudo systemctl start polymarket-basket polymarket-scalper
fi

# ── 6. Sudoers para deploy sin password ───────────────────────────────────────
if [ "$SYSTEMD_USER" = false ]; then
  echo "[6/6] Configurando sudoers (restart sin contraseña)…"
  SUDOERS_LINE="$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart polymarket-basket, /bin/systemctl restart polymarket-scalper, /bin/systemctl restart polymarket-basket polymarket-scalper"
  echo "$SUDOERS_LINE" | sudo tee /etc/sudoers.d/polymarket-deploy > /dev/null
  sudo chmod 440 /etc/sudoers.d/polymarket-deploy
  echo "  Regla sudoers instalada"
else
  echo "[6/6] Saltando sudoers (modo --user no requiere sudo)"
fi

# ── Resumen ───────────────────────────────────────────────────────────────────
echo ""
echo "=== Setup completado ==="
echo ""
echo "Estado de servicios:"
for svc in polymarket-basket polymarket-scalper; do
  if $SYSTEMCTL is-active --quiet "$svc" 2>/dev/null; then
    echo "  ✓ $svc: running"
  else
    echo "  ✗ $svc: $(${SYSTEMCTL} is-active "$svc" 2>/dev/null || echo 'error')"
  fi
done
echo ""
echo "Comandos útiles:"
echo "  Ver logs:       journalctl -u polymarket-basket -f"
echo "  Parar todo:     $SYSTEMCTL stop polymarket-basket polymarket-scalper"
echo "  Deploy futuro:  ./deploy.sh   (desde tu máquina local)"
