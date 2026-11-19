# Come lavorare su tvbox

Guida pratica per le operazioni di tutti i giorni, in due situazioni:

- **sul PC Linux**, seduto davanti (terminale o VS Code);
- **dal Mac in SSH** sul PC Linux.

I tre posti in gioco:

| Cosa | Dove |
|---|---|
| il progetto | PC Linux, `~/Scrivania/tvbox` (indirizzo in casa: `<IP-del-PC>`) |
| la TV | Mac mini, `tv.local`, utente `admin` (tvbox installato in `/opt/tvbox`) |
| la copia online | GitHub, `origin` |

---

## 0. Collegarsi (solo dal Mac)

Dal Terminale del Mac:

```bash
ssh <utente>@<IP-del-PC>
cd ~/Scrivania/tvbox
```

Se vuoi anche vedere il banco di prova nel browser del Mac (punto 3), collegati **con il tunnel**:

```bash
ssh -L 8799:127.0.0.1:8799 <utente>@<IP-del-PC>
```

---

## 1. La chiave SSH per la TV

Il deploy e i comandi verso la TV usano la chiave `~/.ssh/id_ed25519` del PC, che ha una
passphrase. Va "caricata" una volta per sessione, altrimenti ogni comando la richiede o fallisce
con `Permission denied` / `Could not open a connection to your authentication agent`.

**Sul PC (terminale o VS Code):**

```bash
export SSH_AUTH_SOCK=/run/user/1000/keyring/ssh
ssh-add ~/.ssh/id_ed25519
```

**Dal Mac in SSH** (il portachiavi del desktop lì non c'è):

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
```

Controllo: `ssh-add -l` deve elencare la chiave. Prova: `ssh admin@tv.local hostname`.

---

## 2. Git: dove sono, cosa ho cambiato, salvare

```bash
git branch --show-current        # su che ramo sono
git status                       # file cambiati (rosso) e pronti per il commit (verde)
git diff                         # le righe cambiate
git log --oneline -5             # gli ultimi commit
```

Salvare e mandare su GitHub:

```bash
git add <file> <file> ...        # meglio nominare i file uno per uno
git commit -m "Parte: cosa cambia, in poche parole"
git push
```

- Primo push di un ramo nuovo: `git push --set-upstream origin <ramo>`.
- Nome con parentesi o spazi: tra virgolette, `git add "tvbox/mio(copia).py"`.
- Cartelle vuote: git non le salva; mettici un file vuoto `.gitkeep`.
- Messaggio lungo: `git commit` senza `-m`; prima riga breve, riga vuota, poi i dettagli.

Mettere da parte e riprendere (senza perdere niente):

```bash
git stash push -m "descrizione" -- <file>     # mette da parte le modifiche di quei file
git stash list
git stash pop                                  # le riprende
git revert <commit>                            # annulla un commit già su GitHub (ne aggiunge uno opposto)
```

---

## 3. Provare sul PC prima della TV

**Prove automatiche** (le stesse che fa il deploy):

```bash
python3 -m unittest discover -s tests -q      # prove del codice Python, qualche secondo
bash tools/uitest.sh                            # grafica + dialogo tvd ↔ Chrome, qualche minuto
```

Foto delle prove della grafica: `/tmp/tvbox-uitest/`. Le prove "foto della serie sullo sfondo" e
"logo della serie" di Mediaset scaricano immagini da internet: se falliscono una volta, rilancia.

**Banco di prova** (launcher vero, TV finta):

```bash
python3 tools/uitest/server.py 8799
```

- sul PC: apri `http://127.0.0.1:8799/`;
- dal Mac: collegato con il tunnel del punto 0, apri `http://127.0.0.1:8799/` nel browser del Mac.

Tastiera come il telecomando: frecce, Invio = OK, Esc = MENU. Ctrl+C per fermarlo. Non si vedono
le cose gestite da tvd (MENU tenuto premuto, tasti nei video, ripresa degli episodi).

---

## 4. Deploy sulla TV

Dalla cartella del progetto, con la chiave caricata (punto 1):

```bash
./deploy.sh                        # prove, copia, installazione, riavvio di tvd
./deploy.sh --no-ui                # senza le prove della grafica (es. Mediaset lento)
./deploy.sh --rollback             # torna alla versione installata prima
TV_HOST=192.168.1.x ./deploy.sh  # se tv.local non risponde
```

Chiede la password di `admin` sulla TV. **Spedisce i file così come sono nella cartella**, anche
quelli non salvati in un commit: prima controlla il ramo (`git branch --show-current`) e
`git status`.

Una cartella nuova (oltre a `tvbox`, `launcher`, `system`) arriva sulla TV solo se la aggiungi
sia in `deploy.sh` (elenco del `tar`) sia in `install.sh` (`install_app`).

---

## 5. Guardare la TV da lontano

**Il registro di tvd** (cosa è successo, errori):

```bash
ssh admin@tv.local 'grep -a -v rilasciata /var/log/tvbox/tvd.log | tail -20'
```

**È davvero la versione nuova?** Cerca una parola introdotta di recente, per esempio:

```bash
ssh admin@tv.local 'grep -c resume_point /opt/tvbox/tvbox/tv.py'     # 0 = versione vecchia
```

**Lo schermo della TV in Chrome DevTools** (immagine a scatti, senza audio, ma cliccabile):

- sul PC:

  ```bash
  ssh -N -L 9222:127.0.0.1:9222 admin@tv.local
  ```

  poi in Chromium `chrome://inspect` → *Configure…* → `localhost:9222` → *inspect* sulla pagina,
  e l'icona "Toggle screencast" in alto a sinistra;
- dal Mac (serve Chrome sul Mac): collegati al PC con
  `ssh -L 9222:127.0.0.1:9222 <utente>@<IP-del-PC>`, lì lancia il comando del PC qui sopra, poi
  sul Mac `chrome://inspect` come sopra.

HOME e MENU tenuto premuto passano solo dal telecomando vero.

---

## 6. Problemi frequenti

| Messaggio | Cosa fare |
|---|---|
| `Could not open a connection to your authentication agent` | punto 1 (`export SSH_AUTH_SOCK=…` sul PC, `eval "$(ssh-agent -s)"` dal Mac) |
| `Permission denied (publickey,password)` verso `tv.local` | chiave non caricata: `ssh-add ~/.ssh/id_ed25519` |
| `il branch corrente … non ha alcun branch upstream` | `git push --set-upstream origin <ramo>` |
| `non è stato aggiunto nulla al commit` | i file vanno prima aggiunti con `git add` |
| deploy fermo su "Prove della grafica fallite" (Mediaset) | rilancia, o `./deploy.sh --no-ui` |
| sulla TV qualcosa non va dopo un deploy | `./deploy.sh --rollback` |
