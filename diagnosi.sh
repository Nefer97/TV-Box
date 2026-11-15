#!/bin/bash
# diagnosi.sh — raccoglie informazioni sullo schermo nero. Solo lettura: non modifica niente.
# Si esegue SUL MAC MINI con sudo (vedi istruzioni di Claude).
sec() { printf '\n===== %s\n' "$*"; }
sec "kernel e parametri";  uname -r; cat /proc/cmdline
sec "modello";             cat /sys/class/dmi/id/product_name
sec "scheda video";        lspci -nnk | grep -A3 -iE 'vga|display'
sec "uscite video (connected = TV vista)"
for s in /sys/class/drm/card*-*/status; do echo "$s: $(cat "$s")"; done
for m in /sys/class/drm/card*-*/modes; do [ -s "$m" ] && { echo "$m:"; head -5 "$m"; }; done
sec "processi della sessione TV"
ps -eo pid,user,etime,args | grep -E '[X]org|[c]hrome|[t]vd\.py|[m]atchbox|[a]getty|[x]init' | cut -c1-160
sec "servizi falliti";     systemctl --failed --no-pager
sec "primo avvio";         ls -l /var/lib/tvbox-firstboot.done 2>&1; journalctl -b -u tvbox-firstboot --no-pager | tail -8
sec "getty tty1";          journalctl -b -u getty@tty1 --no-pager | tail -10
sec "sessione X (.xorg-session.log)"; tail -40 /home/tv/.xorg-session.log 2>&1
sec "Xorg.0.log (errori/avvisi e modalità)"
for f in /var/log/Xorg.0.log /home/tv/.local/share/xorg/Xorg.0.log; do
  [ -f "$f" ] && { echo "-- $f"; grep -E '\(EE\)|\(WW\)|Output .* (connected|disconnected)|Modeline|driver|Using' "$f" | tail -40; }
done
sec "tvd (.tvbox.log)";    tail -40 /home/tv/.tvbox.log 2>&1
sec "chrome log";          tail -25 /home/tv/.config/tvbox-chrome/tvbox-chrome.log 2>&1
sec "errori di sistema";   journalctl -b -p err --no-pager | tail -25
sec "kernel video";        dmesg | grep -iE 'i915|drm|fbcon|gma' | tail -20
