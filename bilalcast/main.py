# main.py
from bilalcast.bilal_server import bilal_server  
import uasyncio as asyncio
import ujson as json
import uos as os

from bilalcast.phew import connect_to_wifi, is_connected_to_wifi
from bilalcast.captive_portal import captive_portal
from bilalcast.utils import WIFI_FILE, disconnect_wifi, set_rtc


async def main():    
    try:
        os.stat(WIFI_FILE)
        with open(WIFI_FILE) as f:
            wifi_credentials = json.load(f)
            ip_address = connect_to_wifi(wifi_credentials["ssid"], wifi_credentials["password"])
            print(f"Connected to wifi, IP address {ip_address}")
            if not is_connected_to_wifi():
                print("disconnecting wifi")
                disconnect_wifi(WIFI_FILE)
    except Exception as e:
        print("in setup mode", e)
        await captive_portal()

    await bilal_server()
    
try:
    asyncio.run(main())
except Exception as e:
    print(e)
    asyncio.new_event_loop()
finally:
    asyncio.new_event_loop()
    

