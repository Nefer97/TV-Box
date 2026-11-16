#!/bin/bash
# vmtest.sh — prova di installazione da zero: Debian 13 ufficiale in una macchina virtuale,
# install.sh come su un Mac mini nuovo, poi riavvio e controllo che tvd e Chrome partano.
#
#   QEMU_DIR=/percorso/copia/qemu IMG=/percorso/debian-13-genericcloud-amd64.qcow2 bash tools/vmtest.sh
#
# * Non installa niente sul PC: QEMU è una copia estratta in una cartella (QEMU_DIR/x/usr/bin/…).
# * L'immagine non viene modificata (snapshot): le scritture vanno in un file temporaneo.
# * Il progetto arriva alla macchina virtuale da un piccolo server locale (10.0.2.2 = il PC).
# * Senza KVM è lenta (30–90 minuti). L'esito: righe "TVBOX:" alla fine; registro completo in $WORK/serial.log
set -u
cd "$(dirname "$0")/.."
: "${QEMU_DIR:?indica QEMU_DIR}" "${IMG:?indica IMG (immagine Debian 13 genericcloud qcow2)}"
WORK=${WORK:-$(mktemp -d /tmp/tvbox-vmtest.XXXX)}
PORT=${PORT:-8810}
TIMEOUT_MIN=${TIMEOUT_MIN:-150}
echo "Cartella di lavoro: $WORK"

tar czf "$WORK/tvbox.tgz" --exclude=__pycache__ tvd.py tvbox launcher config.json system install.sh
echo "instance-id: tvbox-vmtest-$(date +%s)" > "$WORK/meta-data"
: > "$WORK/vendor-data"
cat > "$WORK/user-data" <<EOF
#cloud-config
hostname: tv
write_files:
  - path: /root/tvtest.sh
    permissions: '0755'
    content: |
      #!/bin/bash
      exec > /dev/ttyS0 2>&1
      echo "TVBOX: inizio installazione \$(date)"
      cd /root && curl -s http://10.0.2.2:$PORT/tvbox.tgz -o tvbox.tgz && mkdir -p tvbox && tar xzf tvbox.tgz -C tvbox
      cd /root/tvbox && bash install.sh
      echo "TVBOX: install.sh esito \$?"
      python3 -c "import sys; sys.path.insert(0, '/opt/tvbox'); import tvbox.main, tvbox.tv" && echo "TVBOX: moduli ok" || echo "TVBOX: moduli ERRORE"
      python3 -c "import json; json.load(open('/etc/tvbox/config.json'))" && echo "TVBOX: config ok" || echo "TVBOX: config ERRORE"
      for f in /opt/tvbox/tvd.py /opt/tvbox/launcher/index.html /opt/tvbox/launcher/js/app.js /opt/tvbox/launcher/inject/panel.js /etc/X11/xorg.conf.d/20-tvbox-video.conf /etc/sudoers.d/tvbox /etc/tmpfiles.d/tvbox-reboot.conf; do
        [ -e "\$f" ] && echo "TVBOX: file ok \$f" || echo "TVBOX: file MANCA \$f"; done
      id tv && echo "TVBOX: utente tv ok"
      dpkg -l google-chrome-stable python3-evdev python3-websocket xserver-xorg-core | awk '/^ii/{print "TVBOX: pacchetto ok "\$2}'
      cat > /var/lib/cloud/scripts/per-boot/zz-tvcheck.sh <<'CHK'
      #!/bin/bash
      exec > /dev/ttyS0 2>&1
      [ -f /root/.tvchecked ] && exit 0
      touch /root/.tvchecked
      echo "TVBOX: secondo avvio, aspetto tvd e Chrome (fino a 15 minuti)"
      for i in \$(seq 90); do grep -q "CDP collegato" /var/log/tvbox/tvd.log 2>/dev/null && break; sleep 10; done
      pgrep -af "/opt/tvbox/tvd.py" | head -1 | sed 's/^/TVBOX: processo /'
      pgrep -c chrome | sed 's/^/TVBOX: processi chrome /'
      grep -E "tvbox |configurazione|Chrome avviato|CDP collegato|ERROR|Traceback" /var/log/tvbox/tvd.log | head -12 | sed 's/^/TVBOX: log /'
      curl -s 127.0.0.1:8765/api/config | head -c 80 | sed 's/^/TVBOX: api /'; echo
      echo "TVBOX_VM_DONE"
      poweroff
      CHK
      chmod +x /var/lib/cloud/scripts/per-boot/zz-tvcheck.sh
      echo "TVBOX: riavvio"
      reboot
runcmd:
  - [ bash, /root/tvtest.sh ]
EOF

( cd "$WORK" && exec python3 -m http.server $PORT --bind 127.0.0.1 >"$WORK/http.log" 2>&1 ) &
HPID=$!
export LD_LIBRARY_PATH="$QEMU_DIR/x/usr/lib/x86_64-linux-gnu:$QEMU_DIR/x/lib/x86_64-linux-gnu"
export QEMU_MODULE_DIR="$QEMU_DIR/x/usr/lib/x86_64-linux-gnu/qemu"
export TMPDIR="$WORK"
"$QEMU_DIR/x/usr/bin/qemu-system-x86_64" \
  -L "$QEMU_DIR/x/usr/share/qemu" -L "$QEMU_DIR/x/usr/share/seabios" -L "$QEMU_DIR/x/usr/lib/ipxe/qemu" \
  -accel tcg,thread=multi -cpu max -smp 4 -m 3072 -name tvbox-vmtest \
  -drive "file=$IMG,if=virtio,snapshot=on" -nic user,model=virtio-net-pci \
  -vga std -display none -serial "file:$WORK/serial.log" \
  -smbios "type=1,serial=ds=nocloud;s=http://10.0.2.2:$PORT/" &
QPID=$!
trap 'kill $QPID $HPID 2>/dev/null' EXIT
for _ in $(seq $((TIMEOUT_MIN * 6))); do
  grep -q TVBOX_VM_DONE "$WORK/serial.log" 2>/dev/null && break
  kill -0 $QPID 2>/dev/null || break
  sleep 10
done
grep -a "TVBOX" "$WORK/serial.log" | tr -d '\r'
grep -q TVBOX_VM_DONE "$WORK/serial.log" && echo "PROVA COMPLETATA" || echo "PROVA NON COMPLETATA (vedi $WORK/serial.log)"
