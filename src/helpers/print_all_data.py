# dump_pyaccsharedmemory_to_file.py
#
# Examples:
#   python dump_pyaccsharedmemory_to_file.py --out acc_dump.json --once
#   python dump_pyaccsharedmemory_to_file.py --out acc_dump.json --hz 10
#   python dump_pyaccsharedmemory_to_file.py --out acc_dump.ndjson --hz 10 --ndjson
#
# Default behavior:
# - loops at 1 Hz
# - writes to acc_dump.json
# - overwrites the file each tick (so it's always the latest snapshot)

from __future__ import annotations

import argparse
import json
import time
from enum import Enum
from typing import Any, Dict, Set

from pyaccsharedmemory import accSharedMemory


def _decode_if_byteslike(x: Any) -> Any:
    if isinstance(x, (bytes, bytearray)):
        try:
            return x.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        except Exception:
            return list(x)
    return x


def to_jsonable(obj: Any, *, _seen: Set[int] | None = None) -> Any:
    if _seen is None:
        _seen = set()

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    obj = _decode_if_byteslike(obj)
    if isinstance(obj, str):
        return obj

    oid = id(obj)
    if oid in _seen:
        return "<circular>"
    _seen.add(oid)

    if isinstance(obj, Enum):
        return {"name": obj.name, "value": obj.value}

    if isinstance(obj, dict):
        return {str(k): to_jsonable(v, _seen=_seen) for k, v in obj.items()}

    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v, _seen=_seen) for v in obj]

    # Try iterable (for ctypes arrays etc.)
    try:
        if hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes, bytearray, dict)):
            return [to_jsonable(v, _seen=_seen) for v in list(obj)]
    except Exception:
        pass

    # Prefer __dict__
    if hasattr(obj, "__dict__"):
        out: Dict[str, Any] = {}
        for k, v in vars(obj).items():
            if not k.startswith("_"):
                out[k] = to_jsonable(v, _seen=_seen)
        return out

    # Fallback: public attributes
    out2: Dict[str, Any] = {}
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if callable(value):
            continue
        out2[name] = to_jsonable(value, _seen=_seen)
    if out2:
        return out2

    return str(obj)


def read_all_snapshot(sm_obj: Any) -> Dict[str, Any]:
    snap: Dict[str, Any] = {}
    for key in ("Physics", "Graphics", "Static", "Statics"):
        if hasattr(sm_obj, key):
            snap[key] = to_jsonable(getattr(sm_obj, key))
    return snap


def write_json(path: str, payload: Dict[str, Any], *, pretty: bool, mode: str) -> None:
    if mode not in ("w", "a"):
        raise ValueError("mode must be 'w' or 'a'")
    text = json.dumps(payload, indent=2 if pretty else None, ensure_ascii=False)
    with open(path, mode, encoding="utf-8") as f:
        if mode == "a":
            f.write(text + "\n")  # NDJSON style (one object per line)
        else:
            f.write(text)         # Normal JSON (single object)


def main() -> int:
    ap = argparse.ArgumentParser(description="Dump ALL PyAccSharedMemory data into a file.")
    ap.add_argument("--out", type=str, default="acc_dump.json", help="Output file path.")
    ap.add_argument("--once", action="store_true", help="Read once and write once.")
    ap.add_argument("--hz", type=float, default=1.0, help="Loop frequency (default 1 Hz).")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON.")
    ap.add_argument(
        "--ndjson",
        action="store_true",
        help="Append mode: write one JSON object per line (NDJSON).",
    )
    args = ap.parse_args()

    mode = "a" if args.ndjson else "w"
    period = 1.0 / max(args.hz, 0.001)

    asm = accSharedMemory()
    try:
        def dump_once() -> bool:
            sm = asm.read_shared_memory()
            if sm is None:
                return False
            payload = read_all_snapshot(sm)
            write_json(args.out, payload, pretty=args.pretty, mode=mode)
            return True

        if args.once:
            ok = dump_once()
            if not ok:
                raise RuntimeError(
                    "read_shared_memory() returned None (ACC running + shared memory enabled?)"
                )
            return 0

        # loop forever
        while True:
            dump_once()  # if None, just skip this tick
            time.sleep(period)

    finally:
        asm.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
