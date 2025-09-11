async def bilal_server():
    import uasyncio as asyncio  # pyright: ignore[reportMissingImports]
    import ujson as json  # pyright: ignore[reportMissingImports, reportMissingModuleSource]

    try:  # support for local development with local files
        from phew import server, get_ip_address
        from device_registry import DeviceRegistry
        from store import AsyncConfigStore
        from scheduler import restart_athan, play
        from utils import disconnect_wifi, WIFI_FILE, CONFIG_FILE, get_wifi_info, rssi_to_bars, rssi_to_quality
        import led_status
    except ImportError:
        from bilalcast.phew import server, get_ip_address
        from bilalcast.device_registry import DeviceRegistry
        from bilalcast.store import AsyncConfigStore
        from bilalcast.scheduler import restart_athan, play
        from bilalcast.utils import (
            disconnect_wifi,
            WIFI_FILE,
            CONFIG_FILE,
            get_wifi_info,
            rssi_to_bars,
            rssi_to_quality,
        )
        from bilalcast import led_status

    store = AsyncConfigStore(CONFIG_FILE)
    configs = await store.read_all()
    if configs:
        led_status.has_config()
    else:
        led_status.no_config()
    device_registry = DeviceRegistry(ip_address=get_ip_address())

    loop = asyncio.get_event_loop()
    app = server.Phew()

    def _json(data, status=200, headers="application/json"):
        body = json.dumps(data)
        return body, status, headers

    @app.route("/", methods=["GET"])
    def app_home(r):
        return app.serve_file("www/home.html")

    @app.route("/api/devices/<force>", methods=["GET", "POST"])
    def get_devices(r, force):
        force = force == "refresh"
        asyncio.create_task(device_registry.ensure_scan(force=force))
        return _json(device_registry.snapshot())

    @app.route("/api/cast/test", methods=["POST"])
    def test_cast(r):
        asyncio.create_task(
            play(r.data.get("file"), r.data["host"], r.data["port"], r.data.get("volume", 7))
        )
        return "ok", 200, "text/html"

    @app.route("/api/wifi/disconnect", methods=["POST", "GET"])
    def wifi_disconnect(r):
        asyncio.create_task(disconnect_wifi(WIFI_FILE))
        return "ok", 200

    @app.route("/api/settings", methods=["GET"])
    def get_settings(r):
        return _json(store.snapshot_sync())

    @app.route("/api/settings", methods=["PUT"])
    async def put_settings(r):
        await store.write_all(r.data)
        led_status.has_config()
        asyncio.create_task(restart_athan(store))
        return "ok", 200

    @app.route("/api/wifi/signal", methods=["GET"])
    def wifi_signal(r):
        info = get_wifi_info()
        if not info:
            data = {"connected": False}
        else:
            rssi = info["rssi_dbm"]
            data = {
                "connected": True,
                "ssid": info["ssid"],
                "rssi_dbm": rssi,
                "quality_pct": rssi_to_quality(rssi),
                "bars": rssi_to_bars(rssi),
            }
        return _json(data)

    @app.route("/icons/icon.png", methods=["GET"])
    def icon(r):
        return app.serve_file("www/icon.png")

    @app.route("/manifest.webmanifest", methods=["GET"])
    def web_manifest(r):
        manifest = {
            "name": "Bilal Cast",
            "short_name": "Bilal Cast",
            "description": "Prayer casting and settings for Bilal Cast.",
            "id": "bilal-cast",
            "start_url": ".",
            "scope": ".",
            "display": "standalone",
            "background_color": "#0b1220",
            "theme_color": "#0b1220",
            "icons": [
                {"src": "/icons/icon.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/icons/icon.png", "sizes": "512x512", "type": "image/png"},
            ],
        }

        return _json(manifest, headers="application/manifest+json")

    @app.catchall()
    def ap_catch_all(r):
        return "Not found.", 404

    app.run_as_task(loop)
    await restart_athan(store)
    loop.run_forever()
