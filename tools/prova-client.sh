#!/bin/bash
# prova-client.sh — SUL MAC MINI, con sudo. Avvia Xorg (pochi secondi) e lancia UN comando
# della sessione alla volta, per scoprire quale manda Xorg in crash. Non modifica niente.
# Risultati in /home/admin/prova-client/risultati.txt
set -u
OUT=/home/admin/prova-client
rm -rf "$OUT"; mkdir -p "$OUT"
exec > >(tee "$OUT/risultati.txt") 2>&1

systemctl stop getty@tty1 2>/dev/null
pkill -x Xorg; sleep 2

conf() {  # $1 = driver
  if [ "$1" = intel ]; then
    printf 'Section "Device"\n Identifier "gpu"\n Driver "intel"\n Option "AccelMethod" "sna"\nEndSection\n'
  else
    printf 'Section "Device"\n Identifier "gpu"\n Driver "modesetting"\n Option "AccelMethod" "none"\nEndSection\n'
  fi
}
try() {  # $1 driver, $2 comando
  local drv="$1" cmd="$2" tag
  tag="$drv-$(echo "$cmd" | tr -c 'a-zA-Z0-9' '_')"
  conf "$drv" > "$OUT/$drv.conf"
  Xorg :5 vt2 -nolisten tcp -config "$OUT/$drv.conf" -configdir /nonexistent \
       -logfile "$OUT/$tag.log" >/dev/null 2>&1 &
  local pid=$!
  sleep 5
  if ! kill -0 "$pid" 2>/dev/null; then echo "  [$drv] Xorg non è nemmeno partito"; return; fi
  runuser -u tv -- env DISPLAY=:5 sh -c "$cmd" >"$OUT/$tag.out" 2>&1
  sleep 3
  if kill -0 "$pid" 2>/dev/null; then
    echo "  [$drv] OK     $cmd"
    kill "$pid"; wait "$pid" 2>/dev/null
  else
    echo "  [$drv] CRASH  $cmd"
  fi
  sleep 2
}

for drv in modesetting intel; do
  echo "== driver $drv"
  try "$drv" "true"
  try "$drv" "xset s off"
  try "$drv" "xset s noblank"
  try "$drv" "xset -dpms"
  try "$drv" "xsetroot -solid black"
  try "$drv" "xrandr"
  try "$drv" "xrandr --output VGA-1 --mode 1280x720"
done

chown -R admin: "$OUT"
echo "Fatto. (la sessione TV resta ferma: niente schermo che lampeggia)"
