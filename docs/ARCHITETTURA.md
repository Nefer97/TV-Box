# tvbox — architettura

Come è costruita tvbox (V6) e dove si mette mano per ogni tipo di modifica. Cosa deve fare:
[REQUISITI.md](REQUISITI.md).

## 1. I pezzi

```
 Apple Remote ──evdev──▶ tvd (Python, /opt/tvbox) ◀──HTTP /api──▶ launcher (la home: HTML/JS)
                           │                                           ▲
                           │ Chrome DevTools Protocol (127.0.0.1:9222)  │ http://127.0.0.1:8765/
                           ▼                                           │
                         Google Chrome a schermo intero (kiosk) ───────┘
                           └─ pagine dei servizi (RaiPlay, Mediaset…) + script di tvbox iniettati
```

- **tvd** è il "cervello": legge il telecomando, decide cosa fanno i tasti, apre i servizi in
  Chrome, disegna sopra le pagine, sorveglia Chrome e le dirette, serve il launcher e le API.
- **Chrome** è solo lo schermo: una scheda, comandata da tvd via CDP. Per lavori brevi
  (l'accesso a Mediaset) tvd apre a volte una seconda scheda **nascosta** (§9).
- **Il launcher** (home, Impostazioni, Guida TV, Mediaset…) è una pagina servita da tvd; quando
  è a schermo i tasti gli arrivano come tasti veri (tastiera virtuale uinput).

Avvio: `xinitrc` → Xorg → `tvd.py` → `tvbox.main` (configurazione, preferenze, TV, API,
telecomando) → Chrome.

## 2. tvd: fili e coda

| Filo | Cosa fa |
|---|---|
| lettore del telecomando (`remote.py`) | tasti fisici → tasti logici (antirimbalzo, ripetizioni, pressioni lunghe) |
| **worker** (`tv.worker`) | esegue **una azione alla volta** dalla coda (`tv.post`): tasti, aperture, riaperture |
| sorveglianza (`tv.watchdog`, ogni 2 s) | Chrome vivo? schermo intero automatico, salvaschermo, timer, salute del video, risoluzione nei video |
| server HTTP (`api.py`) | API del launcher; le azioni lunghe le mette in coda |
| fili brevi | avvio del video (`_kick_live`), banner, ritiro della prenotazione |

Regola: tutto ciò che cambia cosa c'è a schermo (aprire, chiudere, riaprire, spegnere) passa
dalla coda, così due azioni non si accavallano. I fili brevi e le richieste in coda controllano
di essere ancora sulla stessa visione (`self.session is sess`) prima di agire: una riapertura
automatica non scavalca il canale che l'utente ha appena scelto.

## 3. Un tasto, dall'inizio alla fine

```
remote.RemoteLogic ─▶ tv.dispatch(evento)
                        ├─ schermo spento?  → riaccende
                        ├─ keys.detect_mode(tv.context())     stato: LAUNCHER, PANEL, LIVE_PLAYER…
                        └─ keys.action_for(stato, tasto)      tabella KEYMAP → nome del metodo
                             └─ metodo della TV (actions.py, panel.py…)
```

Per cambiare cosa fa un tasto si cambia **una riga di `KEYMAP`** (`tvbox/keys.py`); per un
comportamento nuovo si aggiunge uno stato o un'azione, senza toccare gli altri.

## 4. La visione: cosa si sta guardando (`session.py`)

Fuori dalla home c'è sempre **una** visione (`tv.session`), che nasce da `tv.open(id)`,
`tv.open_episode(...)` o `tv.open_url(...)` e finisce con `tv.home()`. Il tipo decide le regole:

| | sipario | banner | sorveglianza | riapertura | ultimo canale | avvio audio |
|---|---|---|---|---|---|---|
| `channel` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ (web) |
| `episode` | ✔ | | ✔ | | | ✔ |
| `service`, `site` | | | | | | |

`tv.start(visione)` applica le regole in un posto solo: identità e blocchi del servizio,
prenotazione dello strato (sipario), navigazione, avvio del video, ultimo canale, banner.
Il **servizio** della visione (`session.service`) dice come si comporta la pagina (tipo,
identità, blocchi, vista telefono); episodi e siti hanno il loro, senza toccare l'elenco dei
servizi. Una nuova "cosa da guardare" = un tipo nuovo in `session.py` + la sua riga di prove.

## 5. Lo strato TV (`launcher/inject/layer.js` + `tvbox/layer.py`)

Tutto ciò che compare sopra le pagine dei servizi sta in **un solo elemento** (popover: sopra
anche al video a schermo intero; shadow DOM: lo stile del sito non lo tocca), con lo stile
della home (`css/tokens.css`, `css/cards.css`, `js/cards.js`):

| Pezzo | Chi lo chiede |
|---|---|
| sipario "Apro Rai 1…" | `tv.start` (prenotato), sparisce da solo quando il video va |
| pannello cambio canale | `panel.py` (MENU, ◄ ►); resta durante il cambio |
| banner del programma | `layer._banner` quando il video è partito |
| barra del volume | `osd_volume` |
| avviso | `tv.toast` (pausa, salti, sorveglianza, timer) |

Da tvd tutto passa da `self.layer("metodo", argomenti)`: se la pagina non ha ancora lo strato
glielo mette e poi chiama. Per la pagina che sta per nascere c'è `self.book(...)`: lo strato
viene registrato per il prossimo documento e nasce con la pagina, già blu e con il sipario
(niente lampo bianco); appena c'è, la prenotazione si ritira.

## 6. Script in ogni pagina (`browser.inject_scripts`)

| Script | Compito |
|---|---|
| `helper.js` (`__tv`) | video principale, pausa/salti, schermo intero senza la scritta di Chrome, stato per la sorveglianza, richiesta di accesso, pulsanti "Salta intro" / "Episodio successivo" |
| `h264.js` | chiede ai siti H.264 (il Mac lo decodifica meglio) |
| `osk.js` | tastiera a schermo nei campi di testo |
| `nav.js` (`__nav`) | navigazione assistita: il riquadro giallo; a fine fila preme la freccina dei caroselli (Netflix) |
| `shield.js` | cookie, finestre e riquadri pubblicitari (solo per i siti) |
| `hbbtv.js` + hls.js | simulatore HbbTV per le app per TV (solo se Chrome si presenta come TV) |

## 7. Dati: chi decide cosa

| Dove | Cosa | Chi lo scrive |
|---|---|---|
| `config.json` | servizi della home e di Altri servizi, sezioni, identità, tempi | chi installa |
| `tvbox/channels.py` | **catalogo** dei canali (indirizzi, sigle, palinsesti) | lo sviluppo; verificato da `tools/checklinks.py` |
| `prefs.json` | scelte dalla TV: quali canali e in che ordine, siti, meteo, schermo, riquadri nascosti, "Continua a guardare" (`ms_history`, `sc_history`), punto degli episodi, email Mediaset da mostrare (`ms_user`)… | la TV (`prefs.py`, con controllo dei valori e versioni del file: la 4 rinomina "mio" in "sc") |
| cookie di Chrome | **accesso** ai servizi con account (Mediaset, StreamingCommunity) | il sito, tramite tvd (§9); le password non si salvano mai |

Un canale si toglie dalla home **solo** da "Canali in diretta"; "Riquadri della home" vale per
gli altri riquadri.

## 8. Il launcher (`launcher/`)

Moduli ES in `js/`: `core.js` (API, stato, navigazione con le frecce), `home.js`, `settings.js`,
`lists.js` (Wi-Fi, siti, canali, riquadri), `guide.js`, `mediaset.js` e `sc.js` (i cataloghi,
§9), `login.js` (schermata di accesso, §9), `saver.js` (salvaschermo), `app.js` (pagine, titoli,
indietro, indirizzi `#guide`, `#ms:<serie>`, `#sc:<serie>`…).
`cards.js` è uno script classico perché lo usa anche lo strato TV.

## 9. Cataloghi e accesso agli account

Tre sezioni del launcher sono **cataloghi** costruiti da tvbox sopra un sito: righe di
locandine, pagina della serie con stagioni ed episodi, "Continua a guardare"; l'episodio si
apre a schermo (visione `episode`, MENU torna alla serie e riparte dal punto salvato).

| | Mediaset Infinity | StreamingCommunity | AnimeUnity |
|---|---|---|---|
| id del servizio, API, pagine | `mediaset`, `/api/mediaset`, `mediaset` / `msserie` | `sc`, `/api/sc`, `sc` / `scserie` | `au`, `/api/au`, `au` / `auserie` |
| dati del catalogo | `tvbox/mediaset.py`: feed pubblici di Mediaset | `tvbox/sc.py`: API e archivio del sito (`vendor/scuapi`) | `tvbox/au.py`: in alto il connettore (API e pagine del sito), in basso la classe `AU` |
| launcher | `launcher/js/mediaset.js` | `launcher/js/sc.js` | `launcher/js/au.js` (copia di `sc.js`, schede HOME / ANIME) |
| cosa si apre per un episodio | la pagina dell'episodio sul sito | il **player da solo** (sotto) | il **player da solo** (sotto) |
| accesso | obbligatorio | obbligatorio | nessuno (`LOGIN_REQUIRED = False`) |

**Il player da solo.** StreamingCommunity e AnimeUnity mettono il video in un riquadro di
vixcloud dentro la pagina dell'episodio: lì tvbox non lo vede (niente schermo intero, niente
punto di ripresa). `resolve_episode(url)` nel modulo del catalogo legge l'indirizzo del player
(StreamingCommunity: dal riquadro `/it/iframe/`, chiesto dichiarando di arrivare dalla pagina
dell'episodio; AnimeUnity: `embedUrl` nei dati della pagina) e `play_target` lo restituisce con
la provenienza da dichiarare. La visione `episode` ha allora `referrer` (passato a
`Page.navigate`: senza, vixcloud risponde 403) e `key` = indirizzo dell'episodio sul sito, sotto
cui si salva il punto di ripresa (l'indirizzo del player contiene un codice che scade). Se il
player non si trova si apre la pagina dell'episodio come prima.

**Accesso obbligatorio.** Senza account le due sezioni mostrano solo la **schermata di accesso**
di tvbox (`login.js`: riquadro del servizio, campi con la tastiera a schermo, pulsante Accedi;
`lockPage` nasconde il catalogo). Il sito non si vede: **l'accesso lo fa tvd** e la password non
si salva da nessuna parte. Ogni catalogo ha le stesse azioni:

| `/api/<id>?action=` | Cosa |
|---|---|
| `status` | `{required, logged, user}`: si entra solo con `logged` |
| `login&user=…&password=…` | accesso; `{ok}` oppure `{error}`; `{site: true}` se il sito vuole altro (captcha) |
| `logout` | esce (Impostazioni → Rete e assistenza → Account, una riga per servizio: `data-svc`) |
| `site` | solo Mediaset: il sito vero a schermo per completare l'accesso (`tv.open_login`) |

| | Mediaset | StreamingCommunity |
|---|---|---|
| come accede tvd | apre il sito in una **scheda nascosta** (`cdp.HiddenTab`) e chiama la libreria di accesso del sito (Gigya, `gigya.accounts.login`): cookie e sessione li imposta il sito stesso | invia il modulo di login del sito (Laravel + Inertia) come il browser, poi copia i cookie della sessione in Chrome (`Network.setCookie`) |
| collegati se | Chrome ha il cookie di Gigya `glt_*` | Chrome ha i cookie di sessione e il sito, interrogato, risponde con l'utente (controllo ogni 5 min) |
| tempo | 20–30 s (la pagina di Mediaset è pesante) | 1–2 s |

`cdp.HiddenTab`: scheda in sottofondo con una connessione DevTools sua; non riceve gli script di
tvbox, i suoi video non partono, `cdp.targets()` la ignora (la sorveglianza non la chiude come
popup e tvd non la scambia per la pagina principale) e si chiude da sola alla fine.

Gigya decide **in base al rischio** se chiedere il captcha: dal Chromium senza schermo del PC
lo chiede sempre, dal Chrome della TV finora no. Le prove di un accesso vero si fanno quindi
sulla TV; sul PC si prova solo il percorso con credenziali finte.

## 10. Le prove

| Livello | Cosa | Dove |
|---|---|---|
| logica | telecomando, tasti, configurazione, preferenze, palinsesti, Mediaset, visione, sorveglianza, accesso (stato, messaggi, pagina del sito) | `tests/` (senza Chrome) |
| grafica | home, Guida TV, Impostazioni, Canali, Riquadri, Mediaset con il telecomando simulato; il server di prova (`tools/uitest/server.py`) fa risultare Mediaset collegato, `UITEST_LOGGED_OUT=1` mostra la schermata di accesso | `tools/uitest/check.mjs` |
| dialogo tvd ↔ Chrome | la vera classe TV con canali finti: sipario, schermo intero, banner, volume, pannello, cambio canale, pausa, diretta ferma, episodio | `tools/uitest/tvtest.py` |
| mondo esterno | gli indirizzi di Rai, Mediaset e Discovery rispondono ancora | `tools/checklinks.py` |
| installazione | Debian 13 da zero in macchina virtuale (lenta, scalda il PC) | `tools/vmtest.sh` |

`deploy.sh` esegue i primi quattro prima di ogni installazione (il quarto solo come avviso).

## 11. Dove mettere mano

| Voglio… | File |
|---|---|
| un canale nuovo | `tvbox/channels.py` (+ `tools/checklinks.py` lo verifica da solo) |
| un servizio nuovo nella home | `config.json` (per player esigenti: `"player_control": "keys"`, `"hover": false`, vedi `tvbox/config.py`) |
| cambiare cosa fa un tasto | `tvbox/keys.py` (`KEYMAP`) |
| un riquadro nuovo sopra le pagine | un pezzo in `layer.js` + un metodo che chiama `self.layer(...)` |
| una regola nuova per dirette/episodi | `tvbox/session.py` + `tests/` |
| una preferenza nuova | `tvbox/prefs.py` (`DEFAULTS` e `_clean`) |
| una pagina nuova del launcher | `index.html` + un modulo in `launcher/js/` + `app.js` |
| un catalogo nuovo (come StreamingCommunity o AnimeUnity: il modello più semplice è `tvbox/au.py`) | `tvbox/<id>.py` (righe, serie, cronologia in `prefs.py`) + `def <id>(q)` in `api.py` + `launcher/js/<id>.js` + le due pagine in `index.html` (`page-<id>`, `page-<id>serie`) + `app.js` (titoli, MENU, `#<id>:<serie>`) + il servizio con `"page": "<id>"` in `config.json` |
| l'accesso a un servizio | `login_state` / `login` / `logout` nel modulo del catalogo + le azioni in `api.py` + `loginGate(...)` nella pagina + una riga `data-act="account" data-svc="<id>"` in `index.html` |

## 12. Rimasti come sono (scelte consapevoli)

- `osk.js`, `shield.js`, `hbbtv.js` vengono dalla V1: funzionano e non sono stati riscritti;
  non hanno prove automatiche proprie. `nav.js` è provato da `tvtest.py` su un catalogo finto
  (file di locandine con freccina, anteprime, player con "Salta intro").
- Le pagine delle Impostazioni sono in parte scritte in `index.html` e in parte generate in JS
  (elenchi): è voluto, le voci fisse restano leggibili nell'HTML.
