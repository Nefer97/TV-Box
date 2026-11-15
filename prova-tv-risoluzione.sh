#!/bin/bash
# prova-tv-risoluzione.sh — SUL MAC MINI, con sudo.
# La TV collegata in VGA non comunica le risoluzioni che accetta (EDID vuoto), quindi Linux
# usa 1024x768. Questo script prova alcune risoluzioni 16:9 per 20 secondi ciascuna e poi
# torna SEMPRE a 1024x768. Non cambia niente in modo permanente.
#   sudo bash prova-tv-risoluzione.sh                 # prova 1360x768, 1280x720, 1920x1080
#   sudo bash prova-tv-risoluzione.sh 1366x768        # prova solo quella indicata
set -u
[ "$(id -u)" = 0 ] || { echo "Va lanciato con sudo"; exit 1; }
X() { sudo -u tv env DISPLAY=:0 XAUTHORITY=/home/tv/.Xauthority xrandr "$@"; }
OUT=$(X | awk '/ connected/{print $1; exit}')
[ -n "$OUT" ] || { echo "Schermo non trovato (la TV è accesa?)"; exit 1; }
SAFE=1024x768
declare -A ML=(
  [1360x768]="85.50 1360 1424 1536 1792 768 771 777 795 +hsync +vsync"
  [1366x768]="85.50 1366 1436 1579 1792 768 771 774 798 +hsync +vsync"
  [1280x720]="74.25 1280 1390 1430 1650 720 725 730 750 +hsync +vsync"
  [1920x1080]="148.50 1920 2008 2052 2200 1080 1084 1089 1125 +hsync +vsync"
)
trap 'X --output "$OUT" --mode $SAFE; echo; echo "Tornato a $SAFE."' EXIT
for m in ${@:-1360x768 1280x720 1920x1080}; do
  [ -n "${ML[$m]:-}" ] || { echo "Non conosco $m"; continue; }
  X --newmode "$m" ${ML[$m]} 2>/dev/null
  X --addmode "$OUT" "$m" 2>/dev/null
  echo
  echo ">>> PROVA $m: guarda la TV (20 secondi)…"
  if X --output "$OUT" --mode "$m"; then
    for s in $(seq 20 -1 1); do printf "\r    %2d s " "$s"; sleep 1; done
  else
    echo "    (non applicabile)"
  fi
  X --output "$OUT" --mode $SAFE
  echo; echo "    tornato a $SAFE"; sleep 4
done
