from utils import WIFI_FILE

AP_NAME = "Bilal Cast Onboarding"
AP_DOMAIN = "bilalcast.net"
_REBOOT_TIMER = None
_SERVER_STOP_TIMER = None
_REBOOT_AT = None


async def captive_portal():
    import asyncio
    import json
    import os    
    import machine, time
    from phew import dns, access_point, server
    from phew.template import render_template

    app = server.Phew()  

    def schedule_reset(delay_ms):
        """Reboot slightly after we send the HTTP response (no threads)."""
        global _REBOOT_TIMER, _REBOOT_AT
        _REBOOT_AT = time.ticks_add(time.ticks_ms(), delay_ms)
        def _cb(t):
            machine.reset()
        _REBOOT_TIMER = machine.Timer(-1)
        _REBOOT_TIMER.init(period=delay_ms, mode=machine.Timer.ONE_SHOT, callback=_cb)

    def schedule_server_stop(delay_ms=250):
        """Stop HTTP server (and DNS) shortly after response flushes."""
        global _SERVER_STOP_TIMER
        def _cb(t):
            try:
                try:
                    dns.stop()
                except:
                    pass
                app.stop()
            except:
                pass
        _SERVER_STOP_TIMER = machine.Timer(-1)
        _SERVER_STOP_TIMER.init(period=delay_ms, mode=machine.Timer.ONE_SHOT, callback=_cb)
    
    @app.catchall()
    def ap_catch_all(request):
        if request.headers.get("host") != AP_DOMAIN:
            return render_template("www/redirect.html", domain=AP_DOMAIN)
        return "Not found.", 404
    
    @app.route("/", methods=["GET"])
    def ap_index(request):
        if request.headers.get("host") != AP_DOMAIN:
            return render_template("www/redirect.html", domain=AP_DOMAIN.lower())
        return render_template("www/index.html")
    
    @app.route("/configure", methods=["POST"])
    def ap_configure(request):
        with open(WIFI_FILE, "w") as f:
            json.dump(request.form, f)
            f.flush()
        try:
            os.sync()  # safe to ignore if not present on your port
        except:
            pass

        # Schedule: stop server → reboot
        schedule_server_stop(300)  # give ~300ms for response to flush
        schedule_reset(1000)       # reboot ~1s later

        return render_template("www/configured.html", ssid=request.form.get("ssid", ""))

    ap = access_point(AP_NAME)
    dns.run_catchall(ap.ifconfig()[0])
    loop = asyncio.get_event_loop()
    app.run_as_task(loop)
    loop.run_forever()
        