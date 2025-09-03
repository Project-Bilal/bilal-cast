from cast import Chromecast

DING_URL = "https://storage.googleapis.com/athans/ding.mp3"

def play_url(url, vol, ip, port):
        # Handle volume
        device = Chromecast(ip, port)
        device.set_volume(vol)
        device.disconnect()
        # Handle casting
        device = Chromecast(ip, port)
        device.play_url(url)
        device.disconnect()


async def test_cast_url(url=None, vol=None, ip=None, port=None):
    if not url:
        url = DING_URL
    if not vol:
        vol = '1.0'

    play_url(url, vol, ip, port)