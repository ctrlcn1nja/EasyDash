import json
from pathlib import Path

_TRACK_CACHE = {}


def safe_track_name(raw: str) -> str:
    return raw.split("\x00", 1)[0].strip()


def load_track_points(path_to_points: str):
    if path_to_points in _TRACK_CACHE:
        return _TRACK_CACHE[path_to_points]

    p = Path(path_to_points)
    if not p.exists():
        _TRACK_CACHE[path_to_points] = []
        return []

    pts = json.loads(p.read_text(encoding="utf-8"))

    out = []
    if isinstance(pts, list) and pts:
        if isinstance(pts[0], dict):
            for q in pts:
                out.append((float(q["x"]), float(q["z"])))
        else:
            for q in pts:
                out.append((float(q[0]), float(q[1])))

    _TRACK_CACHE[path_to_points] = out
    return out


def process_track(sm):
    track_name = safe_track_name(sm.Static.track)
    folder = track_name.lower().replace(" ", "_")
    filename = f"points_{folder}.json"
    path_to_points = str(Path("src/acc_dashboard/resources/tracks") / folder / filename)

    flag = sm.Graphics.flag

    cars = []
    coords = sm.Graphics.car_coordinates  
    ids = getattr(sm.Graphics, "car_id", None)
    player_id = getattr(sm.Graphics, "player_car_id", None)

    for i in range(len(coords)):
        v = coords[i]
        car_id = ids[i] if ids is not None and i < len(ids) else None
        is_player = (car_id == player_id) if (car_id is not None and player_id is not None) else False
        cars.append({"x": float(v.x), "y": float(v.y), "z": float(v.z), "is_player": is_player})

    track_points = load_track_points(path_to_points)

    return {
        "track_name": track_name,
        "path_to_points": path_to_points,
        "flag": flag,
        "track_points": track_points,       
        "cars_coordinates": cars,
    }