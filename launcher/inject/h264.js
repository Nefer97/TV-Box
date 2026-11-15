// h264.js — i siti credono che VP9/AV1 non siano supportati e mandano H.264,
// molto più leggero da decodificare per il Core 2 Duo del Mac mini.
(() => {
  if (window.__tvH264) return; window.__tvH264 = 1;
  const bad = /vp0?9|av01|av1/i;
  try {
    const MS = window.MediaSource;
    if (MS && MS.isTypeSupported) { const o = MS.isTypeSupported.bind(MS);
      MS.isTypeSupported = t => bad.test(t) ? false : o(t); }
    const cp = HTMLMediaElement.prototype.canPlayType;
    HTMLMediaElement.prototype.canPlayType = function (t) { return bad.test(t) ? '' : cp.call(this, t); };
    const mc = navigator.mediaCapabilities;
    if (mc && mc.decodingInfo) { const o = mc.decodingInfo.bind(mc);
      mc.decodingInfo = c => { const ct = (c && c.video && c.video.contentType) || '';
        return bad.test(ct) ? Promise.resolve({supported:false, smooth:false, powerEfficient:false}) : o(c); }; }
  } catch (e) {}
})();
