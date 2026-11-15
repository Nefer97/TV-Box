#!/bin/bash
# prepare-disk.sh — installa Debian 13 + tvbox sul disco del Mac mini collegato via USB.
#
# Uso:  sudo ./prepare-disk.sh /dev/sdX
#
# Il PC su cui gira NON viene modificato:
#   * nessun pacchetto installato o aggiornato (debootstrap e le chiavi Debian vengono
#     scaricati in una cartella temporanea, estratti e cancellati alla fine);
#   * dentro il chroot /run è un tmpfs vuoto: i pacchetti Debian non "vedono" il systemd
#     di questo PC, quindi non possono avviare, ricaricare o toccare i suoi servizi;
#   * /proc e /sys sono montati nuovi (non condivisi), /dev in sola bind;
#   * alla fine si smonta tutto e si rimuovono /mnt/tvbox-target e i file temporanei.
# Si può rilanciare da capo quante volte serve: ogni volta ricomincia dalla cancellazione.
set -euo pipefail

DISK="${1:-}"
TARGET=/mnt/tvbox-target
MIRROR=http://deb.debian.org/debian
MIRROR_HTTPS=https://deb.debian.org/debian
SUITE=trixie
SRC="$(cd "$(dirname "$0")" && pwd)"
LOG="$SRC/prepare-disk.log"
WORK=""

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mERRORE: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- controlli
[ "$(id -u)" -eq 0 ] || die "lancialo con sudo:  sudo $0 /dev/sdX"
[ "$(uname -m)" = "x86_64" ] || die "questo PC non è x86_64: non posso eseguire il chroot amd64"
[ -n "$DISK" ] || die "indica il disco, per esempio:  sudo $0 /dev/sdc"
[ -b "$DISK" ] || die "$DISK non esiste"
[ "$(lsblk -dno TYPE "$DISK")" = "disk" ] || die "$DISK non è un disco intero (serve /dev/sdX, non /dev/sdX1)"
[ "$(lsblk -dno TRAN "$DISK" | tr -d ' ')" = "usb" ] || die "$DISK non è collegato via USB: per sicurezza mi fermo"
if [ -n "$(lsblk -nro MOUNTPOINT "$DISK" | tr -d '[:space:]')" ]; then
  lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT "$DISK"
  die "qualche partizione di $DISK è montata (o è swap). Smontala (\"Espelli\" nel file manager,
senza staccare il cavo) e rilancia. Se è rimasta montata da un tentativo precedente:
  sudo umount -R $TARGET"
fi
mountpoint -q "$TARGET" 2>/dev/null && die "$TARGET è già in uso: sudo umount -R $TARGET"

MODEL="$(lsblk -dno MODEL "$DISK" | sed 's/ *$//')"
SIZE="$(lsblk -dno SIZE "$DISK" | tr -d ' ')"
echo
echo "Disco scelto:  $DISK   modello: $MODEL   dimensione: $SIZE"
lsblk -o NAME,SIZE,FSTYPE,LABEL "$DISK"
echo
echo "TUTTO il contenuto di questo disco verrà cancellato in modo definitivo."
read -r -p "Per continuare scrivi CANCELLA (in maiuscolo): " ANSWER
[ "$ANSWER" = "CANCELLA" ] || die "annullato, non ho toccato niente"

# da qui in poi tutto l'output va anche nel log
: > "$LOG"
[ -n "${SUDO_USER:-}" ] && chown "$SUDO_USER": "$LOG"
exec > >(tee -a "$LOG") 2>&1
echo "Avvio: $(date)   disco: $DISK ($MODEL, $SIZE)"

# ---------------------------------------------------------------- pulizia garantita
cleanup() {
  set +e
  if [ -d "$TARGET" ]; then
    # termina eventuali processi rimasti dentro il chroot
    for p in /proc/[0-9]*; do
      [ "$(readlink "$p/root" 2>/dev/null)" = "$TARGET" ] && kill "${p#/proc/}" 2>/dev/null
    done
    sleep 1
    rm -f "$TARGET/usr/sbin/policy-rc.d" 2>/dev/null
    sync
    umount -R "$TARGET" 2>/dev/null || { sleep 2; umount -R -l "$TARGET" 2>/dev/null; }
    rmdir "$TARGET" 2>/dev/null
  fi
  [ -n "$WORK" ] && rm -rf "$WORK"
}
trap cleanup EXIT
trap 'echo; echo "Interrotto."; exit 130' INT TERM

in_chroot() {
  chroot "$TARGET" /usr/bin/env -i HOME=/root TERM="${TERM:-linux}" LANG=C.UTF-8 \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    DEBIAN_FRONTEND=noninteractive "$@"
}

# ---------------------------------------------------------------- 0. strumenti temporanei
say "Scarico debootstrap e le chiavi Debian in una cartella temporanea (niente viene installato)"
WORK="$(mktemp -d /tmp/tvbox-prep.XXXXXX)"
cd "$WORK"
curl -fsSL "$MIRROR_HTTPS/dists/$SUITE/main/binary-all/Packages.xz" -o Packages.xz
xz -dc Packages.xz > Packages
fetch_deb() {   # scarica un pacchetto e ne controlla lo SHA256 indicato dall'archivio
  local pkg="$1" file sum
  file="$(awk -v p="$pkg" '$1=="Package:"{ok=($2==p)} ok&&$1=="Filename:"{print $2;exit}' Packages)"
  sum="$(awk -v p="$pkg" '$1=="Package:"{ok=($2==p)} ok&&$1=="SHA256:"{print $2;exit}' Packages)"
  [ -n "$file" ] && [ -n "$sum" ] || die "non trovo $pkg nell'archivio Debian"
  curl -fsSL "$MIRROR_HTTPS/$file" -o "$pkg.deb"
  echo "$sum  $pkg.deb" | sha256sum -c --quiet || die "checksum errato per $pkg"
  dpkg-deb -x "$pkg.deb" "$WORK/x"
}
mkdir -p "$WORK/x"
fetch_deb debian-archive-keyring
fetch_deb debootstrap
KEYRING="$WORK/x/usr/share/keyrings/debian-archive-keyring.gpg"
# controllo incrociato: firma dell'archivio verificata con le chiavi appena scaricate,
# e l'elenco pacchetti usato sopra deve corrispondere a quello firmato
curl -fsSL "$MIRROR_HTTPS/dists/$SUITE/InRelease" -o InRelease
gpgv --keyring "$KEYRING" InRelease 2>/dev/null || die "firma dell'archivio Debian non valida"
PSUM="$(awk '/^SHA256:/{s=1;next} /^[A-Za-z]/{s=0} s&&$3=="main/binary-all/Packages.xz"{print $1}' InRelease)"
echo "$PSUM  Packages.xz" | sha256sum -c --quiet || die "elenco pacchetti non corrispondente alla firma"
export DEBOOTSTRAP_DIR="$WORK/x/usr/share/debootstrap"
DEBOOTSTRAP="$WORK/x/usr/sbin/debootstrap"
cd /

# ---------------------------------------------------------------- 1. disco
say "1/12  Cancello $DISK e creo una partizione ext4 (tabella MBR)"
for p in $(lsblk -nrpo NAME,TYPE "$DISK" | awk '$2=="part"{print $1}'); do
  wipefs -a "$p" >/dev/null || true
done
wipefs -a "$DISK"
parted -s "$DISK" mklabel msdos mkpart primary ext4 1MiB 100% set 1 boot on
partprobe "$DISK" || true
udevadm settle
PART="$(lsblk -nrpo NAME,TYPE "$DISK" | awk '$2=="part"{print $1; exit}')"
[ -n "$PART" ] && [ -b "$PART" ] || die "non trovo la nuova partizione su $DISK"
mkfs.ext4 -F -L tvroot "$PART"
udevadm settle
sleep 2
# se il desktop l'ha montata da solo, la smonto
for m in $(findmnt -nro TARGET -S "$PART" || true); do umount "$m" || true; done
mkdir -p "$TARGET"
mount "$PART" "$TARGET"
mount --make-private "$TARGET"
ROOT_UUID="$(blkid -s UUID -o value "$PART")"

# ---------------------------------------------------------------- 2. sistema base
say "2/12  Installo il sistema base Debian 13 (qualche minuto)"
"$DEBOOTSTRAP" --arch=amd64 --components=main,contrib,non-free-firmware \
  --keyring="$KEYRING" "$SUITE" "$TARGET" "$MIRROR"

# ---------------------------------------------------------------- 3. chroot
say "3/12  Preparo il chroot"
mount --bind /dev "$TARGET/dev"
mount --bind /dev/pts "$TARGET/dev/pts"
mount -t proc proc "$TARGET/proc"
mount -t sysfs sysfs "$TARGET/sys"
mount -t tmpfs -o mode=0755,nosuid,nodev tmpfs "$TARGET/run"
rm -f "$TARGET/etc/resolv.conf"
if [ -s /run/systemd/resolve/resolv.conf ]; then
  cp /run/systemd/resolve/resolv.conf "$TARGET/etc/resolv.conf"
else
  cp -L /etc/resolv.conf "$TARGET/etc/resolv.conf"
fi
printf '#!/bin/sh\nexit 101\n' > "$TARGET/usr/sbin/policy-rc.d"
chmod 0755 "$TARGET/usr/sbin/policy-rc.d"

# ---------------------------------------------------------------- 4. configurazione
say "4/12  Configurazione di base (sorgenti, fstab, nome, fuso, tastiera)"
cat > "$TARGET/etc/apt/sources.list" <<EOF
deb http://deb.debian.org/debian $SUITE main contrib non-free-firmware
deb http://deb.debian.org/debian $SUITE-updates main contrib non-free-firmware
deb http://security.debian.org/debian-security $SUITE-security main contrib non-free-firmware
EOF
cat > "$TARGET/etc/fstab" <<EOF
# <file system>  <mount point>  <type>  <options>  <dump>  <pass>
UUID=$ROOT_UUID  /  ext4  errors=remount-ro  0  1
EOF
echo tv > "$TARGET/etc/hostname"
cat > "$TARGET/etc/hosts" <<'EOF'
127.0.0.1	localhost
127.0.1.1	tv
::1		localhost ip6-localhost ip6-loopback
ff02::1		ip6-allnodes
ff02::2		ip6-allrouters
EOF
ln -sf /usr/share/zoneinfo/Europe/Rome "$TARGET/etc/localtime"
echo Europe/Rome > "$TARGET/etc/timezone"
cat > "$TARGET/etc/default/keyboard" <<'EOF'
XKBMODEL="pc105"
XKBLAYOUT="it"
XKBVARIANT=""
XKBOPTIONS=""
BACKSPACE="guess"
EOF

say "5/12  Pacchetti di sistema (kernel, GRUB, SSH, rete, lingua italiana)"
in_chroot apt-get update
in_chroot apt-get install -y --no-install-recommends locales tzdata
sed -i 's/^# *it_IT.UTF-8 UTF-8/it_IT.UTF-8 UTF-8/' "$TARGET/etc/locale.gen"
in_chroot locale-gen
in_chroot update-locale LANG=it_IT.UTF-8
in_chroot debconf-set-selections <<'EOF'
grub-pc grub-pc/install_devices_empty boolean true
grub-pc grub-pc/install_devices multiselect
keyboard-configuration keyboard-configuration/layoutcode string it
tzdata tzdata/Areas select Europe
tzdata tzdata/Zones/Europe select Rome
EOF
in_chroot apt-get install -y --no-install-recommends \
  linux-image-amd64 grub-pc console-setup openssh-server avahi-daemon libnss-mdns \
  sudo systemd-timesyncd ca-certificates nano less

# ---------------------------------------------------------------- 6. rete
say "6/12  Rete via cavo (DHCP)"
cat > "$TARGET/etc/systemd/network/20-wired.network" <<'EOF'
[Match]
Name=en* eth*

[Network]
DHCP=yes
EOF
in_chroot systemctl enable systemd-networkd

# ---------------------------------------------------------------- 7. utente admin
say "7/12  Utente amministratore 'admin' (per entrare con: ssh admin@tv.local)"
id_admin() { in_chroot id admin >/dev/null 2>&1; }
id_admin || in_chroot useradd -m -s /bin/bash -G sudo admin
in_chroot passwd -l root >/dev/null
echo "Scegli ora la password di 'admin' (non viene mostrata mentre la scrivi)."
until in_chroot passwd admin </dev/tty >/dev/tty 2>&1; do
  echo "Le password non coincidono o non sono valide: riprova." >/dev/tty
done

# ---------------------------------------------------------------- 8. tvbox
say "8/12  Installo tvbox (Chrome, launcher, telecomando)"
rm -rf "$TARGET/root/tvbox"
mkdir -p "$TARGET/root/tvbox"
tar -C "$SRC" --exclude=./prepare-disk.log -cf - . | tar -C "$TARGET/root/tvbox" -xf -
in_chroot bash /root/tvbox/install.sh

# ---------------------------------------------------------------- 9. GRUB
say "9/12  Installo GRUB (avvio BIOS) su $DISK"
in_chroot grub-install --target=i386-pc "$DISK"
in_chroot update-grub
grep -q "root=UUID=$ROOT_UUID" "$TARGET/boot/grub/grub.cfg" \
  || die "grub.cfg non usa root=UUID=$ROOT_UUID"

# ---------------------------------------------------------------- 10. primo avvio
say "10/12 Servizio del primo avvio (ricollega GRUB al disco interno del Mac mini)"
cat > "$TARGET/usr/local/sbin/tvbox-firstboot" <<'EOF'
#!/bin/sh
# Al primo avvio sul Mac mini: dice a grub-pc qual è il disco giusto (per nome stabile)
# e reinstalla GRUB, così gli aggiornamenti futuri non cercano il disco USB di allora.
set -eu
src="$(findmnt -no SOURCE /)"
disk="/dev/$(lsblk -no PKNAME "$src" | head -n1)"
dev=""
for l in /dev/disk/by-id/ata-*; do
  [ -e "$l" ] || continue
  case "$l" in *-part*) continue ;; esac
  if [ "$(readlink -f "$l")" = "$disk" ]; then dev="$l"; break; fi
done
[ -n "$dev" ] || dev="$disk"
echo "tvbox-firstboot: disco di avvio $dev"
printf 'grub-pc grub-pc/install_devices multiselect %s\ngrub-pc grub-pc/install_devices_empty boolean false\n' "$dev" \
  | debconf-set-selections
grub-install --target=i386-pc "$dev"
update-grub
touch /var/lib/tvbox-firstboot.done
EOF
chmod 0755 "$TARGET/usr/local/sbin/tvbox-firstboot"
cat > "$TARGET/etc/systemd/system/tvbox-firstboot.service" <<'EOF'
[Unit]
Description=tvbox: configura GRUB sul disco interno del Mac mini (primo avvio)
ConditionPathExists=!/var/lib/tvbox-firstboot.done
After=local-fs.target systemd-udevd.service

[Service]
Type=oneshot
ExecCondition=/bin/sh -c 'grep -q "^Macmini" /sys/class/dmi/id/product_name'
ExecStart=/usr/local/sbin/tvbox-firstboot

[Install]
WantedBy=multi-user.target
EOF
in_chroot systemctl enable tvbox-firstboot.service

# ---------------------------------------------------------------- 11. pulizia
say "11/12 DNS di sistema (systemd-resolved) e pulizia"
in_chroot apt-get install -y --no-install-recommends systemd-resolved
in_chroot systemctl enable systemd-resolved || true
in_chroot apt-get clean
rm -f "$TARGET/usr/sbin/policy-rc.d"
rm -rf "$TARGET/root/tvbox"
sync

# ---------------------------------------------------------------- 12. verifiche
say "12/12 Verifiche finali"
FAIL=0
check() { if eval "$2" >/dev/null 2>&1; then echo "  OK     $1"; else echo "  MANCA  $1"; FAIL=1; fi; }
check "kernel in /boot"                 "ls $TARGET/boot/vmlinuz-*"
check "initrd in /boot"                 "ls $TARGET/boot/initrd.img-*"
check "grub.cfg"                        "test -s $TARGET/boot/grub/grub.cfg"
check "google-chrome-stable installato" "in_chroot dpkg -s google-chrome-stable"
check "/opt/tvbox/tvd.py"               "test -f $TARGET/opt/tvbox/tvd.py"
check "/etc/tvbox/config.json"          "test -f $TARGET/etc/tvbox/config.json"
check "utente tv"                       "in_chroot id tv"
check "utente admin"                    "in_chroot id admin"
check "autologin su tty1"               "grep -q 'autologin tv' $TARGET/etc/systemd/system/getty@tty1.service.d/autologin.conf"
for s in ssh systemd-networkd mac-power-restore tvbox-firstboot; do
  check "servizio $s abilitato"         "in_chroot systemctl is-enabled $s"
done

echo
if [ "$FAIL" -eq 0 ]; then
  echo "Tutto pronto. Smonto il disco: quando lo script termina puoi spegnere e staccarlo."
else
  echo "Qualche verifica è fallita: incolla a Claude il file $LOG"
fi
echo "Fine: $(date)"
