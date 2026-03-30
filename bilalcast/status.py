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
    return render_template(
        "www/status.html",
        device_name=state["device_name"] or "Bilal Cast",
        cast_status=cast_status,
        local_time=local_time,
        local_ip=state["local_ip"] or "?",
        rssi_svg=_rssi_svg(rssi),
        rows=rows,
        lc=lc,
        hostname=state["hostname"] or "bilalcast",
        ota_version=ota_version,
    )


def render_settings(state, pre_athan_mins, calc_method):
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
        cast_device_name=state["device_name"] or "",
        local_ip=state["local_ip"] or "",
    )


def save_settings(form, config_file):
    with open(config_file) as f:
        cfg = json.load(f)
    cfg["pre_athan_mins"] = form.get("pre_athan_mins", "10").strip()
    cfg["method"] = form.get("method", "2").strip()
    cfg["lat_adj"] = form.get("lat_adj", "1").strip()
    cfg["midnight"] = form.get("midnight", "0").strip()
    cfg["school"] = form.get("school", "0").strip()
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
    if new_name:
        cfg["cast_device_name"] = new_name
        if new_name != old_name:
            try:
                os.remove("cast_device.json")
            except Exception:
                pass
    cast_host = form.get("cast_device_host", "").strip()
    cast_port_str = form.get("cast_device_port", "").strip()
    if cast_host and cast_port_str:
        try:
            from bilalcast.discovery import _save_cast_cache
            _save_cast_cache(cast_host, int(cast_port_str))
        except Exception:
            pass
    with open(config_file, "w") as f:
        json.dump(cfg, f)
    machine.Timer(-1).init(
        period=1000,
        mode=machine.Timer.ONE_SHOT,
        callback=lambda t: machine.reset(),
    )


def start_status_server(
    state, pre_athan_mins, calc_method, config_file, activation_url, do_cast, local_ip
):
    app = server.Phew()

    @app.route("/", methods=["GET"])
    def status_page(request):
        return render_status(state)

    @app.route("/test", methods=["POST"])
    def test_cast_route(request):
        asyncio.create_task(do_cast(activation_url, "test"))
        return "ok", 200

    @app.route("/icon.png", methods=["GET"])
    def icon_route(request):
        from bilalcast.icon_data import (  # pyright: ignore[reportMissingImports]
            DATA,
        )

        return DATA, 200, "image/png"

    @app.route("/settings", methods=["GET"])
    def settings_page(request):
        return render_settings(state, pre_athan_mins, calc_method)

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
            state["cast_devices"] = await list_cast_devices(local_ip)
            state["scan_in_progress"] = False

        asyncio.create_task(_scan())
        return "ok", 200

    @app.route("/factory-reset", methods=["POST"])
    def factory_reset_route(request):
        for f in (config_file, "cast_device.json", "cast_state.json"):
            try:
                os.remove(f)
            except Exception:
                pass
        machine.Timer(-1).init(
            period=1000,
            mode=machine.Timer.ONE_SHOT,
            callback=lambda t: machine.reset(),
        )
        return "resetting", 200

    loop = asyncio.get_event_loop()
    app.run_as_task(loop)
