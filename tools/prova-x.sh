#!/bin/bash
# prova-x.sh — SUL MAC MINI, con sudo. Prova varie configurazioni di Xorg (pochi secondi
# ciascuna), annota quali reggono e alla fine rimette la sessione TV com'era.
# Risultati in /home/admin/prova-x/ (leggibili da admin).
set -u
OUT=/home/admin/prova-x
rm -rf "$OUT"; mkdir -p "$OUT"
exec > >(tee "$OUT/risultati.txt") 2>&1

echo "== arbiter VGA del kernel"
timeout 2 cat /dev/vga_arbiter; echo

echo "== installo i driver video intel e fbdev (pacchetti Debian, solo sul Mac mini)"
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  xserver-xorg-video-intel xserver-xorg-video-fbdev >/dev/null && echo "installati" || echo "installazione FALLITA"

echo "== fermo la sessione TV"
systemctl stop getty@tty1
pkill -x Xorg; sleep 2

dev() {  # $1 = righe dentro la sezione Device
  printf 'Section "Device"\n    Identifier "gpu"\n%s\nEndSection\n' "$1"
}
try() {  # $1 nome, $2 contenuto xorg.conf
  local name="$1"
  printf '%s\n' "$2" > "$OUT/$name.conf"
  Xorg :5 vt2 -nolisten tcp -config "$OUT/$name.conf" -configdir /nonexistent \
       -logfile "$OUT/$name.log" >/dev/null 2>&1 &
  local pid=$!
  sleep 8
  if kill -0 "$pid" 2>/dev/null; then
    echo "  $name: OK (Xorg resta acceso)"
    kill "$pid"; wait "$pid" 2>/dev/null
  else
    echo "  $name: CRASH"
    grep -m4 -E 'Segmentation|Fatal server error|\(EE\) [0-9]+: ' "$OUT/$name.log" | sed 's/^/      /'
  fi
  sleep 2
}

echo "== prove (lo schermo può lampeggiare)"
try ms-noaccel        "$(dev '    Driver "modesetting"
    Option "AccelMethod" "none"')"
try ms-noaccel-noinput "$(dev '    Driver "modesetting"
    Option "AccelMethod" "none"')
Section \"ServerFlags\"
    Option \"AutoAddDevices\" \"false\"
EndSection"
try intel-sna         "$(dev '    Driver "intel"
    Option "AccelMethod" "sna"')"
try intel-uxa         "$(dev '    Driver "intel"
    Option "AccelMethod" "uxa"')"
try fbdev             "$(dev '    Driver "fbdev"')"

echo "== rimetto la sessione TV"
systemctl reset-failed getty@tty1
systemctl start getty@tty1
chown -R admin: "$OUT"
echo "Fatto."
