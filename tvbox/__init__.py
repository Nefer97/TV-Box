"""tvbox — Smart TV per Mac mini: demone tvd suddiviso in moduli.

    util      utilità comuni (registro, scaricamenti, file JSON sicuri)
    prefs     preferenze dell'utente, in un unico file
    config    lettura e normalizzazione di config.json (tipi di servizio, identità)
    display   risoluzione dello schermo (xrandr)
    cdp       Chrome DevTools Protocol
    browser   avvio e sorveglianza di Chrome, script iniettati nelle pagine
    inputdev  tastiera e mouse virtuali (uinput)
    remote    lettura dell'Apple Remote -> tasti logici
    keys      stati della TV e tabella "tasto -> azione"
    tv        la TV: stato e azioni
    epg       palinsesti (Rai, Mediaset, Warner Bros. Discovery)
    wifi      Wi-Fi tramite wpa_cli
    sites     "I miei siti": indirizzi e loghi
    meteo     meteo Open-Meteo
    api       API HTTP per il launcher
    main      avvio
"""
VERSION = "3.0.0-dev"
