// helper.js — iniettato in ogni pagina prima degli script del sito (window.__tv).
// Trova il video principale, pausa/salti, schermo intero (anche dopo la pubblicità),
// avvio automatico delle dirette e piccoli avvisi (toast).
(() => {
  if (window.__tv) return;
  const T = {};
  T.main = () => {
    let best = null, ba = 0;
    for (const v of document.querySelectorAll('video')) {
      const r = v.getBoundingClientRect(), a = r.width * r.height;
      if (a > ba) { ba = a; best = v; }
    }
    return best;
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
        d.style.cssText = 'position:fixed;left:50%;bottom:8vh;transform:translateX(-50%);' +
          'z-index:2147483647;background:rgba(0,0,0,.82);color:#fff;font:600 34px/1.2 sans-serif;' +
          'padding:18px 36px;border-radius:18px;pointer-events:none;transition:opacity .3s';
        (document.fullscreenElement && document.fullscreenElement.tagName !== 'VIDEO'
          ? document.fullscreenElement : document.documentElement).appendChild(d);
      }
      d.textContent = msg; d.style.opacity = '1';
      clearTimeout(T._tt); T._tt = setTimeout(() => d.style.opacity = '0', 1600);
    } catch (e) {}
  };
  T.toggle = () => {
    const v = T.main(); if (!v) return false;
    if (v.paused) { v.play().catch(() => {}); T.toast('▶  Riproduci'); }
    else { v.pause(); T.toast('❚❚  Pausa'); }
    return true;
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
        'html.__tvmaxed,html.__tvmaxed body{overflow:hidden!important;background:#000!important}';
      document.head.appendChild(st);
    }
    v.classList.add('__tvmax'); document.documentElement.classList.add('__tvmaxed');
  };
  // lo schermo intero è già sul video giusto? (dopo la pubblicità il sito cambia video)
  T.fsOk = (v) => { const fs = document.fullscreenElement; return !!fs && (fs === v || fs.contains(v)); };
  T.maximize = () => {
    const v = T.main(); if (!v) return false;
    if (T.fsOk(v)) return true;
    const go = () => {
      try {
        const p = v.requestFullscreen();
        if (p && p.catch) p.catch(() => T.cssMax(v));
      } catch (e) { T.cssMax(v); }
    };
    if (document.fullscreenElement) document.exitFullscreen().then(go, go);   // era sulla pubblicità
    else go();
    return true;
  };
  T.exitFull = () => {
    const v = T.main();
    if (document.fullscreenElement) {
      if (v) v.dataset.tvNoAuto = '1';
      document.exitFullscreen().catch(() => {}); return true;
    }
    if (document.documentElement.classList.contains('__tvmaxed')) {
      if (v) { v.dataset.tvNoAuto = '1'; v.classList.remove('__tvmax'); }
      document.documentElement.classList.remove('__tvmaxed'); return true;
    }
    return false;
  };
  // Video "vero" che sta suonando: non muto (esclude anteprime), lungo o in diretta.
  T.autoCandidate = () => {
    const v = T.main();
    if (!v || T.fsOk(v) || v.dataset.tvNoAuto) return false;
    if (document.documentElement.classList.contains('__tvmaxed')) return false;
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
