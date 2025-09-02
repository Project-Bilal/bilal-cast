from bilalcast.cast_functions import play_url, test_cast_url
from bilalcast.scheduler import DING_URL, restart_athan
from bilalcast.utils import disconnect_wifi


async def bilal_server(app, store, device_registry, wifi_file, athan_loop):
    import asyncio
    import json

    def _json(data, status=200, headers="application/json"):
        body = json.dumps(data)
        return body, status, headers


    @app.route("/", methods=["GET"])
    def app_index(r):
        return app.serve_file("settings.html")
    
    @app.route("/api/devices/refresh", methods=["GET", "POST"])
    def refresh_devices(r):
        asyncio.create_task(device_registry.ensure_scan(force=True))
        return _json(device_registry.snapshot())
    
    @app.route("/api/devices", methods=["GET", "POST"])
    def get_devices(r):
        asyncio.create_task(device_registry.ensure_scan(force=False))        
        return _json(device_registry.snapshot())
    
    @app.route("/api/cast/test", methods=["POST"])
    def test_cast(r):
        asyncio.create_task(test_cast_url(r.data.get('value', DING_URL), r.data.get('volume', 10), r.data['host'], r.data['port']))
        return "ok", 200, "text/html"
    
    @app.route("/api/wifi/disconnect", methods=["POST", "GET"])
    def wifi_disconnect(r):
        asyncio.create_task(disconnect_wifi(wifi_file))
        return "ok", 200
        
    @app.route("/api/settings", methods=["GET"])
    def get_settings(r):
        return _json(store.snapshot_sync())
    
    @app.route("/api/settings", methods=["PUT"])
    async def put_settings(r):
        await store.write_all(r.data)
        await restart_athan(store, athan_loop)
        return "ok", 200
    
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
            { "src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png" },
            { "src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png" }
          ]
        }

        return _json(manifest, headers="application/manifest+json")
    
    @app.catchall()
    def ap_catch_all(r):
        return "Not found.", 404
