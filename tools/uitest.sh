#!/bin/bash
# uitest.sh — prove della grafica sul PC: launcher vero + API vere (TV finta) in Chromium senza
# schermo. Serve internet (palinsesti, catalogo Mediaset) e Chromium + Node già presenti:
# non installa niente. Se mancano, avvisa e non blocca.
#   bash tools/uitest.sh            (le foto restano in /tmp/tvbox-uitest)
set -u
cd "$(dirname "$0")/.."
CHROME=$(command -v chromium || command -v chromium-browser || command -v google-chrome || echo /snap/bin/chromium)
if [ ! -x "$CHROME" ] || ! command -v node >/dev/null; then
  echo "prove della grafica saltate: servono Chromium e Node sul PC"; exit 0
fi
SRV=8799; CDP=9333
OUT=/tmp/tvbox-uitest; mkdir -p "$OUT"
PROFILE="$HOME/snap/chromium/common/tvbox-uitest"; mkdir -p "$PROFILE"
python3 tools/uitest/server.py $SRV >"$OUT/server.log" 2>&1 &
SPID=$!
"$CHROME" --headless=new --remote-debugging-port=$CDP --user-data-dir="$PROFILE" \
  --window-size=1280,720 --no-first-run about:blank >"$OUT/chrome.log" 2>&1 &
CPID=$!
trap 'kill $SPID $CPID 2>/dev/null' EXIT
for _ in $(seq 30); do
  curl -s -o /dev/null "http://127.0.0.1:$CDP/json/version" && curl -s -o /dev/null "http://127.0.0.1:$SRV/" && break
  sleep 0.5
done
node tools/uitest/check.mjs $CDP $SRV "$OUT"
