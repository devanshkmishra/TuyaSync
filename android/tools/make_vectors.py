"""Generate golden test vectors for the Kotlin Tuya protocol from TinyTuya and the desktop app.

Run from the repository root:  python android/tools/make_vectors.py
"""

import binascii
import hmac
import json
import struct
import sys
from hashlib import md5, sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tinytuya.core import header as H  # noqa: E402
from tinytuya.core.crypto_helper import AESCipher  # noqa: E402
from tinytuya.core.message_helper import TuyaMessage, pack_message  # noqa: E402

from screensync.scenes import BUILTIN_SCENES, compile_scene, encode_scene_data  # noqa: E402
from screensync.screen_sync.bulb_control.tuya_bulb import TuyaBulbControl  # noqa: E402

hexs = lambda b: binascii.hexlify(b).decode()
KEY = b"0123456789abcdef"
IV = b"fixed-iv-123"
DEV = "bf0123456789abcdefgh"


def frame_6699(seq, cmd, payload, key, retcode=None, iv=IV):
    return pack_message(TuyaMessage(seq, cmd, retcode, payload, 0, True, H.PREFIX_6699_VALUE, iv), hmac_key=key)


def frame_55aa(seq, cmd, payload, key=None):
    return pack_message(TuyaMessage(seq, cmd, 0, payload, 0, True, H.PREFIX_55AA_VALUE, None), hmac_key=key)


def ecb(key, data, pad=True):
    return AESCipher(key).encrypt(data, use_base64=False, pad=pad)


vectors = {"key": KEY.decode(), "iv": hexs(IV), "device_id": DEV}

# Protocol 3.5: client CONTROL_NEW frame, device STATUS push, session negotiation.
control_json = b'{"protocol":5,"t":1700000000,"data":{"dps":{"20":true}}}'
vectors["v35_control"] = {
    "seq": 7, "cmd": 0x0D, "json": control_json.decode(),
    "frame": hexs(frame_6699(7, 0x0D, H.PROTOCOL_35_HEADER + control_json, KEY)),
}
status_json = b'{"protocol":4,"t":1700000001,"data":{"dps":{"20":true,"21":"colour","24":"00f003e803e8"}}}'
vectors["v35_status"] = {
    "frame": hexs(frame_6699(42, 0x08, H.PROTOCOL_35_HEADER + status_json, KEY, retcode=0)),
    "json": status_json.decode(),
}
query_reply = b'{"dps":{"20":false,"22":500}}'
vectors["v35_query_reply"] = {"frame": hexs(frame_6699(43, 0x10, query_reply, KEY, retcode=0)), "json": query_reply.decode()}

local_nonce = b"0123456789ABCDEF"
remote_nonce = b"fedcba9876543210"
step1 = frame_6699(1, 0x03, local_nonce, KEY)
step2_payload = remote_nonce + hmac.new(KEY, local_nonce, sha256).digest()
step2 = frame_6699(100, 0x04, step2_payload, KEY, retcode=0)
step3 = frame_6699(2, 0x05, hmac.new(KEY, remote_nonce, sha256).digest(), KEY)
xored = bytes(a ^ b for a, b in zip(local_nonce, remote_nonce))
session35 = AESCipher(KEY).encrypt(xored, use_base64=False, pad=False, iv=local_nonce[:12])[12:28]
vectors["v35_session"] = {
    "local_nonce": local_nonce.decode(), "remote_nonce": remote_nonce.decode(),
    "step1": hexs(step1), "step2": hexs(step2), "step3": hexs(step3), "session_key": hexs(session35),
}

# Protocol 3.4: HMAC-signed 55AA frames with ECB payloads.
session34 = ecb(KEY, xored, pad=False)
vectors["v34_session"] = {
    "local_nonce": local_nonce.decode(), "remote_nonce": remote_nonce.decode(),
    "step1": hexs(frame_55aa(1, 0x03, ecb(KEY, local_nonce), KEY)),
    "step2": hexs(frame_55aa(100, 0x04, b"\0\0\0\0" + ecb(KEY, step2_payload), KEY)),
    "step3": hexs(frame_55aa(2, 0x05, ecb(KEY, hmac.new(KEY, remote_nonce, sha256).digest()), KEY)),
    "session_key": hexs(session34),
}
vectors["v34_control"] = {
    "seq": 3, "json": control_json.decode(),
    "frame": hexs(frame_55aa(3, 0x0D, ecb(session34, H.PROTOCOL_34_HEADER + control_json), session34)),
}
vectors["v34_status"] = {
    "frame": hexs(frame_55aa(9, 0x08, b"\0\0\0\0" + ecb(session34, H.PROTOCOL_34_HEADER + status_json), session34)),
    "json": status_json.decode(),
}

# Protocol 3.3: CRC32 55AA frames; CONTROL carries the version header, DP_QUERY does not.
control33 = b'{"devId":"%s","uid":"%s","t":"1700000000","dps":{"20":true}}' % (DEV.encode(), DEV.encode())
query33 = b'{"gwId":"%s","devId":"%s","uid":"%s","t":"1700000000"}' % (DEV.encode(), DEV.encode(), DEV.encode())
vectors["v33_control"] = {"seq": 4, "json": control33.decode(), "frame": hexs(frame_55aa(4, 0x07, H.PROTOCOL_33_HEADER + ecb(KEY, control33)))}
vectors["v33_query"] = {"seq": 5, "json": query33.decode(), "frame": hexs(frame_55aa(5, 0x0A, ecb(KEY, query33)))}
vectors["v33_status"] = {
    "frame": hexs(frame_55aa(11, 0x08, b"\0\0\0\0" + H.PROTOCOL_33_HEADER + ecb(KEY, status_json))),
    "json": status_json.decode(),
}

# LAN discovery broadcasts.
udpkey = md5(b"yGAdlopoPVldABfn").digest()
bcast35 = b'{"ip":"192.168.1.40","gwId":"%s","active":2,"ability":0,"mode":0,"encrypt":true,"productKey":"keyabc","version":"3.5"}' % DEV.encode()
bcast33 = bcast35.replace(b'"3.5"', b'"3.3"')
vectors["udp"] = [
    {"frame": hexs(frame_6699(0, 0x13, bcast35, udpkey)), "json": bcast35.decode()},
    {"frame": hexs(frame_55aa(0, 0x13, b"\0\0\0\0" + ecb(udpkey, bcast33))), "json": bcast33.decode()},
]

# DS22000 payloads from the desktop app.
vectors["scenes"] = [
    {"name": scene.name, "encoded": encode_scene_data(compile_scene(scene, 1))} for scene in BUILTIN_SCENES
]
vectors["control_data"] = [
    {"rgb": rgb, "transition": transition, "encoded": TuyaBulbControl.control_payload(tuple(rgb), transition)}
    for rgb in ([255, 0, 0], [12, 200, 90], [255, 255, 255], [0, 0, 0])
    for transition in ("gradient", "direct")
]

out = ROOT / "android/tuya-core/src/test/resources/vectors.json"
out.write_text(json.dumps(vectors, indent=1) + "\n")
print(f"wrote {out}")
