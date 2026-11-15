#!/bin/bash
# prova-arb.sh — SUL MAC MINI, con sudo. Confronta Xorg con e senza accesso al VGA arbiter
# (/dev/vga_arbiter), lanciando i comandi che prima lo facevano crashare. Non modifica niente.
# Risultati in /home/admin/prova-arb/risultati.txt
set -u
OUT=/home/admin/prova-arb
rm -rf "$OUT"; mkdir -p "$OUT"
exec > >(tee "$OUT/risultati.txt") 2>&1

systemctl stop getty@tty1 tvbox-prova tvbox-prova2 2>/dev/null
pkill -x Xorg; sleep 2
printf 'Section "Device"\n Identifier "gpu"\n Driver "modesetting"\n Option "AccelMethod" "none"\nEndSection\n' > "$OUT/ms.conf"

# Il test gira dentro un'unità systemd temporanea, così si può nascondere l'arbiter.
cat > "$OUT/test.sh" <<'EOF'
#!/bin/bash
OUT=/home/admin/prova-arb; tag=$1
Xorg :5 vt2 -nolisten tcp -config $OUT/ms.conf -configdir /nonexistent -logfile $OUT/$tag.log >/dev/null 2>&1 &
pid=$!; sleep 5
kill -0 $pid 2>/dev/null || { echo "  [$tag] Xorg non è partito"; exit 0; }
for c in "xset s off" "xset -dpms" "xsetroot -solid black" "xrandr --output VGA-1 --mode 1280x720" "xrandr"; do
  runuser -u tv -- env DISPLAY=:5 sh -c "$c" >/dev/null 2>&1; sleep 2
  if kill -0 $pid 2>/dev/null; then echo "  [$tag] OK     $c"; else echo "  [$tag] CRASH  $c"; exit 0; fi
done
kill $pid; wait $pid 2>/dev/null
EOF
chmod +x "$OUT/test.sh"

echo "== con arbiter (come adesso)"
systemd-run --quiet --wait --pipe --unit=prova-arb-1 "$OUT/test.sh" con-arbiter
sleep 2
echo "== SENZA arbiter"
systemd-run --quiet --wait --pipe --unit=prova-arb-2 -p InaccessiblePaths=/dev/vga_arbiter "$OUT/test.sh" senza-arbiter
grep -h -i "arbiter" "$OUT"/senza-arbiter.log | head -3

chown -R admin: "$OUT"
echo "Fatto."
