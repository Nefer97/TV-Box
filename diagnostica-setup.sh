#!/bin/bash
# diagnostica-setup.sh — SUL MAC MINI, con sudo. Attiva la diagnostica dei blocchi:
#  * netconsole: i messaggi del kernel vanno in tempo reale via rete al PC (UDP 6666);
#  * tvbox-monitor: ogni 5 s scrive temperature, ventola, carico e memoria nel log del kernel
#    (quindi anche via netconsole);
#  * journald scrive su disco ogni 5 s invece che ogni 5 minuti.
# Per toglierla: sudo bash diagnostica-setup.sh rimuovi
set -euo pipefail
PC_IP="${PC_IP:-192.168.1.x}"
IFACE="$(ip route | awk '/^default/{print $5; exit}')"

if [ "${1:-}" = rimuovi ]; then
  systemctl disable --now tvbox-monitor.service 2>/dev/null || true
  rm -f /etc/systemd/system/tvbox-monitor.service /usr/local/sbin/tvbox-monitor \
        /etc/sysctl.d/90-tvbox-debug.conf /etc/systemd/journald.conf.d/90-tvbox-debug.conf
  modprobe -r netconsole 2>/dev/null || true
  systemctl daemon-reload; systemctl restart systemd-journald
  echo "Diagnostica rimossa."; exit 0
fi

cat > /etc/sysctl.d/90-tvbox-debug.conf <<'EOF'
# diagnostica blocchi: tutti i messaggi del kernel sulla console (=> netconsole), SysRq attivo
kernel.printk = 7 4 1 7
kernel.sysrq = 1
kernel.softlockup_all_cpu_backtrace = 1
EOF
sysctl -q --system

mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSyncIntervalSec=5s\n' > /etc/systemd/journald.conf.d/90-tvbox-debug.conf
systemctl restart systemd-journald

cat > /usr/local/sbin/tvbox-monitor <<'EOF'
#!/bin/sh
# Ogni 5 secondi: temperature, ventola, carico, memoria e processo più grosso -> log del kernel
while :; do
  t=$(cat /sys/class/hwmon/hwmon*/temp*_input 2>/dev/null | awk '{printf "%d ", $1/1000}')
  f=$(cat /sys/class/hwmon/hwmon*/fan*_input /sys/devices/platform/applesmc.768/fan*_input 2>/dev/null | tr '\n' ' ')
  l=$(cut -d' ' -f1-3 /proc/loadavg)
  m=$(awk '/MemAvailable/{a=$2} /SwapTotal/{st=$2} /SwapFree/{sf=$2} END{printf "memfree=%dMB swapused=%dMB", a/1024, (st-sf)/1024}' /proc/meminfo)
  p=$(ps -eo rss=,comm= --sort=-rss | awk 'NR==1{printf "%s=%dMB", $2, $1/1024}')
  echo "<5>tvmon: temp=[${t}] fan=[${f}] load=[$l] $m top=$p" > /dev/kmsg
  sleep 5
done
EOF
chmod 0755 /usr/local/sbin/tvbox-monitor

cat > /etc/systemd/system/tvbox-monitor.service <<EOF
[Unit]
Description=tvbox: diagnostica blocchi (netconsole + monitor)
Wants=network-online.target
After=network-online.target

[Service]
ExecStartPre=-/sbin/modprobe -r netconsole
ExecStartPre=/sbin/modprobe netconsole netconsole=@/$IFACE,6666@$PC_IP/
ExecStart=/usr/local/sbin/tvbox-monitor
Restart=always

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now tvbox-monitor.service
sleep 1
echo "<4>tvmon: TEST netconsole verso $PC_IP" > /dev/kmsg
systemctl --no-pager --lines=0 status tvbox-monitor.service | head -4
echo "Diagnostica attiva (interfaccia $IFACE -> $PC_IP:6666)."
