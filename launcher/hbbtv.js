// hbbtv.js — simula in Chrome le funzioni di un televisore HbbTV/OIPF, quanto basta perché
// le app "tasto rosso" (es. RaiPlay per TV) partano anche fuori da un televisore.
// Iniettato da tvd in ogni pagina insieme a hls.js; si attiva solo con lo user agent HbbTV
// (servizi con "hbbtv": true in config.json).
(function () {
  if (window.__hbbtv) return;
  const log = (...a) => { try { console.log('[hbbtv]', ...a); } catch (e) {} };

  // ---- codici tasto HbbTV (KeyEvent.VK_*) -------------------------------------------
  const VK = { VK_LEFT: 37, VK_UP: 38, VK_RIGHT: 39, VK_DOWN: 40, VK_ENTER: 13, VK_BACK: 461,
    VK_RED: 403, VK_GREEN: 404, VK_YELLOW: 405, VK_BLUE: 406,
    VK_PLAY: 415, VK_PAUSE: 19, VK_PLAY_PAUSE: 463, VK_STOP: 413,
    VK_FAST_FWD: 417, VK_REWIND: 412, VK_TRACK_NEXT: 425, VK_TRACK_PREV: 424,
    VK_0: 48, VK_1: 49, VK_2: 50, VK_3: 51, VK_4: 52, VK_5: 53, VK_6: 54, VK_7: 55, VK_8: 56, VK_9: 57,
    VK_INFO: 457, VK_TELETEXT: 459, VK_SUBTITLE: 460, VK_PAGE_UP: 33, VK_PAGE_DOWN: 34 };
  window.KeyEvent = window.KeyEvent || {};
  for (const k in VK) { window.KeyEvent[k] = VK[k]; try { window[k] = VK[k]; } catch (e) {} }

  // ---- oggetti OIPF -------------------------------------------------------------------
  const keyset = { RED: 0x1, GREEN: 0x2, YELLOW: 0x4, BLUE: 0x8, NAVIGATION: 0x10, VCR: 0x20,
    SCROLL: 0x40, INFO: 0x80, NUMERIC: 0x100, ALPHA: 0x200, OTHER: 0x400, value: 0x1ff,
    PLAY: 0x20, PAUSE: 0x20, STOP: 0x20, NEXT: 0x20, PREV: 0x20, FAST_FWD: 0x20, REWIND: 0x20,
    otherKeys: [], maximumValue: 0x7ff, maximumOtherKeys: [], supportsPointer: false,
    setValue(v, other) { this.value = v; if (other) this.otherKeys = other; return v; } };
  const channel = { channelType: 0, ccid: 'ccid:dvbt.0', dsd: '', idType: 12, onid: 318, tsid: 1,
    sid: 1, name: 'Rai 1', majorChannel: 1, minorChannel: 0, nid: 0 };
  const app = {
    privateData: { keyset, currentChannel: channel, getFreeMem: () => 256 * 1024 * 1024 },
    visible: true,
    show() { this.visible = true; return true; },
    hide() { this.visible = false; return true; },
    activate() {}, deactivate() {},
    createApplication(url) { log('createApplication', url); if (url) location.href = url; return app; },
    destroyApplication() { log('destroyApplication'); window.__tvHome && window.__tvHome(); },
    addEventListener() {}, removeEventListener() {}
  };
  const appMgr = {
    getOwnerApplication() { return app; },
    getChildApplications() { return []; },
    gc() {}, onLowMemory: null,
    addEventListener() {}, removeEventListener() {}
  };
  const config = {
    configuration: { preferredAudioLanguage: 'ita', preferredSubtitleLanguage: 'ita',
      preferredUILanguage: 'ita', countryId: 'ITA', regionId: 0, isPVRSupported: false },
    localSystem: { deviceID: 'tvbox', modelName: 'SmartTV2015', vendorName: 'Samsung',
      softwareVersion: '1490.3', hardwareVersion: '1', serialNumber: '0', volume: 100, mute: false },
    getText: () => '', setText() {}
  };
  const XMLCAP = '<profilelist><ui_profile name="OITF_HD_UIPROF+DVB_S+DVB_C+DVB_T+TRICKMODE">' +
    '<ext><parentalcontrol schemes="dvb-si">true</parentalcontrol></ext></ui_profile>' +
    '<drm DRMSystemID="urn:dvb:casystemid:19188">TS_PF</drm>' +
    '<video_profile name="MP4_AVC_HD_25_HEAAC" type="video/mp4"/>' +
    '<video_profile name="DASH_AVC_HD_25_HEAAC" type="application/dash+xml"/></profilelist>';
  const caps = {
    xmlCapabilities: new DOMParser().parseFromString(XMLCAP, 'text/xml'),
    extraSDVideoDecodes: 1, extraHDVideoDecodes: 1,
    hasCapability: () => true
  };

  // video/broadcast: non c'è il sintonizzatore. Simula un canale "fermo" (schermo nero)
  function broadcast(el) {
    own(el, {
      playState: 0, currentChannel: channel, fullScreen: false, data: '',
      bindToCurrentChannel() { this.playState = 2; fire(this, 'PlayStateChange'); return channel; },
      setChannel(ch) { this.currentChannel = ch || channel; this.playState = ch ? 2 : 0;
        fire(this, 'PlayStateChange'); fire(this, 'ChannelChangeSucceeded'); },
      prevChannel() {}, nextChannel() {},
      stop() { this.playState = 0; fire(this, 'PlayStateChange'); },
      release() { this.playState = 0; },
      setFullScreen(f) { this.fullScreen = !!f; },
      getChannelConfig() { return { channelList: Object.assign([channel], { getChannel: () => channel,
        getChannelByTriplet: () => channel, item: () => channel }) }; },
      createChannelObject: () => channel,
      getComponents: () => [], getCurrentActiveComponents: () => [], selectComponent() {},
      unselectComponent() {}, setVolume() {}, getVolume: () => 100
    });
  }
  // proprietà proprie dell'oggetto (non passa dai getter "pigri" del prototipo)
  function own(el, props) {
    for (const k of Object.keys(props))
      Object.defineProperty(el, k, { value: props[k], writable: true, configurable: true, enumerable: true });
    return el;
  }
  function fire(el, name) {
    const h = el['on' + name];
    try { if (typeof h === 'function') h.call(el, el.playState); } catch (e) {}
    try { el.dispatchEvent(new Event(name)); } catch (e) {}
  }

  // A/V control (video/mp4, HLS, DASH): l'<object> resta nascosto e un <video> HTML5 gli
  // sta esattamente sopra. Per l'HLS si usa hls.js (tvd lo inietta insieme a questo file).
  // playState OIPF: 0 fermo, 1 in riproduzione, 2 pausa, 3 connessione, 4 buffering, 5 finito, 6 errore
  function avControl(el) {
    if (el.__av) return;
    const v = document.createElement('video');
    v.setAttribute('playsinline', '');
    v.style.cssText = 'position:fixed;left:0;top:0;width:0;height:0;background:#000;' +
                      'object-fit:contain;pointer-events:none';
    el.__av = v;
    el.style.visibility = 'hidden';
    let hls = null, src = '', want = false, last = -1, failed = false;

    const place = () => {
      if (!el.isConnected) { if (v.isConnected) { teardown(); v.remove(); } return; }
      if (!v.isConnected || v.nextSibling !== el) el.parentNode.insertBefore(v, el);
      const cs = getComputedStyle(el);
      if (el.__fs) Object.assign(v.style, { left: '0', top: '0', width: '100vw', height: '100vh' });
      else {
        const r = el.getBoundingClientRect();
        Object.assign(v.style, { left: r.left + 'px', top: r.top + 'px',
                                 width: r.width + 'px', height: r.height + 'px' });
      }
      v.style.zIndex = cs.zIndex === 'auto' ? '0' : cs.zIndex;
    };
    setInterval(place, 500);

    const st = () => failed || v.error ? 6 : v.ended ? 5 :
      !want ? (v.currentTime > 0 ? 2 : 0) :
      v.paused ? (v.readyState < 3 ? 3 : 2) : v.readyState < 3 ? 4 : 1;
    const upd = () => {
      const s = st();
      if (s !== last) { last = s; el.playState = s; fire(el, 'PlayStateChange'); }
    };
    ['play', 'playing', 'pause', 'ended', 'error', 'waiting', 'canplay', 'loadedmetadata',
     'stalled', 'seeked'].forEach(e => v.addEventListener(e, upd));
    v.addEventListener('timeupdate', () => {
      const h = el.onPlayPositionChanged;
      if (typeof h === 'function') try { h.call(el, Math.round(v.currentTime * 1000)); } catch (e) {}
    });

    function teardown() {
      if (hls) { try { hls.destroy(); } catch (e) {} hls = null; }
      v.removeAttribute('src');
      try { v.load(); } catch (e) {}
    }
    function load(s) {
      s = s || '';
      if (s === src) return;
      src = s; failed = false; teardown();
      if (!s) return;
      place();
      const t = (el.getAttribute('type') || '').toLowerCase();
      const isHls = /mpegurl/.test(t) || /\.m3u8/i.test(s);
      // hls.js sempre: Chrome per Linux dichiara di saper leggere l'HLS ma poi non parte
      if (isHls && window.Hls && Hls.isSupported()) {
        // buffer corti: il Mac mini ha poca memoria
        hls = new Hls({ maxBufferLength: 20, maxMaxBufferLength: 30, backBufferLength: 10 });
        hls.on(Hls.Events.ERROR, (e, d) => {
          log('hls', d.type, d.details, d.fatal ? 'FATALE' : '');
          if (!d.fatal) return;
          if (d.type === Hls.Events.NETWORK_ERROR || d.type === 'networkError') hls.startLoad();
          else if (d.type === 'mediaError') hls.recoverMediaError();
          else { failed = true; upd(); }
        });
        hls.loadSource(s);
        hls.attachMedia(v);
      } else v.src = s;
      log('load', t, s.slice(0, 120));
    }
    el.__avLoad = () => { if (want) load(el.getAttribute('data')); };

    Object.defineProperties(el, {
      data: { get: () => src || el.getAttribute('data') || '',
              set: s => { load(s); }, configurable: true },
      playPosition: { get: () => Math.round(v.currentTime * 1000), configurable: true },
      playTime: { get: () => isFinite(v.duration) ? Math.round(v.duration * 1000) : 0, configurable: true },
      speed: { get: () => (want && !v.paused ? v.playbackRate : 0), configurable: true }
    });
    own(el, {
      playState: 0, error: 0, fullScreen: false,
      play(s) {
        if (s === undefined) s = 1;
        want = s !== 0;
        if (want && !src) load(el.getAttribute('data'));
        if (!want) v.pause();
        else { v.playbackRate = s > 0 ? Math.min(s, 4) : 1;
               v.play().catch(e => log('play()', e.message)); }
        upd();
        return true;
      },
      stop() { want = false; v.pause(); load(''); last = -1; upd(); return true; },
      seek(ms) { try { v.currentTime = ms / 1000; } catch (e) { return false; } return true; },
      setFullScreen(f) { el.__fs = el.fullScreen = !!f; place(); },
      setVolume(x) { v.volume = Math.max(0, Math.min(1, x / 100)); return true; },
      getVolume: () => Math.round(v.volume * 100),
      getComponents: () => [], getCurrentActiveComponents: () => [],
      selectComponent() {}, unselectComponent() {}
    });
  }

  function patch(el) {
    if (!el || el.__hbb || el.tagName !== 'OBJECT') return;
    const t = (el.getAttribute('type') || '').toLowerCase();
    if (!t) return;
    el.__hbb = true;
    if (t === 'application/oipfapplicationmanager') own(el, appMgr);
    else if (t === 'application/oipfconfiguration') own(el, config);
    else if (t === 'application/oipfcapabilities') own(el, caps);
    else if (t === 'application/oipfsearchmanager') own(el, { createSearch: () => ({ result: [] }) });
    else if (t === 'application/oipfdrmagent') own(el, { sendDRMMessage() {}, DRMSystemStatus: () => 0 });
    else if (t === 'application/oipfparentalcontrolmanager') own(el, { parentalRatingSchemes: [] });
    else if (t === 'video/broadcast') { broadcast(el); el.style.visibility = 'hidden'; }
    else if (/^(video|audio)\/|dash\+xml|mpegurl/.test(t)) avControl(el);
    log('patch', t);
  }
  // L'app può chiamare i metodi subito dopo aver creato l'<object>, prima che il
  // MutationObserver lo veda: metodi "pigri" sul prototipo che completano l'oggetto al volo.
  const LAZY = ['play', 'stop', 'seek', 'setFullScreen', 'setVolume', 'getVolume', 'getComponents',
    'getCurrentActiveComponents', 'selectComponent', 'unselectComponent', 'bindToCurrentChannel',
    'setChannel', 'prevChannel', 'nextChannel', 'release', 'getChannelConfig', 'createChannelObject',
    'getOwnerApplication', 'getChildApplications', 'hasCapability', 'createSearch'];
  LAZY.forEach(m => {
    if (m in HTMLObjectElement.prototype) return;
    Object.defineProperty(HTMLObjectElement.prototype, m, { configurable: true, writable: true,
      value: function (...a) {
        patch(this);
        const own = Object.prototype.hasOwnProperty.call(this, m) && this[m];
        return typeof own === 'function' ? own.apply(this, a) : undefined;
      } });
  });
  ['xmlCapabilities', 'configuration', 'localSystem', 'privateData'].forEach(p => {
    if (p in HTMLObjectElement.prototype) return;
    Object.defineProperty(HTMLObjectElement.prototype, p, { configurable: true,
      get() { patch(this); return Object.prototype.hasOwnProperty.call(this, p) ? this[p] : undefined; } });
  });

  const scan = root => { if (root.querySelectorAll) root.querySelectorAll('object').forEach(patch); };
  new MutationObserver(ms => ms.forEach(m => {
    m.addedNodes.forEach(n => { if (n.nodeType === 1) { patch(n); scan(n); } });
    if (m.type === 'attributes') {
      patch(m.target);
      if (m.attributeName === 'data' && m.target.__avLoad) m.target.__avLoad();
    }
  })).observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ['type', 'data'] });
  window.oipfObjectFactory = {
    isObjectSupported: () => true,
    createApplicationManagerObject: () => appMgr, createConfigurationObject: () => config,
    createCapabilitiesObject: () => caps, createVideoBroadcastObject: () => { const o = document.createElement('object'); broadcast(o); return o; },
    createVideoMpegObject: () => { const o = document.createElement('object'); avControl(o); return o; }
  };

  // (il tasto "indietro" arriva già come VK_BACK: lo invia tvd tramite Chrome)

  // niente sintonizzatore: sotto l'app c'è uno sfondo nero al posto del canale TV
  const bg = () => { const st = document.createElement('style');
    st.textContent = 'html{background:#000}';
    (document.head || document.documentElement).appendChild(st); };
  if (document.documentElement) bg(); else document.addEventListener('DOMContentLoaded', bg);

  scan(document);   // oggetti già presenti (se il simulatore arriva a pagina caricata)
  window.__hbbtv = { app, keyset, VK };
  log('pronto');
})();
