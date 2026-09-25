"""UDP 报文：JSON 一行，便于实验抓包阅读。"""

import json
from typing import Any, Dict

MAX_DATAGRAM = 1400


def pack_message(obj: Dict[str, Any]) -> bytes:
    raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_DATAGRAM:
        raise ValueError(f"datagram too large: {len(raw)}")
    return raw


def unpack_message(data: bytes) -> Dict[str, Any]:
    return json.loads(data.decode("utf-8"))
