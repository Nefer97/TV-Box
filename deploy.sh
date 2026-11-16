#!/bin/bash
# deploy.sh — dal PC: prova, copia e installa la versione attuale sul Mac mini.
#
#   ./deploy.sh                 prove automatiche e della grafica, poi aggiornamento (chiede la password)
#   ./deploy.sh --no-ui         salta le prove della grafica (es. senza internet)
#   ./deploy.sh --rollback      torna alla versione installata prima
#   TV_HOST=192.168.1.x ./deploy.sh     se tv.local non risponde
#
# Sul PC non installa niente: usa solo ssh, scp, tar e python3 già presenti.
set -euo pipefail
cd "$(dirname "$0")"

HOST="${TV_HOST:-tv.local}"
SSH_OPTS=(-o HostKeyAlias=tv.local -o ConnectTimeout=8)
DIR=tvbox-deploy                      # cartella di appoggio nella home di admin sul Mac mini

remote() { ssh -t "${SSH_OPTS[@]}" "admin@$HOST" "$@"; }

if [ "${1:-}" = "--rollback" ]; then
  remote "sudo bash ~/$DIR/install.sh --rollback"
  exit
fi

echo "==> Prove automatiche"
python3 -m unittest discover -s tests -q

if [ "${1:-}" != "--no-ui" ]; then
  echo "==> Prove della grafica (Chromium sul PC)"
  bash tools/uitest.sh || { echo "Prove della grafica fallite: niente installazione (foto in /tmp/tvbox-uitest)"; exit 1; }
fi

echo "==> Pacchetto"
PKG=$(mktemp --suffix=.tgz)
trap 'rm -f "$PKG"' EXIT
tar czf "$PKG" --exclude=__pycache__ --exclude='*.pyc' \
  tvd.py tvbox launcher config.json system install.sh

echo "==> Copia su $HOST"
scp -q "${SSH_OPTS[@]}" "$PKG" "admin@$HOST:$DIR.tgz"

echo "==> Installazione (serve la password di admin)"
remote "rm -rf ~/$DIR && mkdir ~/$DIR && tar xzf ~/$DIR.tgz -C ~/$DIR && rm ~/$DIR.tgz && sudo bash ~/$DIR/install.sh --update"
