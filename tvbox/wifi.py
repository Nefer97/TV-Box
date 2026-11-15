"""Wi-Fi (Impostazioni > Wi-Fi): dialoga con wpa_supplicant@<scheda> tramite wpa_cli.
L'utente tv è nel gruppo netdev, quindi non servono privilegi di root.
La password non viene salvata in chiaro: si salva la chiave derivata (come wpa_passphrase)."""
import hashlib
import os
import re
import subprocess
import threading
import time

from .util import log

WPA_CLI = "/usr/sbin/wpa_cli"
wifi_lock = threading.Lock()


def wifi_iface():
    try:
        for n in sorted(os.listdir("/sys/class/net")):
            if os.path.isdir(f"/sys/class/net/{n}/wireless"):
                return n
    except OSError:
        pass
    return None


def _wpa(iface, *args, timeout=8):
    r = subprocess.run([WPA_CLI, "-i", iface, *args], capture_output=True,
                       text=True, timeout=timeout)
    return r.stdout.strip()


def _unescape_ssid(s):
    """wpa_cli stampa i nomi rete con escape stile C (\\xNN, \\\", \\\\)."""
    out, i = bytearray(), 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n == "x" and i + 3 < len(s):
                try:
                    out.append(int(s[i + 2:i + 4], 16))
                    i += 4
                    continue
                except ValueError:
                    pass
            out += {"n": b"\n", "r": b"\r", "t": b"\t", "e": b"\x1b"}.get(n, n.encode())
            i += 2
            continue
        out += c.encode()
        i += 1
    return out.decode("utf-8", "replace")


def _ipv4(iface):
    r = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", iface],
                       capture_output=True, text=True).stdout
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", r)
    return m.group(1) if m else None


def _saved(iface):
    nets = {}
    for line in _wpa(iface, "list_networks").splitlines()[1:]:
        f = line.split("\t")
        if len(f) >= 2 and f[0].isdigit():
            nets[_unescape_ssid(f[1])] = f[0]
    return nets


def wifi_status():
    iface = wifi_iface()
    if not iface:
        return {"present": False}
    try:
        st = dict(l.split("=", 1) for l in _wpa(iface, "status").splitlines() if "=" in l)
    except Exception as ex:
        return {"present": True, "iface": iface, "error": f"wpa_supplicant non risponde ({ex})"}
    if not st:
        return {"present": True, "iface": iface, "error": "wpa_supplicant non attivo"}
    res = {"present": True, "iface": iface, "state": st.get("wpa_state"),
           "connected": st.get("wpa_state") == "COMPLETED",
           "ssid": _unescape_ssid(st.get("ssid", "")) or None, "ip": _ipv4(iface)}
    if res["connected"]:
        m = re.search(r"RSSI=(-?\d+)", _wpa(iface, "signal_poll"))
        if m:
            res["signal"] = int(m.group(1))
    return res


def wifi_scan():
    iface = wifi_iface()
    if not iface:
        return {"error": "Nessuna scheda Wi-Fi"}
    with wifi_lock:
        _wpa(iface, "scan")
        # la scansione di tutti i canali può durare parecchi secondi: aspetto che
        # l'elenco smetta di crescere (minimo 3 s, massimo 10 s)
        lines, prev, t0 = [], -1, time.monotonic()
        while time.monotonic() - t0 < 10:
            time.sleep(1)
            lines = _wpa(iface, "scan_results").splitlines()[1:]
            if time.monotonic() - t0 >= 3 and len(lines) == prev and lines:
                break
            prev = len(lines)
        best = {}
        for line in lines:
            f = line.split("\t")
            if len(f) < 5 or not f[4]:
                continue                                   # rete nascosta
            ssid, sig, flags = _unescape_ssid(f[4]), int(f[2]), f[3]
            if ssid not in best or sig > best[ssid]["signal"]:
                best[ssid] = {"ssid": ssid, "signal": sig,
                              "secure": "WPA" in flags or "RSN" in flags or "WEP" in flags,
                              "wep": "WEP" in flags and "WPA" not in flags}
        saved = _saved(iface)
    for n in best.values():
        n["saved"] = n["ssid"] in saved
    return {"networks": sorted(best.values(), key=lambda n: -n["signal"])}


def wifi_connect(ssid, password):
    """Collega alla rete. Se fallisce ricarica la configurazione salvata (nulla cambia)."""
    iface = wifi_iface()
    if not iface or not ssid:
        return {"ok": False, "error": "Nessuna scheda Wi-Fi"}
    if password and not 8 <= len(password) <= 63:
        return {"ok": False, "error": "La password deve avere da 8 a 63 caratteri"}
    with wifi_lock:
        saved = _saved(iface)
        nid = saved.get(ssid)
        if nid is None or password:
            if nid is None:
                nid = _wpa(iface, "add_network")
                if not nid.isdigit():
                    return {"ok": False, "error": "wpa_supplicant non risponde"}
            raw = ssid.encode()
            _wpa(iface, "set_network", nid, "ssid", raw.hex())
            if password:
                # chiave derivata (come wpa_passphrase): la password in chiaro non va su disco
                psk = hashlib.pbkdf2_hmac("sha1", password.encode(), raw, 4096, 32).hex()
                _wpa(iface, "set_network", nid, "key_mgmt", "WPA-PSK")
                _wpa(iface, "set_network", nid, "psk", psk)
            else:
                _wpa(iface, "set_network", nid, "key_mgmt", "NONE")
            _wpa(iface, "set_network", nid, "scan_ssid", "1")
        _wpa(iface, "select_network", nid)
        ok, deadline = False, time.monotonic() + 30
        while time.monotonic() < deadline:
            time.sleep(1)
            st = dict(l.split("=", 1) for l in _wpa(iface, "status").splitlines() if "=" in l)
            if st.get("wpa_state") == "COMPLETED" and _unescape_ssid(st.get("ssid", "")) == ssid:
                ok = True
                break
        if not ok:
            _wpa(iface, "reconfigure")                     # torna alle reti salvate
            log.warning("wifi: collegamento a %r fallito", ssid)
            return {"ok": False, "error": "Collegamento non riuscito: password sbagliata "
                                          "o rete troppo lontana"}
        _wpa(iface, "enable_network", "all")               # le altre reti restano di riserva
        _wpa(iface, "save_config")
        ip = None
        for _ in range(15):
            ip = _ipv4(iface)
            if ip:
                break
            time.sleep(1)
        log.info("wifi: collegato a %r (%s)", ssid, ip)
        return {"ok": True, "ssid": ssid, "ip": ip}


def wifi_forget(ssid):
    iface = wifi_iface()
    if not iface:
        return {"ok": False}
    with wifi_lock:
        nid = _saved(iface).get(ssid)
        if nid is not None:
            _wpa(iface, "remove_network", nid)
            _wpa(iface, "save_config")
            _wpa(iface, "reassociate")
    return {"ok": True}
