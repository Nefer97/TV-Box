// osk.js — tastiera a schermo per il telecomando.
// Funziona nel launcher e (iniettata da tvd) dentro i siti: tutto sta in uno shadow DOM,
// quindi gli stili del sito non la toccano. Uso:
//   __osk.open({ title: 'Password', value: '', onDone: v => ..., onCancel: () => ... })
// Frecce = muovi, OK = premi il tasto, MENU (Esc) = annulla.
(function () {
  if (window.__osk) return;

  const LAYERS = {
    abc: [
      [...'1234567890'],
      [...'qwertyuiop'],
      [...'asdfghjkl@'],
      ['⇧', ...'zxcvbnm', '.', '-'],
      ['?123', 'SPAZIO', '⌫', 'FATTO']
    ],
    sym: [
      [...'1234567890'],
      [...'!"#$%&/()='],
      [..."?'+*_:;,<>"],
      [...'[]{}\\|^~€£'],
      [...'àèéìòù`°§ç'],
      ['ABC', 'SPAZIO', '⌫', 'FATTO']
    ]
  };
  // tasti speciali (testo mostrato -> azione)
  const SPECIAL = { '⇧': 'shift', '?123': 'sym', 'ABC': 'abc', 'SPAZIO': 'space',
                    '⌫': 'del', 'FATTO': 'done' };

  const CSS = `
    :host { all: initial; }
    .wrap { position: fixed; inset: 0; z-index: 2147483647; display: flex; flex-direction: column;
      justify-content: flex-end; background: rgba(5,8,18,.55);
      font-family: "Noto Sans", "DejaVu Sans", sans-serif; }
    .panel { background: #141b33; color: #f4f6fb; padding: 3vh 4vw 4vh;
      box-shadow: 0 -1vh 4vh rgba(0,0,0,.5); }
    .title { font-size: 2.6vh; color: #9aa3b8; margin-bottom: 1vh; }
    .field { font-size: 4vh; font-weight: 600; background: rgba(255,255,255,.08); border-radius: 1.2vh;
      padding: 1.4vh 1.4vw; min-height: 7.5vh; margin-bottom: 2.4vh; white-space: pre; overflow: hidden;
      text-overflow: ellipsis; direction: ltr; }
    .field .caret { display: inline-block; width: .3vh; height: 4.4vh; background: #fff;
      vertical-align: middle; animation: blink 1s steps(1) infinite; }
    @keyframes blink { 50% { opacity: 0; } }
    .row { display: flex; gap: .8vw; margin-bottom: 1.1vh; justify-content: center; }
    .key { flex: 0 0 7.4vw; height: 7.6vh; display: flex; align-items: center; justify-content: center;
      font-size: 3.6vh; font-weight: 600; border-radius: 1.2vh; background: rgba(255,255,255,.1);
      color: #f4f6fb; cursor: pointer; user-select: none; transition: transform .08s; }
    .key.wide { flex: 0 0 16vw; font-size: 2.8vh; }
    .key.space { flex: 0 0 34vw; font-size: 2.6vh; }
    .key.on { background: #3b82f6; }
    .key.done { background: #16a34a; }
    .key.focus { background: #fff; color: #0b1020; transform: scale(1.08); }
    .hint { font-size: 2vh; color: #9aa3b8; margin-top: 1.4vh; text-align: center; }
  `;

  let host, root, st = null;

  function render() {
    const layer = LAYERS[st.layer];
    const rows = root.querySelector('.keys');
    rows.innerHTML = '';
    st.grid = layer.map((row, r) => {
      const div = document.createElement('div'); div.className = 'row';
      const keys = row.map((label, c) => {
        const k = document.createElement('div');
        const sp = SPECIAL[label];
        k.className = 'key' + (sp === 'space' ? ' space' : sp ? ' wide' : '') +
                      (sp === 'done' ? ' done' : '') + (sp === 'shift' && st.shift ? ' on' : '');
        k.textContent = sp === 'space' ? 'spazio' : (!sp && st.shift ? label.toUpperCase() : label);
        k.addEventListener('mousedown', e => e.preventDefault());
        k.addEventListener('click', e => { e.preventDefault(); e.stopPropagation();
          st.r = r; st.c = c; press(label); });
        div.appendChild(k);
        return k;
      });
      rows.appendChild(div);
      return keys;
    });
    st.r = Math.min(st.r, st.grid.length - 1);
    st.c = Math.min(st.c, st.grid[st.r].length - 1);
    paint();
  }

  function paint() {
    root.querySelectorAll('.key.focus').forEach(k => k.classList.remove('focus'));
    st.grid[st.r][st.c].classList.add('focus');
    const f = root.querySelector('.field');
    f.textContent = st.secret ? '•'.repeat(st.value.length) : st.value;
    const caret = document.createElement('span'); caret.className = 'caret'; f.appendChild(caret);
    f.scrollLeft = f.scrollWidth;
  }

  function moveFocus(dr, dc) {
    if (dc) {
      const n = st.grid[st.r].length;
      st.c = (st.c + dc + n) % n;
    } else {
      const cur = st.grid[st.r][st.c].getBoundingClientRect();
      const x = cur.left + cur.width / 2;
      st.r = (st.r + dr + st.grid.length) % st.grid.length;
      let best = 0, bd = Infinity;
      st.grid[st.r].forEach((k, i) => {
        const b = k.getBoundingClientRect(), d = Math.abs(b.left + b.width / 2 - x);
        if (d < bd) { bd = d; best = i; }
      });
      st.c = best;
    }
    paint();
  }

  function press(label) {
    const sp = SPECIAL[label];
    if (sp === 'shift') { st.shift = !st.shift; render(); return; }
    if (sp === 'sym' || sp === 'abc') { st.layer = sp; st.shift = false; render(); return; }
    if (sp === 'space') st.value += ' ';
    else if (sp === 'del') st.value = st.value.slice(0, -1);
    else if (sp === 'done') { finish(true); return; }
    else {
      st.value += st.shift ? label.toUpperCase() : label;
      if (st.shift) { st.shift = false; render(); return; }
    }
    if (st.onInput) try { st.onInput(st.value); } catch (e) {}
    paint();
  }

  function finish(ok) {
    const s = st; close();
    try { ok ? s.onDone && s.onDone(s.value) : s.onCancel && s.onCancel(); } catch (e) {}
  }

  function onKey(ev) {
    if (!st) return;
    const k = ev.key;
    if (k === 'ArrowUp') moveFocus(-1, 0);
    else if (k === 'ArrowDown') moveFocus(1, 0);
    else if (k === 'ArrowLeft') moveFocus(0, -1);
    else if (k === 'ArrowRight') moveFocus(0, 1);
    else if (k === 'Enter') press(LAYERS[st.layer][st.r][st.c]);
    else if (k === 'Escape') finish(false);
    else if (k === 'Backspace') press('⌫');
    else if (k.length === 1 && !ev.ctrlKey && !ev.altKey && !ev.metaKey) {   // tastiera vera
      st.value += k; paint();
    } else return;
    ev.preventDefault(); ev.stopImmediatePropagation();
  }

  function open(opts) {
    if (st) close();
    st = { title: opts.title || '', value: opts.value || '', secret: !!opts.secret,
           onDone: opts.onDone, onCancel: opts.onCancel, onInput: opts.onInput,
           layer: 'abc', shift: false, r: 1, c: 0, grid: [] };
    host = document.createElement('div');
    host.id = '__osk_host';
    root = host.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>${CSS}</style><div class="wrap"><div class="panel">
      <div class="title"></div><div class="field"></div><div class="keys"></div>
      <div class="hint">Frecce: muovi · OK: scrivi · MENU: annulla · FATTO: conferma</div>
      </div></div>`;
    root.querySelector('.title').textContent = st.title;
    root.querySelector('.wrap').addEventListener('mousedown', e => e.preventDefault());
    (document.body || document.documentElement).appendChild(host);
    render();
  }

  function close() {
    if (host) host.remove();
    host = root = null; st = null;
  }

  window.addEventListener('keydown', onKey, true);
  // tasto inviato da tvd (navigazione assistita nei siti): 'ArrowUp', 'Enter', ...
  function key(k) {
    onKey({ key: k, ctrlKey: false, altKey: false, metaKey: false,
            preventDefault() {}, stopImmediatePropagation() {} });
  }
  window.__osk = { open, close, key, isOpen: () => !!st, cancel: () => st && finish(false) };
})();
