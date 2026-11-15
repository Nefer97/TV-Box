// osd.js — banner del programma all'apertura di un canale (come sulle TV vere), per 6 secondi.
// tvd lo inietta quando il video è partito, insieme a js/cards.js e allo stile comune
// (window.__tvCardsCSS). Non riceve tasti: sparisce da solo.
//   __tvosd.show({label, color, now: {title, start, end, image}, next: {title, start}})
(function () {
  const V = 2;
  if (window.__tvosd && window.__tvosd.v === V) return;
  const C = window.TVCards;
  const CSS = `
  :host { all: initial; }
  .osd { position: fixed; left: 4vw; right: 4vw; bottom: 5vh; display: flex; gap: 2vw; align-items: center;
    padding: 2.2vh 2vw; border-radius: 2.6vh; font-family: var(--font); color: var(--fg);
    background: linear-gradient(90deg, rgba(11,16,32,.94), rgba(11,16,32,.82));
    box-shadow: 0 2vh 5vh rgba(0,0,0,.55); opacity: 0; transform: translateY(2vh);
    transition: opacity .35s ease, transform .35s ease; }
  .osd.in { opacity: 1; transform: none; }
  .pic { flex: 0 0 18vw; height: 10.1vw; border-radius: 1.6vh; background: #1e293b center/cover no-repeat; }
  .txt { flex: 1; min-width: 0; }
  .ch { font-size: 2.2vh; font-weight: 700; color: #ff6b6b; letter-spacing: .06em; text-transform: uppercase; }
  .ch .live { display: inline-block; margin-left: 1vw; font-size: 1.6vh; padding: .2vh .6vw; border-radius: .8vh;
    background: var(--live); color: #fff; letter-spacing: .08em; vertical-align: .2vh; }
  .title { font-size: 4vh; font-weight: 800; line-height: 1.12; margin-top: .4vh;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .time { display: flex; align-items: center; gap: 1.2vw; margin-top: 1.2vh; font-size: 2.2vh; color: var(--muted); }
  .bar { flex: 0 0 22vw; height: .7vh; border-radius: .4vh; background: rgba(255,255,255,.2); overflow: hidden; }
  .bar i { display: block; height: 100%; background: var(--live-bar); }
  .next { margin-top: 1.2vh; font-size: 2.1vh; color: #d5d9e4; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .next b { color: var(--muted); font-weight: 600; margin-right: .6vw; }`;

  let host = null, root = null, t = 0;
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };

  function hide() {
    const o = root && root.querySelector('.osd');
    if (o) o.classList.remove('in');
    setTimeout(() => { if (host) { try { host.hidePopover(); } catch (e) {} host.remove(); host = null; } }, 400);
  }

  function show(d, tries) {
    if (!d || !d.now || !d.now.title) return false;
    const p = window.__tvp;
    if (p && (p.panelShown ? p.panelShown() : p.isOpen())) return false;   // c'è già il pannello
    if (p && p.isOpen() && (tries || 0) < 12) {                          // c'è ancora il sipario
      setTimeout(() => show(d, (tries || 0) + 1), 400);
      return true;
    }
    if (host) host.remove();
    host = document.createElement('div');
    host.id = '__tvosd';
    host.setAttribute('popover', 'manual');
    host.style.cssText = 'all:initial;position:fixed;inset:auto 0 0 0;width:100vw;height:auto;margin:0;' +
      'padding:0;border:0;background:transparent;z-index:2147483646;overflow:visible';
    root = host.attachShadow({ mode: 'open' });
    root.appendChild(el('style', '', (window.__tvCardsCSS || '') + CSS));
    const o = el('div', 'osd');
    if (d.now.image) {
      const pic = el('div', 'pic');
      pic.style.backgroundImage = `url("${d.now.image.replace(/"/g, '%22')}")`;
      o.appendChild(pic);
    }
    const txt = el('div', 'txt'), ch = el('div', 'ch', d.label);
    ch.appendChild(el('span', 'live', 'LIVE'));
    txt.append(ch, el('div', 'title', d.now.title));
    const time = el('div', 'time', C.span(d.now)), bar = el('div', 'bar'), i = el('i');
    i.style.width = C.progress(d.now) + '%';
    bar.appendChild(i);
    if (d.now.start && d.now.end) time.appendChild(bar);
    txt.appendChild(time);
    if (d.next && d.next.title) {
      const n = el('div', 'next');
      n.append(el('b', '', 'Dopo, alle ' + C.hhmm(d.next.start)), document.createTextNode(d.next.title));
      txt.appendChild(n);
    }
    o.appendChild(txt);
    root.appendChild(o);
    (document.body || document.documentElement).appendChild(host);
    try { host.showPopover(); } catch (e) {}
    requestAnimationFrame(() => requestAnimationFrame(() => o.classList.add('in')));
    clearTimeout(t);
    t = setTimeout(hide, 6000);
    return true;
  }

  // sopra un video messo a schermo intero dopo il banner: lo rimetto in cima
  document.addEventListener('fullscreenchange', () => {
    if (host) { try { host.hidePopover(); host.showPopover(); } catch (e) {} }
  }, true);

  window.__tvosd = { v: V, show, hide };
})();
