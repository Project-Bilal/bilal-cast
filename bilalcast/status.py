import asyncio
import json
import os
import time
import machine  # pyright: ignore[reportMissingImports]
import network  # pyright: ignore[reportMissingImports]

from bilalcast.phew import server
from bilalcast.phew.template import render_template
from bilalcast.prayer import ATHANS_ORDER


def _rssi_svg(dbm_str):
    try:
        v = int(dbm_str)
        bars = 3 if v >= -55 else 2 if v >= -70 else 1 if v >= -85 else 0
    except Exception:
        bars = -1
    on = "#1a73e8"
    off = "#d0d0d0"
    dot = on if bars > 0 else ("#d93025" if bars == 0 else off)
    c = [on if i < bars else off for i in range(3)]
    return (
        '<svg width="18" height="14" viewBox="0 0 18 14"'
        ' style="vertical-align:middle;margin-right:3px">'
        '<circle cx="9" cy="13" r="1.5" fill="' + dot + '"/>'
        '<path d="M5,10 Q9,6.5 13,10"'
        ' stroke="' + c[0] + '" stroke-width="2" fill="none" stroke-linecap="round"/>'
        '<path d="M2.5,7.5 Q9,2 15.5,7.5"'
        ' stroke="' + c[1] + '" stroke-width="2" fill="none" stroke-linecap="round"/>'
        '<path d="M0.5,5 Q9,-2 17.5,5"'
        ' stroke="' + c[2] + '" stroke-width="2" fill="none" stroke-linecap="round"/>'
        "</svg>"
    )


def _label_12h(label):
    if label and len(label) >= 5 and label[-3] == ":":
        return label[:-5] + _fmt12(label[-5:])
    return label


def _fmt12(hhmm):
    h, m = hhmm.split(":")
    h = int(h)
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return "{}:{:02d} {}".format(h12, int(m), suffix)


def render_status(state):
    now = time.localtime()
    hour = now[3]
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    local_time = "{}:{:02d} {} \u00b7 {:02d}-{:02d}-{:04d}".format(
        hour12, now[4], suffix, now[1], now[2], now[0]
    )
    try:
        rssi = str(network.WLAN(network.STA_IF).status("rssi"))
    except Exception:
        rssi = "?"
    now_mins = now[3] * 60 + now[4]
    rows = ""
    for p in ATHANS_ORDER:
        t = state["prayer_times"].get(p, "")
        display = _fmt12(t) if t else "&mdash;"
        if p == state["next_prayer"]:
            css = " class=nx"
        elif t:
            h, m = t.split(":")
            css = " class=ps" if int(h) * 60 + int(m) <= now_mins else ""
        else:
            css = ""
        rows += "<tr" + css + "><td>" + p + "</td><td>" + display + "</td></tr>"
    if state["last_cast_ok"] is True:
        lc = "<span class=ok>" + _label_12h(state["last_cast_label"] or "") + " &#10003;</span>"
    elif state["last_cast_ok"] is False:
        lc = "<span class=fl>" + _label_12h(state["last_cast_label"] or "") + " &#10007;</span>"
    else:
        lc = "none yet"
    if state["cast_host"]:
        cast_status = "<span class=ok>Found &#10003;</span>"
    else:
        cast_status = "<span class=fl>Not found &#9888;</span>"
    try:
        with open("ota_version.txt") as _f:
            ota_version = _f.read().strip()
    except Exception:
        ota_version = "unknown"
    addr = state.get("address") or ""
    if not addr and state.get("lat") is not None and state.get("lon") is not None:
        addr = "{}, {}".format(state["lat"], state["lon"])
    if addr:
        addr = addr.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        address_line = '<br><span style="font-size:.85rem;color:#5f6368">\U0001F4CD ' + addr + "</span>"
    else:
        address_line = ""
    return render_template(
        "www/status.html",
        device_name=state["device_name"] or "Bilal Cast",
        cast_status=cast_status,
        local_time=local_time,
        address_line=address_line,
        local_ip=state["local_ip"] or "?",
        rssi_svg=_rssi_svg(rssi),
        rows=rows,
        lc=lc,
        hostname=state["hostname"] or "bilalcast",
        ota_version=ota_version,
    )


def render_settings(state, pre_athan_mins, calc_method, prayer_volumes):
    vols = {}
    for p in ["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]:
        vols[p] = str(round(prayer_volumes.get(p, 0.5) * 100))
    return render_template(
        "www/settings.html",
        address=str(state.get("address") or ""),
        lat=str(state["lat"] or ""),
        lon=str(state["lon"] or ""),
        pre_athan_mins=str(pre_athan_mins),
        method=str(calc_method),
        lat_adj=str(state.get("lat_adj", 1)),
        midnight=str(state.get("midnight", 0)),
        school=str(state.get("school", 0)),
        athan_current=str(state.get("athan") or ""),
        fajr_current=str(state.get("fajr_athan") or ""),
        pre_current=str(state.get("pre_athan") or ""),
        cast_device_name=state["device_name"] or "",
        local_ip=state["local_ip"] or "",
        vol_fajr=vols["Fajr"],
        vol_dhuhr=vols["Dhuhr"],
        vol_asr=vols["Asr"],
        vol_maghrib=vols["Maghrib"],
        vol_isha=vols["Isha"],
    )


def save_settings(form, config_file):
    with open(config_file) as f:
        cfg = json.load(f)
    cfg["pre_athan_mins"] = form.get("pre_athan_mins", "10").strip()
    cfg["method"] = form.get("method", "2").strip()
    cfg["lat_adj"] = form.get("lat_adj", "1").strip()
    cfg["midnight"] = form.get("midnight", "0").strip()
    cfg["school"] = form.get("school", "0").strip()
    # athan sound selections (fall back to current value if the form omitted them)
    for _snd, _dflt in (("athan", "athan_1.mp3"), ("fajr_athan", "athan_fajr_1.mp3"), ("pre_athan", "Salat_Ibrahimiyya.mp3")):
        _v = form.get(_snd, "").strip()
        if _v:
            cfg[_snd] = _v
        elif _snd not in cfg:
            cfg[_snd] = _dflt
    for _p in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
        _k = "vol_" + _p
        try:
            cfg[_k] = str(max(0, min(100, int(form.get(_k, "50").strip()))))
        except Exception:
            cfg[_k] = "50"
    lat_val = form.get("lat", "").strip()
    lon_val = form.get("lon", "").strip()
    address_val = form.get("address", "").strip()
    if lat_val and lon_val:
        cfg["lat"] = lat_val
        cfg["lon"] = lon_val
        if address_val:
            cfg["address"] = address_val
        else:
            cfg.pop("address", None)
    elif address_val:
        cfg["address"] = address_val
        cfg.pop("lat", None)
        cfg.pop("lon", None)
    else:
        cfg.pop("lat", None)
        cfg.pop("lon", None)
        cfg.pop("address", None)
    old_name = cfg.get("cast_device_name", "")
    new_name = form.get("cast_device_name", "").strip()
    cast_host = form.get("cast_device_host", "").strip()
    cast_port_str = form.get("cast_device_port", "").strip()
    if new_name:
        cfg["cast_device_name"] = new_name
        if new_name != old_name:
            try:
                os.remove("cast_device.json")
            except Exception:
                pass
    # Persist the selected endpoint in config.json (durable/authoritative) and
    # seed the runtime cache so it's used immediately and survives a cache clear.
    if cast_host and cast_port_str:
        cfg["cast_device_host"] = cast_host
        cfg["cast_device_port"] = cast_port_str
        try:
            from bilalcast.discovery import _save_cast_cache
            _save_cast_cache(cast_host, int(cast_port_str))
        except Exception:
            pass
    elif new_name and new_name != old_name:
        # switched to a device whose endpoint we don't know — drop the stale one
        # so it is rediscovered via mDNS on next boot
        cfg.pop("cast_device_host", None)
        cfg.pop("cast_device_port", None)
    with open(config_file, "w") as f:
        json.dump(cfg, f)
        f.flush()
    try:
        os.sync()  # commit to flash before rebooting — littlefs may otherwise
                   # buffer the write and lose it on reset (onboarding does this too)
    except Exception:
        pass
    machine.Timer(-1).init(
        period=2000,
        mode=machine.Timer.ONE_SHOT,
        callback=lambda t: machine.reset(),
    )
    return "Saved — rebooting to apply…", 200


def start_status_server(
    state, pre_athan_mins, calc_method, prayer_volumes, config_file, activation_url, do_cast, local_ip
):
    app = server.Phew()

    @app.route("/", methods=["GET"])
    def status_page(request):
        return render_status(state)

    @app.route("/test", methods=["POST"])
    def test_cast_route(request):
        # volume=None: play at the speaker's current volume without changing it
        asyncio.create_task(do_cast(activation_url, "test", None))
        return "ok", 200

    @app.route("/icon.png", methods=["GET"])
    @app.route("/favicon.ico", methods=["GET"])
    def icon_route(request):
        # Serve from the filesystem (www/icon.png is in the OTA manifest).
        # Do NOT import the frozen bilalcast.icon_data here: once the app is
        # on the filesystem it shadows the frozen bilalcast package, so that
        # import raises and (having no guard) would kill the request task.
        return app.serve_file("www/icon.png")

    @app.route("/settings", methods=["GET"])
    def settings_page(request):
        return render_settings(state, pre_athan_mins, calc_method, prayer_volumes)

    @app.route("/settings", methods=["POST"])
    def settings_save(request):
        return save_settings(request.form, config_file)

    @app.route("/cast-devices", methods=["GET"])
    def cast_devices_route(request):
        return json.dumps({
            "devices": state.get("cast_devices") or [],
            "scanning": state.get("scan_in_progress", False),
        }), 200, "application/json"

    @app.route("/scan-cast-devices", methods=["POST"])
    def scan_cast_devices_route(request):
        from bilalcast.discovery import list_cast_devices

        async def _scan():
            state["scan_in_progress"] = True
            new_devices = await list_cast_devices(local_ip)
            existing = state.get("cast_devices") or []
            existing_names = [d["name"] for d in existing]
            for d in new_devices:
                if d["name"] not in existing_names:
                    existing.append(d)
                    existing_names.append(d["name"])
            state["cast_devices"] = existing
            state["scan_in_progress"] = False

        asyncio.create_task(_scan())
        return "ok", 200

    @app.route("/factory-reset", methods=["POST"])
    def factory_reset_route(request):
        for f in (config_file, "cast_device.json", "cast_state.json", "prayer_times.json", "location.json"):
            try:
                os.remove(f)
            except Exception:
                pass
        try:
            os.sync()  # commit the removals to flash before rebooting
        except Exception:
            pass
        machine.Timer(-1).init(
            period=2000,
            mode=machine.Timer.ONE_SHOT,
            callback=lambda t: machine.reset(),
        )
        return "resetting", 200

    loop = asyncio.get_event_loop()
    app.run_as_task(loop)
