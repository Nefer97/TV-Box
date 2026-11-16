// cards.js — schede dei canali in diretta, scritte una volta sola.
// Script "classico" (non modulo): lo usa la home (launcher) e tvd lo inietta insieme al
// pannello sopra le dirette (strato TV, inject/layer.js). Lo stile è in css/cards.css.
//   TVCards.live({id, label, color}, {current, busy})  -> elemento .tvcard
//   TVCards.fill(card, programma)                       -> titolo, orario, barra, immagine
//   TVCards.action({k, ic, lbl, sub})                   -> scheda-azione (pannello)
(function () {
  if (window.TVCards) return;
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const hhmm = t => new Date(t).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' });
  const span = d => (d && d.start && d.end ? `${hhmm(d.start)} – ${hhmm(d.end)}` : '');
  const progress = (d, now) => (d && d.end > d.start
    ? Math.max(0, Math.min(100, ((now || Date.now()) - d.start) / (d.end - d.start) * 100)) : 0);

  function live(ch, opt) {
    opt = opt || {};
    const c = el('div', 'tvcard noimg');
    c.dataset.id = ch.id;
    c.dataset.label = ch.label;
    c.style.background = `linear-gradient(135deg, ${ch.color || '#334155'}, #0b1020)`;
    if (opt.current) c.classList.add('cur');
    if (opt.busy) c.classList.add('busy');
    c.appendChild(el('div', 'shade'));
    c.appendChild(el('div', 'ch', ch.label));
    c.appendChild(el('div', 'badge', opt.current ? 'IN VISIONE' : 'LIVE'));
    c.appendChild(el('div', 'prog', 'In diretta'));
    c.appendChild(el('div', 'time'));
    const bar = el('div', 'bar');
    bar.appendChild(el('i'));
    c.appendChild(bar);
    return c;
  }

  function fill(c, d, now) {
    if (!d || !d.title) return;
    c.querySelector('.prog').textContent = d.title;
    c.querySelector('.time').textContent = span(d);
    c.querySelector('.bar i').style.width = progress(d, now) + '%';
    if (d.image && c.dataset.img !== d.image) {
      c.dataset.img = d.image;
      c.style.backgroundImage = `url("${d.image.replace(/"/g, '%22')}")`;
      c.classList.remove('noimg');
    }
  }

  function action(a) {
    const c = el('div', 'tvcard act ' + (a.k || ''));
    c.appendChild(el('div', 'shade'));
    c.appendChild(el('div', 'ic', a.ic));
    c.appendChild(el('div', 'lbl', a.lbl));
    c.appendChild(el('div', 'sub', a.sub || ''));
    return c;
  }

  window.TVCards = { live, fill, action, hhmm, span, progress };
})();
