from bilalcast.logger import log


CONFIG_FILE = "config.json"
AP_NAME = "Bilal Cast Onboarding"
AP_DOMAIN = "bilalcast.net"
_REBOOT_TIMER = None
_config_saved = False

_REDIRECT_HTML = (
    "<!DOCTYPE html><html><head>"
    "<meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>Redirecting...</title>"
    "<meta http-equiv=refresh content='0;url=http://{domain}'>"
    "</head><body>Redirecting...</body></html>"
)

_INDEX_HTML = (
    "<!DOCTYPE html><html><head>"
    "<meta charset=UTF-8>"
    "<meta name=viewport content='width=device-width,initial-scale=1'>"
    "<meta name=apple-mobile-web-app-capable content=yes>"
    "<meta name=apple-mobile-web-app-status-bar-style content=default>"
    "<meta name=apple-mobile-web-app-title content='Bilal Cast'>"
    "<link rel=apple-touch-icon href=/icon.png>"
    "<title>Bilal Cast</title>"
    "<style>"
    "body{{font-family:sans-serif;margin:0;padding:16px;background:#f4f6f9;color:#222}}"
    "h1{{margin:0 0 12px;font-size:1.3rem;color:#1a73e8}}"
    ".c{{background:#fff;border-radius:8px;padding:14px;margin:8px 0;box-shadow:0 1px 3px rgba(0,0,0,.12)}}"
    "label{{display:block;margin:10px 0 4px;font-size:.9rem;font-weight:600}}"
    "input,select{{box-sizing:border-box;width:100%;padding:8px;border:1px solid #ccc;border-radius:4px;font-size:.95rem;background:#fff}}"
    "input:focus,select:focus{{outline:none;border-color:#1a73e8}}"
    "button{{box-sizing:border-box;width:100%;padding:10px 14px;margin-top:12px;border:none;border-radius:4px;cursor:pointer;font-size:.95rem;background:#1a73e8;color:#fff}}"
    "</style></head><body>"
    "<h1>Bilal Cast</h1>"
    "<div class=c>"
    "<form action=/configure method=POST autocomplete=off autocapitalize=none id=cfg>"
    "<div id=picker_wrap style='display:{show_picker}'>"
    "<label for=ssid_picker>Wi-Fi Network</label>"
    "<select id=ssid_picker onchange='onPickNetwork(this)'>"
    "<option value='' disabled selected hidden>Select your network</option>"
    "{network_options}"
    "<option value='__other__'>Other (type below)</option>"
    "</select></div>"
    "<label for=ssid id=ssid_label style='display:{show_manual}'>Wi-Fi Name (SSID)</label>"
    "<input type=text id=ssid name=ssid required style='display:{show_manual}'>"
    "<label for=password>Wi-Fi Password</label>"
    "<input type=text id=password name=password>"
    "<label for=cast_device_name>Cast Device Name</label>"
    "<input type=text id=cast_device_name name=cast_device_name"
    " placeholder='Found in Google Home app under device settings' required>"
    "<button type=submit>Save &amp; Connect</button>"
    "</form></div>"
    "<script>"
    "function onPickNetwork(sel){{"
    "var input=document.getElementById('ssid');"
    "var label=document.getElementById('ssid_label');"
    "if(sel.value==='__other__'){{input.value='';input.style.display='block';label.style.display='block';input.focus();}}"
    "else if(sel.value===''){{input.value='';input.style.display='none';label.style.display='none';}}"
    "else{{input.value=sel.value;input.style.display='none';label.style.display='none';}}"
    "}}"
    "document.getElementById('cfg').addEventListener('submit',function(e){{"
    "var sel=document.getElementById('ssid_picker');"
    "var input=document.getElementById('ssid');"
    "if(sel.value===''){{e.preventDefault();sel.focus();return;}}"
    "if(sel.value!=='__other__')input.value=sel.value;"
    "if(!input.value.trim()){{"
    "e.preventDefault();"
    "input.style.display='block';"
    "document.getElementById('ssid_label').style.display='block';"
    "input.focus();"
    "}}"
    "}});"
    "</script>"
    "</body></html>"
)


async def captive_portal():
    import asyncio
    import json
    import os
    import network
    import machine, time  # pyright: ignore[reportMissingImports]
    from bilalcast.phew import dns, access_point, server

    # Scan for networks before starting the AP (blocking is fine here)
    network_options = ""
    try:
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        time.sleep(2)
        results = wlan.scan()
        log("scan found {} networks".format(len(results)))
        results.sort(key=lambda x: -x[3])  # sort by RSSI descending
        seen = set()
        for r in results:
            try:
                ssid = r[0].decode("utf-8")
            except Exception:
                continue
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            safe = ssid.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
            network_options += '<option value="{}">{}</option>'.format(safe, safe)
    except Exception as e:
        log("Wi-Fi scan failed (non-fatal): {}".format(e))

    show_picker = "block" if network_options else "none"
    show_manual = "none" if network_options else "block"
    index_html = _INDEX_HTML.format(
        network_options=network_options,
        show_picker=show_picker,
        show_manual=show_manual,
    )

    app = server.Phew()

    @app.catchall()
    def ap_catch_all(request):
        if _config_saved and "apple.com" in request.headers.get("host", ""):
            return "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>"
        if request.headers.get("host") != AP_DOMAIN:
            return _REDIRECT_HTML.format(domain=AP_DOMAIN), 302
        return "Not found.", 404

    @app.route("/icon.png", methods=["GET"])
    def ap_icon(request):
        try:
            return app.serve_file("www/icon.png")
        except Exception:
            return "", 404

    @app.route("/", methods=["GET"])
    def ap_index(request):
        if request.headers.get("host") != AP_DOMAIN:
            return _REDIRECT_HTML.format(domain=AP_DOMAIN.lower()), 302
        return index_html, 200

    @app.route("/configure", methods=["POST"])
    def ap_configure(request):
        global _REBOOT_TIMER, _config_saved
        with open(CONFIG_FILE, "w") as f:
            json.dump(request.form, f)
            f.flush()
        try:
            os.sync()
        except:
            pass
        _config_saved = True
        _REBOOT_TIMER = machine.Timer(-1)
        _REBOOT_TIMER.init(period=3000, mode=machine.Timer.ONE_SHOT, callback=lambda t: machine.reset())
        ssid = request.form.get("ssid", "")
        return (
            "<!DOCTYPE html><html><head>"
            "<meta charset=UTF-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Bilal Cast</title>"
            "<style>body{font-family:sans-serif;margin:0;padding:16px;background:#f4f6f9;color:#222}"
            "h1{margin:0 0 12px;font-size:1.3rem;color:#1a73e8}"
            ".c{background:#fff;border-radius:8px;padding:14px;margin:8px 0;"
            "box-shadow:0 1px 3px rgba(0,0,0,.12)}.ok{color:#188038}</style></head><body>"
            "<h1>Bilal Cast</h1>"
            "<div class=c><b class=ok>&#10003; Saved!</b><br>Connecting to <b>"
            + ssid +
            "</b>&hellip;</div>"
            "<div class=c>Once connected, visit<br><b>http://bilalcast.local</b></div>"
            "</body></html>"
        ), 200

    ap = access_point(AP_NAME)
    for _ in range(20):
        if ap.active():
            break
        time.sleep_ms(100)
    try:
        dns.run_catchall(ap.ifconfig()[0])
    except Exception as e:
        log("DNS server failed (non-fatal): {}".format(e))
    loop = asyncio.get_event_loop()
    app.run_as_task(loop)
    while True:
        await asyncio.sleep_ms(1000)
