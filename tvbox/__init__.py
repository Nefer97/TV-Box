"""tvbox — Smart TV per Mac mini: demone tvd suddiviso in moduli.
Requisiti e architettura: docs/REQUISITI.md, docs/ARCHITETTURA.md.

    util      utilità comuni (registro, scaricamenti, file JSON sicuri)
    prefs     preferenze dell'utente, in un unico file
    config    lettura e normalizzazione di config.json (tipi di servizio, identità)
    display   risoluzione dello schermo (xrandr)
    cdp       Chrome DevTools Protocol
    browser   avvio e sorveglianza di Chrome, script iniettati nelle pagine
    inputdev  tastiera e mouse virtuali (uinput)
    remote    lettura dell'Apple Remote -> tasti logici
    keys      stati della TV e tabella "tasto -> azione"
    session   cosa si sta guardando (canale, episodio, servizio, sito) e le sue regole
    tv        la TV: apre e chiude le visioni, schermo, sorveglianza di Chrome
    actions   azioni dei tasti (tasti veri, puntatore, video, navigazione assistita)
    layer     strato TV sopra le pagine: sipario, banner, volume, avvisi, prenotazione
    panel     pannello cambio canale (disegnato dallo strato TV)
    sleep     timer di spegnimento e schermo spento
    health    dirette che si riparano da sole
    channels  catalogo dei canali in diretta (Rai, Mediaset, Discovery)
    mediaset  catalogo Mediaset Infinity (fiction, serie, programmi, cartoni…)
    sc        StreamingCommunity: catalogo, episodi e accesso (connettore come mediaset)
    epg       palinsesti (Rai, Mediaset, Warner Bros. Discovery)
    wifi      Wi-Fi tramite wpa_cli
    sites     "I miei siti": indirizzi e loghi
    meteo     meteo Open-Meteo
    api       API HTTP per il launcher
    main      avvio
"""
VERSION = "4.2.0"
