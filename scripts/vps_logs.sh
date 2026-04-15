#!/usr/bin/env bash
# =============================================================================
# Ver logs de los daemons desde local via SSH
# =============================================================================
# Uso:
#   ./scripts/vps_logs.sh              # ambos servicios (interleaved)
#   ./scripts/vps_logs.sh basket       # solo basket
#   ./scripts/vps_logs.sh scalper      # solo scalper
#   ./scripts/vps_logs.sh status       # estado rápido
# =============================================================================

VPS_HOST="${VPS_HOST:-ubuntu@YOUR_VPS_IP}"

CMD="${1:-both}"

case "$CMD" in
  basket)
    ssh "$VPS_HOST" "journalctl -u polymarket-basket -f --output=cat 2>/dev/null || journalctl --user -u polymarket-basket -f --output=cat"
    ;;
  scalper)
    ssh "$VPS_HOST" "journalctl -u polymarket-scalper -f --output=cat 2>/dev/null || journalctl --user -u polymarket-scalper -f --output=cat"
    ;;
  status)
    ssh "$VPS_HOST" bash <<'EOF'
echo "=== Estado de servicios ==="
for svc in polymarket-basket polymarket-scalper; do
  STATUS=$(systemctl is-active "$svc" 2>/dev/null || systemctl --user is-active "$svc" 2>/dev/null || echo "unknown")
  SINCE=$(systemctl show "$svc" -p ActiveEnterTimestamp --value 2>/dev/null \
    || systemctl --user show "$svc" -p ActiveEnterTimestamp --value 2>/dev/null || echo "")
  echo "  $svc: $STATUS ${SINCE:+(desde $SINCE)}"
done
echo ""
echo "=== Últimas 20 líneas basket ==="
journalctl -u polymarket-basket -n 20 --output=cat 2>/dev/null \
  || journalctl --user -u polymarket-basket -n 20 --output=cat 2>/dev/null || echo "(sin logs)"
echo ""
echo "=== Últimas 20 líneas scalper ==="
journalctl -u polymarket-scalper -n 20 --output=cat 2>/dev/null \
  || journalctl --user -u polymarket-scalper -n 20 --output=cat 2>/dev/null || echo "(sin logs)"
EOF
    ;;
  *)
    ssh "$VPS_HOST" "journalctl -u polymarket-basket -u polymarket-scalper -f --output=cat 2>/dev/null || journalctl --user -u polymarket-basket -u polymarket-scalper -f --output=cat"
    ;;
esac
