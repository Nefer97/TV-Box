# tvbox — requisiti

Cosa deve fare la TV e con quali vincoli. Ogni funzione nuova parte da qui: se cambia un
requisito si aggiorna prima questo file, poi il codice. Come è costruita: [ARCHITETTURA.md](ARCHITETTURA.md).

## 1. Il contesto (vincoli fissi)

| Vincolo | Conseguenza |
|---|---|
| **Mac mini 2007** (Core 2 Duo, 2–3 GB, GMA950 senza accelerazione video) | niente desktop, un solo Chrome a schermo intero; il video lo decodifica il processore → H.264 preferito, risoluzione più bassa durante i video |
| **Debian 13**, utente `tv` con accesso automatico, X senza window manager | tutto parte da `xinitrc`: Xorg → tvd → Chrome |
| **TV via VGA senza EDID** ("Smart Tech") | risoluzione fissa 1280×720 di serie, scelta da Impostazioni con prova di 15 s che torna indietro da sola |
| **Apple Remote, 6 tasti** (▲ ▼ ◄ ► OK MENU, ▶❚❚ sul modello di alluminio) | ogni funzione si usa con questi; pressioni lunghe (MENU = home, OK = puntatore) |
| **Chi la usa non è tecnico** | niente tastiera, niente finestre di sistema, niente messaggi in inglese; tutto in italiano e grande |
| **Servizi in streaming gratuiti** (Rai, Mediaset, Discovery, YouTube) | si aprono i loro siti/app ufficiali, travestendo Chrome da TV dove serve (HbbTV, YouTube TV) |
| **Rete di casa** (Wi-Fi o cavo) | palinsesti e cataloghi dalla rete; se mancano, la TV funziona lo stesso (schede senza programma) |

## 2. Cosa deve fare

### Accensione
- R1. All'accensione riparte dall'**ultimo canale** guardato (o dalla home, a scelta).
- R2. Se Chrome si chiude o si blocca, riparte da solo; se il sistema si blocca, il Mac si
  riavvia da solo (watchdog, riavvio dopo un kernel panic).

### Home
- R3. Riquadri grandi (RaiPlay, Mediaset Infinity, YouTube, Altri servizi, Impostazioni) e la
  fila dei **canali in diretta** con il programma in onda, l'immagine e l'avanzamento.
- R4. Le file scorrono tenendo la scheda scelta al centro e girano in cerchio.
- R5. Salvaschermo (orologio e meteo) dopo un po' di inattività; dopo tanto salvaschermo
  (di serie 1 ora) lo schermo si spegne; un tasto lo riaccende.

### Canali in diretta
- R6. Catalogo di canali Rai, Mediaset e Discovery; l'utente sceglie **quali** e in **che
  ordine** (Impostazioni → Home → Canali in diretta). Un solo modo per togliere un canale.
- R7. Aprendo un canale: **sipario** (fondo blu con "Apro Rai 1…") finché il video non va a
  tutto schermo, poi **banner** con programma, orario e successivo.
- R8. Mentre si guarda: ▲ ▼ volume (barra in alto a destra), ◄ ► e MENU aprono il **pannello
  cambio canale** sopra il video (stesse schede della home), che resta a schermo durante il cambio.
- R9. Nel pannello anche: Guida TV, timer di spegnimento, risoluzione durante i video,
  Impostazioni, Home.
- R10. Una diretta che si ferma da sola viene **riaperta** (al massimo 3 volte in 10 minuti);
  se il sito chiede di accedere lo si dice invece di riaprire.
- R11. **Guida TV**: per ogni canale scelto i programmi delle prossime ore.

### Mediaset Infinity
- R12. Sezione nostra con il catalogo gratuito: **fiction, serie TV, programmi TV, cartoni,
  documentari e approfondimento** (locandine, "Continua a guardare"),
  pagina della serie con stagioni ed episodi; l'episodio parte a tutto schermo con il sipario;
  MENU torna alla serie. Serve l'account (R17).
- R18. Un episodio lasciato a metà **riparte da dove si era arrivati** (Mediaset,
  StreamingCommunity, AnimeUnity). L'episodio parte **da solo a tutto schermo** anche quando il
  sito lo mette in un riquadro dentro la pagina.

### StreamingCommunity
- R16. Sezione nostra con il catalogo del sito: schede **HOME / SERIE TV / FILM**, ricerca con
  la tastiera a schermo, "Continua a guardare", righe per genere; pagina della serie come per
  Mediaset. Serve l'account (R17).

### AnimeUnity
- R19. Sezione nostra con il catalogo di anime del sito: schede **HOME / ANIME** (in corso, più
  popolari, righe per genere ordinate per visualizzazioni), ricerca, "Continua a guardare",
  pagina dell'anime con gli episodi; la descrizione si vede anche evidenziando un titolo in HOME.
  I titoli per adulti sono **nascosti di serie** e si possono rendere visibili da Impostazioni →
  Home e meteo. Nessun account.
- R21. Mentre si guarda un episodio (Mediaset, StreamingCommunity, AnimeUnity): **barra di
  avanzamento** (titolo, tempo, quanto manca) all'inizio, in pausa (resta finché si è in pausa)
  e a ogni salto; negli ultimi 40 s il riquadro **"Episodio successivo"** (OK lo apre); finito
  l'episodio il successivo **parte da solo** dopo 10 s (MENU per non farlo). Dopo l'ultimo
  della stagione, il primo della stagione dopo.
- R20. MENU da una sezione (Mediaset, StreamingCommunity, AnimeUnity) torna **dove era il
  riquadro** da cui la si è aperta (home o Altri servizi), anche dopo un episodio.

### Accesso agli account
- R17. Mediaset e StreamingCommunity **chiedono l'accesso** entrando nella sezione: una
  schermata di tvbox (stile della home) con utente/email e password scritti con la tastiera a
  schermo. Il sito **non si vede**: l'accesso lo fa la TV. La password **non si salva**; resta
  la sessione del sito, quindi la schermata non torna finché non si esce. Se il sito chiede un
  controllo "non sono un robot", la TV lo dice e apre il sito solo per quella volta.
  Impostazioni → Rete e assistenza mostra chi è collegato e permette di uscire.

### Altri servizi e siti
- R13. Servizi web (La7, Pluto TV, Radio Rai, discovery+, …) e **I miei siti** scelti
  dall'utente, con navigazione assistita (riquadro giallo), tastiera a schermo, puntatore
  (tieni premuto OK), vista "telefono" e protezione da pubblicità e finestre.

### Impostazioni
- R14. Quattro gruppi: Immagine e audio · Accensione e spegnimento · Home e meteo · Rete e
  assistenza (con gli account, R17). In fondo, come nella home, solo i tasti che non si
  indovinano (niente spiegazioni lunghe).
- R15. Risoluzione con prova sicura; Wi-Fi da telecomando; riavvio e spegnimento. In alto a
  destra la rete usata davvero (Wi-Fi o cavo).

## 3. Requisiti di qualità

- Q1. **Mai una schermata vuota o bianca senza spiegazione**: durante i caricamenti c'è il
  sipario o un messaggio.
- Q2. **Un tasto = una azione**: niente ripetizioni non volute (antirimbalzo), risposta sotto
  il decimo di secondo.
- Q3. Tutto ciò che compare sopra le pagine (pannello, sipario, banner, volume, avvisi) ha
  **lo stesso stile della home** e sta sopra anche al video a schermo intero.
- Q4. Un file di preferenze rovinato o un sito che cambia **non bloccano la TV**.
- Q5. Ogni aggiornamento passa le **prove automatiche** sul PC prima di arrivare alla TV e si
  può **tornare indietro** con un comando.
- Q6. Sul PC di sviluppo non si installa niente; le prove usano Chromium senza schermo.

## 4. Fuori dai requisiti (scelte fatte)

- Telecomando dal telefono: non voluto.
- Servizi a pagamento: possono funzionare (Netflix sperimentale) ma non sono garantiti.
- Accesso con Google o Facebook: non si fa dentro la TV (Google non permette che un programma
  scriva le credenziali al posto dell'utente); gli account usano email e password.
- Il controllo "non sono un robot" non si aggira mai: lo si completa sul sito (R17).
- Il lampo bianco passando da Rai a Mediaset è attenuato (fondo blu), non eliminato del tutto.
