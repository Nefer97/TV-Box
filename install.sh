#!/bin/bash
# Installa "tvbox" su un Debian 13 (trixie) amd64 minimale (senza desktop).
# Uso:  sudo ./install.sh        (dalla cartella del progetto)
set -euo pipefail

TV_USER=tv
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/opt/tvbox

[ "$(id -u)" -eq 0 ] || { echo "Esegui come root (sudo ./install.sh)"; exit 1; }
[ "$(dpkg --print-architecture)" = "amd64" ] || {
  echo "Serve Debian amd64: Chrome e Widevine non esistono per Linux a 32 bit."; exit 1; }
grep -qw lm /proc/cpuinfo || { echo "CPU senza 64 bit (Core Duo): vedi la guida."; exit 1; }

echo "==> Pacchetti di base"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  xserver-xorg-core xserver-xorg-input-libinput xserver-xorg-legacy xinit \
  x11-xserver-utils matchbox-window-manager unclutter-xfixes \
  python3 python3-evdev python3-websocket \
  alsa-utils pciutils sudo curl gnupg ca-certificates \
  fonts-noto-core fonts-noto-color-emoji fonts-dejavu-core \
  zram-tools intel-microcode \
  wpasupplicant wireless-regdb iw

echo "==> Google Chrome (include il modulo Widevine)"
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
  | gpg --dearmor --yes -o /etc/apt/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
  > /etc/apt/sources.list.d/google-chrome.list
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y google-chrome-stable
install -d /etc/opt/chrome/policies/managed
install -m 0644 "$SRC/system/chrome-policy.json" /etc/opt/chrome/policies/managed/tvbox.json

echo "==> Utente $TV_USER"
id "$TV_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$TV_USER"
for g in audio video input render; do
  getent group "$g" >/dev/null && usermod -aG "$g" "$TV_USER"
done
install -m 0644 -o "$TV_USER" -g "$TV_USER" "$SRC/system/bash_profile" "/home/$TV_USER/.bash_profile"

echo "==> File del progetto in $DEST"
install -d "$DEST/launcher" "$DEST/system" /etc/tvbox
install -m 0755 "$SRC/tvd.py" "$DEST/tvd.py"
install -m 0644 "$SRC"/launcher/*.html "$SRC"/launcher/*.js "$DEST/launcher/"
install -d "$DEST/launcher/vendor"
install -m 0644 "$SRC"/launcher/vendor/* "$DEST/launcher/vendor/"
install -m 0755 "$SRC/system/xinitrc" "$DEST/system/xinitrc"
[ -f /etc/tvbox/config.json ] || install -m 0644 "$SRC/config.json" /etc/tvbox/config.json
[ -f /etc/tvbox/session.env ] || install -m 0644 "$SRC/system/session.env" /etc/tvbox/session.env

echo "==> Autologin su tty1"
install -d /etc/systemd/system/getty@tty1.service.d
install -m 0644 "$SRC/system/autologin.conf" /etc/systemd/system/getty@tty1.service.d/autologin.conf

echo "==> uinput (tasti virtuali) e permessi"
echo uinput > /etc/modules-load.d/tvbox.conf
install -m 0644 "$SRC/system/99-tvbox-uinput.rules" /etc/udev/rules.d/99-tvbox-uinput.rules
modprobe uinput || true
udevadm control --reload-rules && udevadm trigger || true
# X avviato dall'utente sul terminale, SENZA privilegi di root (via logind, serve -keeptty).
# Da root Xorg 21.1 apre /dev/vga_arbiter e sul GMA 950 del Mac mini va in crash
# (segfault in pci_device_vgaarb_*) appena un client si collega.
printf 'allowed_users=console\nneeds_root_rights=no\n' > /etc/X11/Xwrapper.config
install -d /etc/X11/xorg.conf.d
install -m 0644 "$SRC/system/20-tvbox-video.conf" /etc/X11/xorg.conf.d/20-tvbox-video.conf

echo "==> Wi-Fi (reti scelte da Impostazioni > Wi-Fi; il cavo ha la precedenza)"
install -m 0755 "$SRC/system/tvbox-wifi-prep" /usr/local/sbin/tvbox-wifi-prep
install -d /etc/systemd/system/wpa_supplicant@.service.d \
           /etc/systemd/system/systemd-networkd-wait-online.service.d \
           /etc/systemd/network/20-wired.network.d
install -m 0644 "$SRC/system/wpa_supplicant-tvbox.conf" /etc/systemd/system/wpa_supplicant@.service.d/tvbox.conf
install -m 0644 "$SRC/system/wait-online-any.conf" /etc/systemd/system/systemd-networkd-wait-online.service.d/tvbox-any.conf
install -m 0644 "$SRC/system/25-wireless.network" /etc/systemd/network/25-wireless.network
install -m 0644 "$SRC/system/wired-metric.conf" /etc/systemd/network/20-wired.network.d/tvbox-metric.conf
install -m 0644 "$SRC/system/80-tvbox-wifi.rules" /etc/udev/rules.d/80-tvbox-wifi.rules
# il wpa_supplicant "globale" (D-Bus) non serve: ogni scheda ha il suo wpa_supplicant@<scheda>
systemctl disable wpa_supplicant.service 2>/dev/null || true
usermod -aG netdev "$TV_USER"     # il launcher parla con wpa_supplicant (wpa_cli)

echo "==> Spegni/Riavvia dal telecomando"
install -m 0440 "$SRC/system/sudoers-tvbox" /etc/sudoers.d/tvbox
visudo -cf /etc/sudoers.d/tvbox

echo "==> Riaccensione automatica dopo blackout"
echo "==> riavvio automatico se il sistema si blocca"
install -d /etc/systemd/system.conf.d
install -m 0644 "$SRC/system/watchdog-tvbox.conf" /etc/systemd/system.conf.d/90-tvbox-watchdog.conf
install -m 0644 "$SRC/system/90-tvbox-autoreboot.conf" /etc/sysctl.d/90-tvbox-autoreboot.conf
install -m 0644 "$SRC/system/tvbox-reboot.conf" /etc/tmpfiles.d/tvbox-reboot.conf
systemd-tmpfiles --create /etc/tmpfiles.d/tvbox-reboot.conf || true
sysctl -q --system || true
systemctl daemon-reexec || true

install -m 0644 "$SRC/system/mac-power-restore.service" /etc/systemd/system/
systemctl daemon-reload 2>/dev/null || true
systemctl enable mac-power-restore.service

echo "==> Memoria compressa (zram)"
sed -i 's/^#\?ALGO=.*/ALGO=zstd/; s/^#\?PERCENT=.*/PERCENT=60/' /etc/default/zramswap || true
systemctl enable zramswap.service || true

echo "==> Avvio silenzioso"
if [ -f /etc/default/grub ]; then
  sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=1/' /etc/default/grub
  sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet loglevel=3 vt.global_cursor_default=0"/' /etc/default/grub
  update-grub || true
fi
systemctl set-default multi-user.target

echo
echo "Fatto. Riavvia con:  sudo reboot"
echo "Per tornare al terminale senza TV: crea /home/$TV_USER/NO_TV e riavvia."
