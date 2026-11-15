// shield.js — "meno pubblicità e popup" per i siti scelti dall'utente (I miei siti).
// Iniettato da tvd in ogni pagina; agisce solo se tvd ha acceso window.__tvShield
// (lo fa quando apre uno dei tuoi siti). Insieme, tvd blocca i domini pubblicitari più noti.
//  * banner dei cookie: preme "rifiuta / continua senza accettare" (o li nasconde);
//  * finestre popup (window.open): bloccate;
//  * riquadri pubblicitari comuni: nascosti.
(function () {
  if (window.__shieldLoaded) return;
  window.__shieldLoaded = true;
  const on = () => !!window.__tvShield;

  // ---- popup: le finestre nuove non si aprono (tvd chiude anche le schede in più) ----
  const origOpen = window.open;
  window.open = function (...a) {
    if (on()) { try { console.log('[shield] popup bloccato', a[0]); } catch (e) {} return null; }
    return origOpen.apply(this, a);
  };

  // ---- banner dei cookie ----
  const KNOWN = ['#onetrust-reject-all-handler', '#didomi-notice-disagree-button',
    '.iubenda-cs-reject-btn', '#CybotCookiebotDialogBodyButtonDecline',
    '.qc-cmp2-summary-buttons button[mode=secondary]', '#truste-consent-required',
    'button.sp_choice_type_REJECT_ALL', '[data-testid="uc-deny-all-button"]', '.cmpboxbtnno',
    '#cookiescript_reject', '.cky-btn-reject', '#tarteaucitronAllDenied2', '.fc-cta-do-not-consent'];
  const REJECT = /^(continua senza accettare|rifiuta( tutt[oi])?|non accetto|nega( tutt[oi])?|solo (cookie )?(tecnici|necessari)|reject( all)?|decline( all)?|deny( all)?|chiudi e rifiuta)$/i;
  const BANNER = '[id*=cookie i],[class*=cookie i],[id*=consent i],[class*=consent i],[id*=cmp i],[class*=cmp i],[id*=gdpr i],[class*=gdpr i],[aria-label*=cookie i],[role=dialog]';
  let done = false;
  function shown(el) { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; }
  function clickReject() {
    for (const s of KNOWN) {
      const b = document.querySelector(s);
      if (b && shown(b)) { b.click(); return true; }
    }
    // pulsanti con il testo esatto di un rifiuto: nel banner o in tutta la pagina
    // (molti banner stanno in un iframe a parte: questo script gira anche lì)
    const boxes = [...document.querySelectorAll(BANNER)];
    const scopes = boxes.length ? boxes.concat([document]) : [document];
    for (const box of scopes) {
      for (const b of box.querySelectorAll('button, a, [role=button], [class*=btn i], [class*=button i], [onclick]')) {
        const t = (b.innerText || b.textContent || '').trim().replace(/\s+/g, ' ');
        if (t.length < 40 && REJECT.test(t) && shown(b)) { b.click(); return true; }
      }
    }
    return false;
  }
  function tick(n) {
    if (!on() || done) return;
    if (clickReject()) { done = true; console.log('[shield] banner cookie rifiutato'); return; }
    if (n < 25) setTimeout(() => tick(n + 1), 1000);
  }

  // ---- riquadri pubblicitari comuni ----
  const ADS = 'ins.adsbygoogle,.adsbygoogle,[id^="google_ads"],[id^="div-gpt-ad"],iframe[src*="doubleclick"],' +
    'iframe[src*="googlesyndication"],[id*="taboola" i],[class*="taboola" i],[id*="outbrain" i],' +
    '[class*="outbrain" i],.OUTBRAIN,[data-ad-slot],[data-google-query-id],amp-ad,.ad-container,.ad-slot,' +
    '.banner-ad,.ads-banner,[id^="adv_"],[class^="adv-"]';
  function hideAds() {
    if (!on()) return;
    const st = document.createElement('style');
    st.textContent = ADS + '{display:none!important}';
    (document.head || document.documentElement).appendChild(st);
  }

  function start() { if (!on()) return; hideAds(); tick(0); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
