# main.py
from cast_functions import test_cast_url
import uasyncio as asyncio
import json
import os

from phew import server, connect_to_wifi, is_connected_to_wifi
from captive_portal import captive_portal
from store import AsyncConfigStore
from utils import disconnect_wifi, sync_hms_from_http
from device_registry import DeviceRegistry
from scheduler import athan_scheduler, restart_athan


WIFI_FILE = "wifi.json"
CONFIG_FILE = "config.json"

app = server.Phew()

ATHAN_LOOP = None

async def main():
    global ATHAN_LOOP
    ip_address = None
    
    try:
        os.stat(WIFI_FILE)
        with open(WIFI_FILE) as f:
            wifi_credentials = json.load(f)
            ip_address = connect_to_wifi(wifi_credentials["ssid"], wifi_credentials["password"])
            print("sync_hms_from_http")
            # await sync_hms_from_http("storage.googleapis.com")
            print(f"Connected to wifi, IP address {ip_address}")
            if not is_connected_to_wifi():
                print("disconnecting wifi")
                disconnect_wifi(WIFI_FILE)
    except Exception as e:
        print("in setup mode", e)
        captive_portal(WIFI_FILE)


    store = AsyncConfigStore(CONFIG_FILE)
    await store.read_all()
    
    device_registry = DeviceRegistry(ip_address=ip_address) 
    print("device_registry")
    print("bilal_server")
    
    

    def _json(data, status=200, headers="application/json"):
        body = json.dumps(data)
        return body, status, headers


    @app.route("/", methods=["GET"])
    def app_index(r):
        return "hello world", 200, "text/html"
    
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

    loop = asyncio.get_event_loop()
    app.run_as_task(loop)
    print("app.run_as_task")
    print(is_connected_to_wifi())
    # ATHAN_LOOP = loop.create_task(athan_scheduler(store))
    loop.run_forever()
    
    

try:
    asyncio.run(main())
except Exception as e:
    print(e)
    asyncio.new_event_loop()
finally:
    asyncio.new_event_loop()
    

