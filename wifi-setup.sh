#!/bin/bash
# wifi-setup.sh — SUL MAC MINI, con sudo. Collega la TV a una rete Wi-Fi.
#  * installa wpasupplicant (gestisce le reti protette WPA/WPA2) e wireless-regdb;
#  * chiede nome rete e password (la password non viene mostrata né salvata in chiaro);
#  * la scheda Wi-Fi prende l'indirizzo con DHCP come il cavo;
#  * se il cavo è collegato ha la precedenza, altrimenti si usa il Wi-Fi.
# Si può rilanciare per cambiare rete.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Va lanciato con sudo"; exit 1; }

IF="$(ls /sys/class/net | grep '^wl' | head -1 || true)"
[ -n "$IF" ] || { echo "Nessuna scheda Wi-Fi trovata"; exit 1; }
echo "Scheda Wi-Fi: $IF"

if ! command -v wpa_passphrase >/dev/null || ! command -v iw >/dev/null; then
  echo "Installo wpasupplicant (serve il cavo di rete collegato)..."
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends wpasupplicant wireless-regdb iw
fi

ip link set "$IF" up || true
echo
echo "Reti visibili:"
for i in 1 2 3; do
  out="$(iw dev "$IF" scan 2>/dev/null | awk -F': ' '/\tSSID: /{print "   " $2}' | sort -u || true)"
  [ -n "$out" ] && break
  sleep 2
done
echo "${out:-   (nessuna trovata con la scansione, puoi comunque scrivere il nome)}"
echo

read -rp "Nome della rete Wi-Fi (esattamente come scritto sopra): " SSID
read -rsp "Password del Wi-Fi (non si vede mentre scrivi): " PW; echo
BLOCK="$(printf '%s\n' "$PW" | wpa_passphrase "$SSID")" || { echo "Password non valida (servono da 8 a 63 caratteri)"; exit 1; }
unset PW

CONF="/etc/wpa_supplicant/wpa_supplicant-$IF.conf"
umask 077
{
  echo "ctrl_interface=DIR=/run/wpa_supplicant GROUP=netdev"
  echo "update_config=1"
  echo "country=IT"
  echo
  # tolgo la riga con la password in chiaro, resta solo la chiave derivata
  printf '%s\n' "$BLOCK" | grep -v '^[[:space:]]*#' | sed 's/^}/\tscan_ssid=1\n}/'
} > "$CONF"
umask 022

cat > /etc/systemd/network/25-wireless.network <<'EOF'
[Match]
Name=wl*

[Network]
DHCP=yes

[DHCPv4]
# il cavo (metrica 100) ha la precedenza sul Wi-Fi
RouteMetric=600
EOF

if ! grep -q RouteMetric /etc/systemd/network/20-wired.network; then
  printf '\n[DHCPv4]\nRouteMetric=100\n' >> /etc/systemd/network/20-wired.network
fi

# all'avvio basta UNA rete connessa (altrimenti senza cavo aspetterebbe 2 minuti)
mkdir -p /etc/systemd/system/systemd-networkd-wait-online.service.d
cat > /etc/systemd/system/systemd-networkd-wait-online.service.d/tvbox-any.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/lib/systemd/systemd-networkd-wait-online --any --timeout=30
EOF

systemctl disable --now wpa_supplicant.service 2>/dev/null || true
systemctl daemon-reload
systemctl enable "wpa_supplicant@$IF.service"
systemctl restart "wpa_supplicant@$IF.service"
networkctl reload

echo -n "Mi collego"
for i in $(seq 1 30); do
  addr="$(ip -4 -br addr show "$IF" | awk '{print $3}')"
  [ -n "$addr" ] && break
  echo -n "."; sleep 1
done
echo
sync
if [ -n "${addr:-}" ]; then
  echo "Wi-Fi collegato a \"$SSID\": indirizzo ${addr%/*}"
else
  echo "Non sono riuscito a collegarmi a \"$SSID\". Stato:"
  journalctl -u "wpa_supplicant@$IF" -n 15 --no-pager
fi
