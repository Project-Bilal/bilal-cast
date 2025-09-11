import socket, ssl, time

from struct import pack, unpack
import gc

THUMB = b"https://storage.googleapis.com/athans/athan_logo.png"

_SRC = b"sender-0"
_RECV = b"receiver-0"
_NS_CONN = b"urn:x-cast:com.google.cast.tp.connection"
_NS_RECV = b"urn:x-cast:com.google.cast.receiver"
_NS_MEDIA = b"urn:x-cast:com.google.cast.media"


def _varint(n):
    """Minimal protobuf varint encoder (bytes)."""
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def _frame(namespace, payload_utf8, dest=_RECV, src=_SRC):
    """
    Build a CastMessage protobuf frame, preceded by the 4-byte length.
    Fields:
      1: protocol_version = 0
      2: source_id        = src (string)
      3: destination_id   = dest (string)
      4: namespace        = namespace (string)
      5: payload_type     = 0 (STRING)
      6: payload_utf8     = payload_utf8 (string)
    """
    if isinstance(namespace, str):
        namespace = namespace.encode()
    if isinstance(dest, str):
        dest = dest.encode()
    if isinstance(payload_utf8, str):
        payload_utf8 = payload_utf8.encode()

    # Protobuf body
    body = (
        b"\x08\x00"  # protocol_version
        + b"\x12"
        + _varint(len(src))
        + src
        + b"\x1a"
        + _varint(len(dest))
        + dest
        + b"\x22"
        + _varint(len(namespace))
        + namespace
        + b"\x28\x00"  # payload_type = STRING (0)
        + b"\x32"
        + _varint(len(payload_utf8))
        + payload_utf8
    )
    return pack(">I", len(body)) + body


class Chromecast(object):
    def __init__(self, cast_ip, cast_port, timeout_s=5):
        self.ip = cast_ip
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self._sock.settimeout(timeout_s)
        except Exception:
            pass
        self._sock.connect((self.ip, cast_port))
        self.s = ssl.wrap_socket(self._sock)

        self._send(_frame(_NS_CONN, b'{"type":"CONNECT"}'))
        self._send(_frame(_NS_RECV, b'{"type":"GET_STATUS","requestId":1}'))

    def _send(self, data):
        """sendall for SSL sockets (write may be partial)."""
        mv = memoryview(data)
        total = 0
        while total < len(data):
            n = self.s.write(mv[total:])
            if n is None:
                # Some MicroPython ports return None; treat as all written
                break
            total += n

    def _read_exact(self, n):
        """Read exactly n bytes or raise."""
        chunks = bytearray()
        mv = memoryview(chunks)
        got = 0
        while got < n:
            chunk = self.s.read(n - got)
            if not chunk:
                raise OSError("socket closed while reading")
            chunks.extend(chunk)
            got += len(chunk)
        return bytes(chunks)

    def read_message(self, max_size=65536):
        """
        Read one Cast message (4-byte big-endian size + body).
        Returns: bytes body (protobuf-encoded CastMessage)
        """
        size_bytes = self._read_exact(4)
        siz = unpack(">I", size_bytes)[0]
        if siz <= 0 or siz > max_size:
            raise OSError("invalid cast frame size: %d" % siz)
        return self._read_exact(siz)

    def set_volume(self, volume):
        if isinstance(volume, float):
            v = ("%.2f" % volume).rstrip("0").rstrip(".")
        else:
            v = str(volume)
        payload = b'{"type":"SET_VOLUME","volume":{"level":' + v.encode() + b'},"requestId":2}'
        self._send(_frame(_NS_RECV, payload, dest=_RECV))

    def play_url(self, url):
        if isinstance(url, str):
            url_b = url.encode()
        else:
            url_b = url

        self._send(_frame(_NS_RECV, b'{"type":"LAUNCH","appId":"CC1AD845","requestId":3}'))

        transport_id = self._wait_for_transport_id(timeout_ms=5000)
        if not transport_id:
            return False

        self._send(_frame(_NS_CONN, b'{"type":"CONNECT"}', dest=transport_id))
        self._send(_frame(_NS_MEDIA, b'{"type":"GET_STATUS","requestId":4}', dest=transport_id))

        load_payload = (
            b'{"media":{"contentId":"' + url_b + b'","streamType":"BUFFERED","contentType":"audio/mp3","metadata":'
            b'{"metadataType":0,"title":"Bilal Cast","thumb":"' + THUMB + b'","images":[{"url":"' + THUMB + b'"}]}},'
            b'"type":"LOAD","autoplay":true,"customData":{},"requestId":5,"sessionId":"' + transport_id + b'"}'
        )

        self._send(_frame(_NS_MEDIA, load_payload, dest=transport_id))

        for _ in range(6):
            try:
                status = self.read_message()
            except OSError:
                break
            if b'"type":"MEDIA_STATUS"' in status and b'"Bilal Cast"' in status:
                return True

        return False

    def _wait_for_transport_id(self, timeout_ms=4000):
        """Wait until any incoming message contains "transportId":"..."""
        start = self._ticks_ms()
        key = b'"transportId":"'
        while self._ticks_diff(self._ticks_ms(), start) < timeout_ms:
            try:
                msg = self.read_message()
            except OSError:
                break
            i = msg.find(key)
            if i != -1:
                j = msg.find(b'"', i + len(key))
                if j != -1:
                    return msg[i + len(key) : j]
        return None

    @staticmethod
    def _ticks_ms():
        try:
            return time.ticks_ms()
        except AttributeError:
            return int(time.time() * 1000)

    @staticmethod
    def _ticks_diff(a, b):
        try:
            return time.ticks_diff(a, b)
        except AttributeError:
            return a - b

    def disconnect(self):
        try:
            self.s.close()
        finally:
            try:
                self._sock.close()
            except Exception:
                pass
        gc.collect()
