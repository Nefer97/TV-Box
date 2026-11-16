// helper.js — iniettato in ogni pagina prima degli script del sito (window.__tv).
// Trova il video principale, pausa/salti, schermo intero (anche dopo la pubblicità),
// avvio automatico delle dirette e piccoli avvisi (toast).
(() => {
  if (window.__tv) return;
  const T = {};
  // il video principale: quello che sta davvero andando con l'audio, poi quello che va
  // (anche muto), poi il più grande. Conta perché alcuni siti (Mediaset) cambiano elemento
  // video durante la diretta: quello vecchio, fermo, resterebbe allargato e lo schermo nero.
  T.main = () => {
    const all = [...document.querySelectorAll('video')];
    const going = v => !v.paused && !v.ended && v.readyState >= 2;
    const pools = [all.filter(v => going(v) && !v.muted), all.filter(going), all];
    for (const pool of pools) {
      let best = null, ba = 0;
      for (const v of pool) {
        const r = v.getBoundingClientRect(), a = r.width * r.height;
        if (a > ba) { ba = a; best = v; }
      }
      if (best) return best;
    }
    return null;
  };
  T.area = v => { const r = v.getBoundingClientRect();
                  return (r.width * r.height) / Math.max(1, innerWidth * innerHeight); };
  T.isPlayer = () => {
    const fs = document.fullscreenElement;
    if (fs) return !!(fs.tagName === 'VIDEO' || fs.querySelector('video'));
    if (document.documentElement.classList.contains('__tvmaxed')) return true;
    const v = T.main();
    return !!(v && v.readyState >= 2 && T.area(v) > 0.6);
  };
  T.toast = (msg) => {
    try {
      let d = document.getElementById('__tvtoast');
      if (!d) {
        d = document.createElement('div'); d.id = '__tvtoast';
        // stesso stile degli altri riquadri della TV (pannello, banner, volume)
        d.style.cssText = 'position:fixed;left:50%;bottom:9vh;transform:translateX(-50%);' +
          'z-index:2147483647;background:rgba(11,16,32,.9);color:#f4f6fb;' +
          'font:700 3.2vh/1.2 "Noto Sans","DejaVu Sans",sans-serif;padding:1.8vh 2.6vw;border-radius:2.4vh;' +
          'box-shadow:0 1.6vh 4vh rgba(0,0,0,.5);pointer-events:none;transition:opacity .25s;white-space:nowrap';
        (document.fullscreenElement && document.fullscreenElement.tagName !== 'VIDEO'
          ? document.fullscreenElement : document.documentElement).appendChild(d);
      }
      d.textContent = msg; d.style.opacity = '1';
      clearTimeout(T._tt); T._tt = setTimeout(() => d.style.opacity = '0', 1600);
    } catch (e) {}
  };
  T.toggle = () => {
    const v = T.main(); if (!v) return false;
    if (v.paused) { delete v.dataset.tvUserPaused; v.play().catch(() => {}); T.toast('▶  Riproduci'); }
    else { v.dataset.tvUserPaused = '1'; v.pause(); T.toast('❚❚  Pausa'); }   // pausa voluta: non è un blocco
    return true;
  };
  // stato del video per la sorveglianza di tvd (dirette che si fermano)
  T.health = () => {
    const v = T.main();
    if (!v) return { video: false };
    return { video: true, t: v.currentTime, paused: v.paused, user: !!v.dataset.tvUserPaused,
             ended: v.ended, ready: v.readyState };
  };
  // il sito sta chiedendo di accedere? (finestra in primo piano con "accedi", "login"…)
  T.loginWall = () => {
    for (const d of document.querySelectorAll('[role=dialog],[aria-modal=true],[class*=modal i],[class*=popup i],[class*=overlay i],[class*=login i]')) {
      const r = d.getBoundingClientRect();
      if (r.width < innerWidth * 0.2 || r.height < innerHeight * 0.15) continue;
      if (/\b(accedi|accesso|registrati|login|sign in)\b/i.test(d.innerText || '')) return true;
    }
    return false;
  };
  T.seek = (d) => {
    const v = T.main(); if (!v) return false;
    let t = v.currentTime + d; const s = v.seekable;
    if (s && s.length) t = Math.max(s.start(0), Math.min(s.end(s.length - 1) - 1, t));
    try { v.currentTime = t; } catch (e) {}
    T.toast((d > 0 ? '▶▶  +' : '◀◀  −') + Math.abs(d) + ' s'); return true;
  };
  T.cssMax = (v) => {
    if (!document.getElementById('__tvmaxstyle')) {
      const st = document.createElement('style'); st.id = '__tvmaxstyle';
      st.textContent = '.__tvmax{position:fixed!important;inset:0!important;width:100vw!important;' +
        'height:100vh!important;max-width:none!important;max-height:none!important;' +
        'z-index:2147483646!important;background:#000!important;object-fit:contain!important;}' +
        // i contenitori del video vengono in primo piano (niente della pagina può coprirlo)
        // e perdono gli effetti che taglierebbero un elemento "fisso"
        '.__tvmaxanc{z-index:2147483646!important;transform:none!important;filter:none!important;' +
        'contain:none!important;will-change:auto!important;overflow:visible!important}' +
        // tutto ciò che sta accanto al video nel player (comandi, titoli, copertine) sparisce:
        // con lo schermo intero vero non si vedrebbe
        '.__tvmaxanc>:not(.__tvmaxanc):not(.__tvmax){opacity:0!important;pointer-events:none!important}' +
        'html.__tvmaxed,html.__tvmaxed body{overflow:hidden!important;background:#000!important}';
      (document.head || document.documentElement).appendChild(st);
    }
    document.querySelectorAll('.__tvmaxanc').forEach(a => a.classList.remove('__tvmaxanc'));
    for (let a = v.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
      a.classList.add('__tvmaxanc');
    }
    v.classList.add('__tvmax'); document.documentElement.classList.add('__tvmaxed');
  };
  T.cssUnmax = () => {
    document.querySelectorAll('.__tvmax').forEach(x => x.classList.remove('__tvmax'));
    document.querySelectorAll('.__tvmaxanc').forEach(a => a.classList.remove('__tvmaxanc'));
    document.documentElement.classList.remove('__tvmaxed');
  };
  // lo schermo intero è già sul video giusto? (dopo la pubblicità il sito cambia video)
  T.fsOk = (v) => { const fs = document.fullscreenElement; return !!fs && (fs === v || fs.contains(v)); };
  // il video allargato occupa davvero tutta la finestra? (un contenitore con effetti grafici
  // può tagliare un elemento "fisso": allora si ripiega sullo schermo intero di Chrome).
  // Non si guarda cosa c'è sopra: i contenitori del video sono portati in primo piano, quindi
  // sopra possono stare solo pezzi del player stesso (comandi, sottotitoli).
  T.covers = (v) => {
    const r = v.getBoundingClientRect();
    return r.left <= 2 && r.top <= 2 && r.width >= innerWidth - 4 && r.height >= innerHeight - 4;
  };
  T.maxOk = (v) => T.fsOk(v) || (v.classList.contains('__tvmax') && T.covers(v));
  // Ingrandisce il video principale a tutta la finestra (Chrome è già a tutto schermo): così
  // non compare la scritta di Chrome "premi Esc per uscire dallo schermo intero".
  T.maximize = () => {
    const v = T.main(); if (!v) return false;
    if (T.maxOk(v)) return true;
    T.cssUnmax();                           // via l'allargamento da un altro video (pubblicità)
    if (document.fullscreenElement && !T.fsOk(v)) document.exitFullscreen().catch(() => {});
    T.cssMax(v);
    if (!T.covers(v)) {                     // riserva: schermo intero vero
      T.cssUnmax();
      try { const p = v.requestFullscreen(); if (p && p.catch) p.catch(() => T.cssMax(v)); }
      catch (e) { T.cssMax(v); }
    }
    return true;
  };
  T.exitFull = () => {
    const v = T.main();
    if (document.fullscreenElement) {
      if (v) v.dataset.tvNoAuto = '1';
      document.exitFullscreen().catch(() => {}); return true;
    }
    if (document.documentElement.classList.contains('__tvmaxed')) {
      if (v) v.dataset.tvNoAuto = '1';
      T.cssUnmax(); return true;
    }
    return false;
  };
  // Video "vero" che sta suonando: non muto (esclude anteprime), lungo o in diretta.
  T.autoCandidate = () => {
    const v = T.main();
    if (!v || T.maxOk(v) || v.dataset.tvNoAuto) return false;
    if (v.paused || v.muted || v.readyState < 3 || T.area(v) < 0.15) return false;
    const d = v.duration;
    if (!(d === Infinity || d > 90)) return false;
    if (d !== Infinity && v.currentTime < 2) return false;
    return true;
  };
  // Per i canali in diretta: fa partire il video con l'audio e lo ingrandisce.
  T.kick = () => {
    const v = T.main();
    if (!v || !(v.currentSrc || v.src || v.srcObject)) return false;
    v.muted = false; if (v.volume === 0) v.volume = 1;
    if (v.paused) v.play().catch(() => {});
    if (v.readyState < 2) return false;      // riprova al giro successivo
    return T.maximize();
  };
  window.__tv = T;
})();
