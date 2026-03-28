__version__ = "0.0.2"

# highly recommended to set a lowish garbage collection threshold
# to minimise memory fragmentation as we sometimes want to
# allocate relatively large blocks of ram.
import gc  # pyright: ignore[reportMissingImports]

gc.threshold(50000)

# phew! the Pico (or Python) HTTP Endpoint Wrangler
# helper method to put the pico into access point mode
def access_point(ssid, password=None):
    import network  # pyright: ignore[reportMissingImports]

    # start up network in access point mode
    wlan = network.WLAN(network.AP_IF)
    wlan.config(essid=ssid)
    if password:
        wlan.config(password=password)
    else:
        wlan.config(security=0)  # disable password
    wlan.active(True)

    return wlan
