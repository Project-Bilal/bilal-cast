from cast_functions import test_cast_url
from scheduler import DING_URL, restart_athan
from utils import disconnect_wifi

async def bilal_server(store, device_registry, wifi_file, athan_loop):
    import asyncio
    import json
    from phew import server
    