# main.py
import asyncio
import json
import os

from phew import server, connect_to_wifi, is_connected_to_wifi
from bilalcast.captive_portal import captive_portal
from bilalcast.store import AsyncConfigStore
from bilalcast.utils import disconnect_wifi, sync_hms_from_http
from bilalcast.device_registry import DeviceRegistry
from bilalcast.scheduler import athan_scheduler
from bilalcast.bilal_server import bilal_server

WIFI_FILE = "wifi.json"
CONFIG_FILE = "config.json"
APP_SERVER = server.Phew()    # captive portal on port 80 (AP mode)
ATHAN_LOOP = None

async def main():
    global ATHAN_LOOP
    ip_address = None
    try:
        os.stat(WIFI_FILE)
        with open(WIFI_FILE) as f:
            wifi_credentials = json.load(f)
            ip_address = connect_to_wifi(wifi_credentials["ssid"], wifi_credentials["password"])
            await sync_hms_from_http("storage.googleapis.com")
            print(f"Connected to wifi, IP address {ip_address}")
            if not is_connected_to_wifi():
                disconnect_wifi()
    except Exception as e:
        print("in setup mode", e)
        captive_portal(APP_SERVER, WIFI_FILE)


    store = AsyncConfigStore(CONFIG_FILE)
    await store.read_all()
    
    device_registry = DeviceRegistry(ip_address=ip_address) 
    bilal_server(APP_SERVER, store, device_registry, ATHAN_LOOP)
    
    loop = asyncio.get_event_loop()
    APP_SERVER.run_as_task(loop)
    ATHAN_LOOP = loop.create_task(athan_scheduler(store))
    loop.run_forever()
    

try:
    asyncio.run(main())
except Exception as e:
    print(e)
    asyncio.new_event_loop()
finally:
    asyncio.new_event_loop()
    

