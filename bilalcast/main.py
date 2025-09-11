# main.py

import uasyncio as asyncio  # pyright: ignore[reportMissingImports]
import ujson as json  # pyright: ignore[reportMissingImports, reportMissingModuleSource]
import uos as os  # pyright: ignore[reportMissingImports]

try:  # support for local development with local files
    from bilalcast.phew import connect_to_wifi, is_connected_to_wifi
    from bilalcast.captive_portal import captive_portal
    from bilalcast.utils import WIFI_FILE, disconnect_wifi
    from bilalcast import led_status
    from bilalcast.bilal_server import bilal_server
except ImportError:
    from phew import connect_to_wifi, is_connected_to_wifi
    from captive_portal import captive_portal
    from utils import WIFI_FILE, disconnect_wifi
    import led_status
    from bilal_server import bilal_server


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
        led_status.onboarding()
        await captive_portal()
    led_status.wifi_connected()
    await bilal_server()


try:
    asyncio.run(main())
except Exception as e:
    print(e)
    asyncio.new_event_loop()
finally:
    asyncio.new_event_loop()
