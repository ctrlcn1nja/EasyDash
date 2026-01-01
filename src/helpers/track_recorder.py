from pyaccsharedmemory import accSharedMemory
import time
import json
import os

def clean_c_string(s: str) -> str:
    return s.split("\x00", 1)[0].strip()

sm = accSharedMemory()

points = []
current_file = None
flush_every = 10

def load_existing(filename: str):
    if not os.path.exists(filename):
        return []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []

def flush(filename: str, pts: list):
    # merge with what's already on disk (in case you restart)
    data = load_existing(filename)
    data.extend(pts)
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

try:
    while True:
        time.sleep(1)
        telemetry_data = sm.read_shared_memory()
        if telemetry_data is None:
            print(".", end=" ")
            continue

        track_raw = telemetry_data.Static.track
        if not track_raw:
            continue

        track_name = clean_c_string(track_raw)
        if not track_name:
            continue

        filename = f"points_{track_name}.json"

        # If track changed, flush old and start new
        if current_file is None:
            current_file = filename
        elif filename != current_file:
            if points:
                flush(current_file, points)
                points.clear()
            current_file = filename

        car_id = telemetry_data.Graphics.player_car_id
        cords = telemetry_data.Graphics.car_coordinates[car_id]

        points.append({"x": float(cords.x), "y": float(cords.y), "z": float(cords.z)})

        if len(points) >= flush_every:
            flush(current_file, points)
            points.clear()

        print(cords)

except KeyboardInterrupt:
    # Final flush on exit
    if current_file and points:
        flush(current_file, points)
