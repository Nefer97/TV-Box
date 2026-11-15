#!/bin/bash
# prova-qemu.sh — avvia il disco del Mac mini in una macchina virtuale, SENZA scriverci.
#
# Uso (da utente normale, NON con sudo):   ./prova-qemu.sh /dev/sdc
#
# * QEMU non è installato: usa la copia estratta in una cartella temporanea.
# * Il disco viene aperto in modalità "snapshot": tutto ciò che la macchina virtuale
#   scrive finisce in un file temporaneo, buttato alla chiusura. In più QEMU gira con il
#   tuo utente, che sul disco ha solo il permesso di LETTURA: il disco resta intatto.
# * Il permesso di lettura (setfacl) sparisce da solo quando stacchi il disco o riavvii.
set -euo pipefail

DISK="${1:-}"
Q=/tmp/claude-1000/-home-nefer-Scrivania-tvbox/0cb1e709-74fd-4f7f-a652-c630f166f79e/scratchpad/qemu
die() { echo "ERRORE: $*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "non usare sudo: lancialo come utente normale (./prova-qemu.sh /dev/sdX)"
[ -x "$Q/x/usr/bin/qemu-system-x86_64" ] || die "la copia temporanea di QEMU non c'è più: chiedi a Claude di riprepararla"
[ -n "$DISK" ] && [ -b "$DISK" ] || die "indica il disco, per esempio: ./prova-qemu.sh /dev/sdc"
[ "$(lsblk -dno TYPE "$DISK")" = "disk" ] || die "$DISK non è un disco intero"
[ "$(lsblk -dno TRAN "$DISK" | tr -d ' ')" = "usb" ] || die "$DISK non è un disco USB: mi fermo"
pgrep -f prepare-disk.sh >/dev/null && die "prepare-disk.sh è ancora in esecuzione: aspetta che finisca"
[ -z "$(lsblk -nro MOUNTPOINT "$DISK" | tr -d '[:space:]')" ] \
  || die "una partizione di $DISK è montata: smontala (\"Espelli\" senza staccare il cavo)"

if [ ! -r "$DISK" ]; then
  echo "Do al tuo utente il permesso di SOLA LETTURA su $DISK (sparisce quando stacchi il disco)."
  sudo setfacl -m "u:$USER:r" "$DISK"
fi

ACCEL=(-accel tcg -cpu max)
if [ -w /dev/kvm ]; then
  ACCEL=(-enable-kvm -cpu host)
  echo "Accelerazione KVM attiva."
else
  echo "KVM non disponibile: la macchina virtuale sarà LENTA (l'avvio può richiedere qualche minuto)."
fi

export LD_LIBRARY_PATH="$Q/x/usr/lib/x86_64-linux-gnu:$Q/x/lib/x86_64-linux-gnu"
export QEMU_MODULE_DIR="$Q/x/usr/lib/x86_64-linux-gnu/qemu"
export TMPDIR="$Q/tmp"
mkdir -p "$TMPDIR"

echo "Avvio. Chiudi la finestra per spegnere la macchina virtuale."
echo "Ctrl+Alt+G libera il mouse dalla finestra."
exec "$Q/x/usr/bin/qemu-system-x86_64" \
  -L "$Q/x/usr/share/qemu" -L "$Q/x/usr/share/seabios" -L "$Q/x/usr/lib/ipxe/qemu" \
  "${ACCEL[@]}" -smp 2 -m 2048 -name "tvbox - prova" \
  -drive "file=$DISK,format=raw,if=ide,snapshot=on" \
  -nic user,model=e1000 -vga std -display gtk
