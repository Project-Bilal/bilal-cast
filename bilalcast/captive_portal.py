from bilalcast.logger import log


CONFIG_FILE = "config.json"
AP_NAME = "Bilal Cast Onboarding"
AP_DOMAIN = "bilalcast.net"
_REBOOT_TIMER = None


async def captive_portal():
    import asyncio
    import json
    import os
    import machine, time  # pyright: ignore[reportMissingImports]
    from bilalcast.phew import dns, access_point, server
    from bilalcast.phew.template import render_template

    app = server.Phew()

    @app.catchall()
    def ap_catch_all(request):
        if request.headers.get("host") != AP_DOMAIN:
            return render_template("www/redirect.html", domain=AP_DOMAIN)
        return "Not found.", 404

    @app.route("/icon.png", methods=["GET"])
    def ap_icon(request):
        return app.serve_file("www/icon.png")

    @app.route("/", methods=["GET"])
    def ap_index(request):
        if request.headers.get("host") != AP_DOMAIN:
            return render_template("www/redirect.html", domain=AP_DOMAIN.lower())
        return render_template("www/index.html")

    @app.route("/configure", methods=["POST"])
    def ap_configure(request):
        global _REBOOT_TIMER
        with open(CONFIG_FILE, "w") as f:
            json.dump(request.form, f)
            f.flush()
        try:
            os.sync()
        except:
            pass
        _REBOOT_TIMER = machine.Timer(-1)
        _REBOOT_TIMER.init(period=1000, mode=machine.Timer.ONE_SHOT, callback=lambda t: machine.reset())
        return render_template("www/configured.html", ssid=request.form.get("ssid", ""))

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
