import sys
import ctypes
import ctypes.wintypes as _wt
from collections import deque
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QLabel, QFrame,
    QVBoxLayout, QHBoxLayout, QGridLayout, QProgressBar, QPushButton
)
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPixmap, QFont
from PySide6.QtCore import Qt, QPointF, QAbstractNativeEventFilter, QTimer
import time
import re
import sqlite3

# =========================================================
# Key bindings
# =========================================================

_BINDS_PATH = "src/acc_dashboard/resources/config/bind.txt"

_KEY_MAP = {
    "F1": Qt.Key_F1, "F2": Qt.Key_F2, "F3": Qt.Key_F3, "F4": Qt.Key_F4,
    "F5": Qt.Key_F5, "F6": Qt.Key_F6, "F7": Qt.Key_F7, "F8": Qt.Key_F8,
    "F9": Qt.Key_F9, "F10": Qt.Key_F10, "F11": Qt.Key_F11, "F12": Qt.Key_F12,
    "PageUp": Qt.Key_PageUp, "PageDown": Qt.Key_PageDown,
    "Home": Qt.Key_Home, "End": Qt.Key_End,
    "Insert": Qt.Key_Insert, "Delete": Qt.Key_Delete,
    "Space": Qt.Key_Space, "Return": Qt.Key_Return, "Enter": Qt.Key_Return,
    "Up": Qt.Key_Up, "Down": Qt.Key_Down, "Left": Qt.Key_Left, "Right": Qt.Key_Right,
    **{c: getattr(Qt, f"Key_{c}") for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
}

# Windows virtual-key codes — parallel to _KEY_MAP
_VK_MAP = {
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
    "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
    "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    "PageUp": 0x21, "PageDown": 0x22,
    "Home": 0x24, "End":  0x23,
    "Insert": 0x2D, "Delete": 0x2E,
    "Space": 0x20, "Return": 0x0D, "Enter": 0x0D,
    "Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27,
    **{c: 0x41 + i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")},
}


_JOY_RETURNBUTTONS = 0x0080
_JOYERR_NOERROR    = 0

class _JOYINFOEX(ctypes.Structure):
    _fields_ = [
        ("dwSize",         ctypes.c_ulong),
        ("dwFlags",        ctypes.c_ulong),
        ("dwXpos",         ctypes.c_ulong),
        ("dwYpos",         ctypes.c_ulong),
        ("dwZpos",         ctypes.c_ulong),
        ("dwRpos",         ctypes.c_ulong),
        ("dwUpos",         ctypes.c_ulong),
        ("dwVpos",         ctypes.c_ulong),
        ("dwButtons",      ctypes.c_ulong),  # bitmask: bit N = button N+1
        ("dwButtonNumber", ctypes.c_ulong),
        ("dwPOV",          ctypes.c_ulong),
        ("dwReserved1",    ctypes.c_ulong),
        ("dwReserved2",    ctypes.c_ulong),
    ]


def _load_binds(path=_BINDS_PATH):
    """Return (qt_binds, vk_binds, joy_binds) from bind.txt.

    joy_binds maps 0-based button index → action.
    Use JOY_BUTTON_N (1-based, matching G HUB numbering) in bind.txt.
    """
    qt_binds  = {}
    vk_binds  = {}
    joy_binds = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                action, key_name = line.split("=", 1)
                action   = action.strip()
                key_name = key_name.strip()

                m = re.fullmatch(r"JOY_BUTTON_(\d+)", key_name, re.IGNORECASE)
                if m:
                    joy_binds[int(m.group(1)) - 1] = action  # store 0-based
                    continue

                qt_key = _KEY_MAP.get(key_name)
                vk     = _VK_MAP.get(key_name)
                if qt_key is not None:
                    qt_binds[qt_key] = action
                if vk is not None:
                    vk_binds[vk] = action
    except FileNotFoundError:
        pass
    return qt_binds, vk_binds, joy_binds


# Windows MSG structure used to read WM_HOTKEY messages
class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd",    _wt.HWND),
        ("message", _wt.UINT),
        ("wParam",  _wt.WPARAM),
        ("lParam",  _wt.LPARAM),
        ("time",    _wt.DWORD),
        ("pt",      _wt.POINT),
    ]


class GlobalHotKeyFilter(QAbstractNativeEventFilter):
    """Intercepts WM_HOTKEY messages so binds work even when ACC is in focus."""

    _WM_HOTKEY = 0x0312

    def __init__(self, callbacks: dict):
        super().__init__()
        self._callbacks = callbacks  # {hotkey_id: callable}

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = _MSG.from_address(int(message))
            if msg.message == self._WM_HOTKEY:
                cb = self._callbacks.get(msg.wParam)
                if cb:
                    cb()
        return False, 0


# =========================================================
# Pace debug database
# =========================================================

_DB_PATH = "pace_debug.db"


def _open_pace_db() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS pace_anomalies (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        REAL,
            track     TEXT,
            car_id    INTEGER,
            arc_dist  REAL,
            dt        REAL,
            speed     REAL,
            steps     INTEGER,
            last_idx  INTEGER,
            cur_idx   INTEGER
        );
        CREATE TABLE IF NOT EXISTS pace_laps (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              REAL,
            track           TEXT,
            car_id          INTEGER,
            outcome         TEXT,
            sectors_ok      INTEGER,
            sectors_total   INTEGER,
            started_at_line INTEGER
        );
    """)
    con.commit()
    return con


# =========================================================
# Mini Map
# =========================================================

class MiniMapWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._track_pts = []
        self._cars = []
        self._bounds = None
        self._player_car_id = None
        self._pace_list = {}
        self.clock = time.perf_counter
        self._sector_len = 10
        self._sector_count = 0
        self._pt_index = {}
        self._player_car_rotation = None
        self._compare_mode = "self"
        self._session_mode = "qualifying"
        self._start_pos = None
        self._start_idx = None
        self._sector_arc_lengths = []
        self._track_name = ""
        self._db = _open_pace_db()

        self.setMinimumHeight(260)

    def set_sector_count(self, n: int):
        self._sector_count = max(0, int(n))

    def set_data(self, track_pts, cars, player_car_id=None, player_car_rotation=None, start_pos=None, track_name=""):
        self._track_name = track_name
        self._start_pos = start_pos
        self._track_pts = [(float(x), float(z)) for x, z in (track_pts or [])]
        self._cars = cars or []
        self._bounds = self._compute_bounds(self._track_pts) if self._track_pts else None
        self._player_car_id = player_car_id
        self._player_car_rotation = player_car_rotation
        self._pt_index = {pt: i for i, pt in enumerate(self._track_pts)}

        if self._track_pts and self._start_pos is not None:
            sx, sz = self._start_pos
            self._start_idx = min(
                range(len(self._track_pts)),
                key=lambda i: (self._track_pts[i][0] - sx) ** 2 + (self._track_pts[i][1] - sz) ** 2,
            )
        else:
            self._start_idx = None

        if self._track_pts:
            if self._sector_count > 0:
                self._sector_len = max(1, len(self._track_pts) // self._sector_count)
            else:
                self._sector_count = max(
                    1, (len(self._track_pts) + self._sector_len - 1) // self._sector_len
                )

            self._sector_arc_lengths = []
            n = len(self._track_pts)
            for s in range(self._sector_count):
                start_i = s * self._sector_len
                end_i = min((s + 1) * self._sector_len, n)
                arc = 0.0
                for i in range(start_i, end_i - 1):
                    x1, z1 = self._track_pts[i]
                    x2, z2 = self._track_pts[i + 1]
                    arc += ((x2 - x1) ** 2 + (z2 - z1) ** 2) ** 0.5
                self._sector_arc_lengths.append(arc)

        now = self.clock()

        for car in self._cars:
            car_id = car.get("car_id")
            if car_id is None:
                continue

            if car_id not in self._pace_list:
                points = {}
                for i in range(len(self._track_pts)):
                    pt = self._track_pts[i]
                    points[pt] = {
                        "speed": 0.0,
                        "last_speed": 0.0,
                        "next_point": self._track_pts[(i + 1) % len(self._track_pts)],
                    }

                sectors = {}
                for s in range(self._sector_count):
                    sectors[s] = {"avg": 0.0, "prev_avg": 0.0, "sum": 0.0, "cnt": 0}

                self._pace_list[car_id] = {
                    "points": points,
                    "last_point_seen": None,
                    "last_time_seen": now,
                    "sectors": sectors,
                    "last_sector": None,
                    "lap_sectors": {si: {"sum": 0.0, "cnt": 0} for si in range(self._sector_count)},
                    "lap_started_at_line": False,
                    "completed_laps": [],
                    "best_lap": None,
                    "best_lap_speed": 0.0,
                    "last_lap": None,
                }

        self.update()

    def find_closest_track_point(self, x, z):
        if not self._track_pts:
            return None
        closest_pt = None
        closest_dist = float("inf")
        for pt in self._track_pts:
            dx = pt[0] - x
            dz = pt[1] - z
            dist = dx * dx + dz * dz
            if dist < closest_dist:
                closest_dist = dist
                closest_pt = pt
        return closest_pt

    def _commit_sector(self, pace_data, sector_id: int):
        if sector_id is None:
            return
        sec = pace_data["sectors"].get(sector_id)
        if not sec or sec["cnt"] <= 0:
            return
        new_avg = sec["sum"] / max(sec["cnt"], 1)
        sec["prev_avg"] = sec["avg"]
        sec["avg"] = new_avg
        sec["sum"] = 0.0
        sec["cnt"] = 0

    def _log_lap(self, car_id, outcome: str, sectors_ok: int, total: int, started: bool):
        if self._db is None:
            return
        try:
            self._db.execute(
                "INSERT INTO pace_laps(ts,track,car_id,outcome,sectors_ok,sectors_total,started_at_line)"
                " VALUES(?,?,?,?,?,?,?)",
                (time.time(), self._track_name, car_id, outcome, sectors_ok, total, int(started)),
            )
            self._db.commit()
        except Exception:
            pass

    def _complete_lap(self, pace_data: dict, car_id=None):
        started = pace_data.get("lap_started_at_line", False)
        lap_sectors = pace_data.get("lap_sectors", {})
        sectors_with_data = sum(1 for sv in lap_sectors.values() if sv["cnt"] > 0)
        total = len(lap_sectors)

        # Reject any accumulation that didn't begin at the start/finish line.
        if not started:
            self._log_lap(car_id, "no_line", sectors_with_data, total, started)
            return

        # Qualifying: every sector must have data (no partial laps).
        # Race: allow laps with at least half the sectors covered.
        if self._session_mode == "qualifying":
            if sectors_with_data < total:
                self._log_lap(car_id, "incomplete", sectors_with_data, total, started)
                return
        else:
            if sectors_with_data < max(1, total // 2):
                self._log_lap(car_id, "incomplete", sectors_with_data, total, started)
                return

        self._log_lap(car_id, "valid", sectors_with_data, total, started)
        lap_avgs = {
            s: sv["sum"] / sv["cnt"] if sv["cnt"] > 0 else 0.0
            for s, sv in lap_sectors.items()
        }
        total_speed = sum(lap_avgs.values())
        pace_data["completed_laps"].append(lap_avgs)
        pace_data["last_lap"] = lap_avgs
        if total_speed > pace_data.get("best_lap_speed", 0.0):
            pace_data["best_lap"] = lap_avgs
            pace_data["best_lap_speed"] = total_speed

    def reset_paces(self):
        self._pace_list.clear()

    def set_compare_mode(self, mode: str):
        self._compare_mode = mode
        self.update()

    def set_session_mode(self, mode: str):
        self._session_mode = mode
        self.update()

    def compute_paces(self):
        if not self._track_pts:
            return

        for car in self._cars:
            car_id = car.get("car_id")
            if car_id is None or car_id not in self._pace_list:
                continue
            if car.get("x") == 0 and car.get("z") == 0:
                continue

            pace_data = self._pace_list[car_id]
            points = pace_data["points"]

            closest_pt = self.find_closest_track_point(car["x"], car["z"])
            if closest_pt is None:
                continue

            now = self.clock()
            last_time = pace_data.get("last_time_seen", now)
            dt = now - last_time
            last_point_seen = pace_data.get("last_point_seen")

            if last_point_seen is None:
                pace_data["last_point_seen"] = closest_pt
                pace_data["last_time_seen"] = now
                pace_data["last_sector"] = None
                continue

            if dt <= 1e-6:
                continue

            cur_idx  = self._pt_index.get(closest_pt)
            last_idx = self._pt_index.get(last_point_seen)
            if cur_idx is None or last_idx is None:
                # Stale point from a previous track load — reset
                pace_data["last_point_seen"] = closest_pt
                pace_data["last_time_seen"] = now
                pace_data["last_sector"] = None
                continue

            # Guard: if the car appears to have moved backwards by less than one
            # sector it is drifting in reverse / in the pit lane — skip rather
            # than walking the while-loop the wrong way around the track.
            if cur_idx < last_idx:
                backward = last_idx - cur_idx
                n_pts = len(self._track_pts)
                forward_wrap = cur_idx + (n_pts - last_idx)
                if backward < forward_wrap and backward < self._sector_len:
                    pace_data["last_point_seen"] = closest_pt
                    pace_data["last_time_seen"] = now
                    pace_data["last_sector"] = None
                    continue

            if closest_pt != last_point_seen:
                # Arc distance: walk every intermediate segment so curves
                # don't underestimate the distance (chord < arc in corners).
                arc_dist = 0.0
                walk = last_point_seen
                for _ in range(len(self._track_pts) + 1):
                    if walk not in points:
                        break
                    nxt = points[walk]["next_point"]
                    dx = nxt[0] - walk[0]
                    dz = nxt[1] - walk[1]
                    arc_dist += (dx * dx + dz * dz) ** 0.5
                    if nxt == closest_pt:
                        break
                    walk = nxt

                # Teleport detection: "return to pits" jumps the car by many
                # track points in one tick, producing physically impossible speed.
                # At ~350 km/h a car advances at most 2 points/tick (27.5 m / 0.2 s
                # = 137 m/s).  Real teleports are thousands of m/s; 400 m/s gives
                # a safe gap while allowing any legitimate high-speed driving.
                _MAX_SPEED = 400.0  # m/s ≈ 1440 km/h
                steps_fwd = (cur_idx - last_idx) % len(self._track_pts)
                computed_speed = arc_dist / dt if dt > 0 else float("inf")
                if arc_dist <= 0 or computed_speed > _MAX_SPEED:
                    if self._db is not None:
                        try:
                            self._db.execute(
                                "INSERT INTO pace_anomalies"
                                "(ts,track,car_id,arc_dist,dt,speed,steps,last_idx,cur_idx)"
                                " VALUES(?,?,?,?,?,?,?,?,?)",
                                (time.time(), self._track_name, car_id,
                                 arc_dist, dt, computed_speed,
                                 steps_fwd, last_idx, cur_idx),
                            )
                            self._db.commit()
                        except Exception:
                            pass
                    pace_data["last_point_seen"] = closest_pt
                    pace_data["last_time_seen"] = now
                    pace_data["last_sector"] = None
                    pace_data["lap_sectors"] = {
                        si: {"sum": 0.0, "cnt": 0} for si in range(self._sector_count)
                    }
                    pace_data["lap_started_at_line"] = False
                    continue

                speed = arc_dist / dt

                while last_point_seen != closest_pt:
                    if last_point_seen not in points:
                        break
                    points[last_point_seen]["last_speed"] = points[last_point_seen]["speed"]
                    points[last_point_seen]["speed"] = speed

                    idx = self._pt_index.get(last_point_seen)
                    if idx is not None and self._sector_count > 0:
                        s = idx // self._sector_len
                        if s >= self._sector_count:
                            s = self._sector_count - 1

                        # Lap crossing: finalise previous lap, reset accumulator.
                        # Mark the new lap as valid only after the first crossing so
                        # pit-exit partial laps are never committed as best/last lap.
                        if self._start_idx is not None and idx == self._start_idx:
                            self._complete_lap(pace_data, car_id=car_id)
                            pace_data["lap_sectors"] = {
                                si: {"sum": 0.0, "cnt": 0} for si in range(self._sector_count)
                            }
                            pace_data["lap_started_at_line"] = True

                        prev_s = pace_data.get("last_sector")
                        if prev_s is None:
                            pace_data["last_sector"] = s
                        elif s != prev_s:
                            self._commit_sector(pace_data, prev_s)
                            pace_data["last_sector"] = s

                        sec = pace_data["sectors"][s]
                        sec["sum"] += speed
                        sec["cnt"] += 1

                        lap_sv = pace_data["lap_sectors"].get(s)
                        if lap_sv is not None:
                            lap_sv["sum"] += speed
                            lap_sv["cnt"] += 1

                    last_point_seen = points[last_point_seen]["next_point"]

                pace_data["last_point_seen"] = closest_pt
                pace_data["last_time_seen"] = now

    def _get_sector_vref(self, s: int):
        """Returns (v, ref, rel) for sector s, or None if data is unavailable or pace is too similar."""
        if self._player_car_id is None:
            return None
        player_pace = self._pace_list.get(self._player_car_id)
        if not player_pace:
            return None

        sec = player_pace["sectors"].get(s)
        if not sec:
            return None

        v = float(sec.get("avg", 0.0))
        if v <= 0.0:
            return None

        lap_key = "last_lap" if self._session_mode == "race" else "best_lap"

        if self._compare_mode == "self":
            ref = float(sec.get("prev_avg", 0.0))
            if ref <= 0.0:
                return None
        elif self._compare_mode == "vs_best":
            player_lap = player_pace.get(lap_key)
            if player_lap is None:
                return None
            v = float(player_lap.get(s, 0.0))
            if v <= 0.0:
                return None

            best_ref = None
            best_ref_speed = 0.0
            for opp_id, pd in self._pace_list.items():
                if opp_id == self._player_car_id:
                    continue
                opp_lap = pd.get(lap_key)
                if opp_lap is None:
                    continue
                opp_speed = sum(opp_lap.values())
                if opp_speed > best_ref_speed:
                    best_ref_speed = opp_speed
                    best_ref = opp_lap

            if best_ref is None:
                return None
            ref = float(best_ref.get(s, 0.0))
            if ref <= 0.0:
                return None
        else:  # vs_avg
            player_lap = player_pace.get(lap_key)
            if player_lap is None:
                return None
            v = float(player_lap.get(s, 0.0))
            if v <= 0.0:
                return None

            opponent_speeds = [
                float(pd[lap_key][s])
                for pd in self._pace_list.values()
                if pd is not player_pace
                and pd.get(lap_key) is not None
                and s in pd[lap_key]
                and pd[lap_key][s] > 0.0
            ]
            if not opponent_speeds:
                return None
            ref = sum(opponent_speeds) / len(opponent_speeds)

        rel = (v - ref) / max(ref, 1e-6)
        if abs(rel) < 0.03:
            return None
        return v, ref, rel

    def compute_track_dominance(self, x, z):
        if self._player_car_id is None:
            return None

        idx = self._pt_index.get((x, z))
        if idx is None or self._sector_count <= 0:
            return None

        s = idx // self._sector_len
        if s >= self._sector_count:
            s = self._sector_count - 1

        result = self._get_sector_vref(s)
        if result is None:
            return None
        _, _, rel = result

        t = max(-1.0, min(1.0, rel / 0.10))
        a = abs(t)

        if t > 0:
            return QColor(int(30 * (1 - a)), int(200 + 55 * a), int(80 * (1 - a)))
        else:
            return QColor(int(220 + 35 * a), int(60 * (1 - a)), int(60 * (1 - a)))

    @staticmethod
    def _compute_bounds(pts):
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        return min(xs), max(xs), min(zs), max(zs)

    def _world_to_screen(self, x, z):
        if not self._bounds:
            return QPointF(self.width() / 2, self.height() / 2)

        minx, maxx, minz, maxz = self._bounds
        w = maxx - minx
        h = maxz - minz
        pad = 18

        s = min(
            (self.width() - 2 * pad) / max(w, 1e-6),
            (self.height() - 2 * pad) / max(h, 1e-6),
        )

        cx = (minx + maxx) / 2
        cz = (minz + maxz) / 2
        sx = (x - cx) * s + self.width() / 2
        sy = self.height() - ((z - cz) * s + self.height() / 2)
        return QPointF(sx, sy)

    def draw_player_marker(self, p: QPainter, pt: QPointF):
        rotation_deg = float(self._player_car_rotation or 0.0) * (180.0 / 3.14159265)
        pm = QPixmap("src/acc_dashboard/resources/images/player_marker.png")

        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.translate(pt.x(), pt.y())
        p.rotate(-rotation_deg)
        p.drawPixmap(-9, -9, 18, 18, pm)
        p.restore()

    def paintEvent(self, _):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)

            if not self._track_pts or len(self._track_pts) < 2:
                return
            if self._player_car_id is None or self._player_car_id not in self._pace_list:
                return

            pts = self._track_pts
            pairs = list(zip(pts, pts[1:])) + [(pts[-1], pts[0])]

            # Pass 1 — dark base track so the coloured overlay has contrast
            base_pen = QPen(QColor(48, 48, 52), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(base_pen)
            for (x1, z1), (x2, z2) in pairs:
                p.drawLine(self._world_to_screen(x1, z1), self._world_to_screen(x2, z2))

            # Pass 2 — pace colour overlay (None == no data, skip)
            for (x1, z1), (x2, z2) in pairs:
                col = self.compute_track_dominance(x1, z1)
                if col is None:
                    continue
                p.setPen(QPen(col, 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawLine(self._world_to_screen(x1, z1), self._world_to_screen(x2, z2))

            # Pass 3 — sector time-gained/lost labels
            if self._sector_arc_lengths:
                font = QFont()
                font.setPointSize(7)
                font.setBold(True)
                p.setFont(font)
                fm = p.fontMetrics()
                n_pts = len(self._track_pts)

                for s in range(self._sector_count):
                    result = self._get_sector_vref(s)
                    if result is None:
                        continue
                    v, ref, _ = result

                    arc = self._sector_arc_lengths[s] if s < len(self._sector_arc_lengths) else 0.0
                    if arc <= 0.0:
                        continue

                    # positive = player gains time (player faster than reference)
                    time_delta = arc / ref - arc / v

                    mid_idx = s * self._sector_len + self._sector_len // 2
                    if mid_idx >= n_pts:
                        continue

                    sp_mid = self._world_to_screen(*self._track_pts[mid_idx])
                    sp_prev = self._world_to_screen(*self._track_pts[max(0, mid_idx - 1)])
                    sp_next = self._world_to_screen(*self._track_pts[min(n_pts - 1, mid_idx + 1)])

                    dx = sp_next.x() - sp_prev.x()
                    dy = sp_next.y() - sp_prev.y()
                    length = (dx * dx + dy * dy) ** 0.5
                    if length > 0:
                        px, py = -dy / length, dx / length
                    else:
                        px, py = 0.0, 1.0

                    label = f"+{time_delta:.2f}s" if time_delta > 0 else f"{time_delta:.2f}s"
                    text_w = fm.horizontalAdvance(label)
                    text_h = fm.height()
                    lx = sp_mid.x() + px * 16 - text_w / 2
                    ly = sp_mid.y() + py * 16 + text_h / 4

                    text_color = QColor(80, 255, 120) if time_delta > 0 else QColor(255, 80, 80)
                    p.setPen(QPen(QColor(0, 0, 0, 200)))
                    p.drawText(int(lx + 1), int(ly + 1), label)
                    p.setPen(QPen(text_color))
                    p.drawText(int(lx), int(ly), label)

            # Start / finish — 4×4 checkered flag (2px cells = 8×8 px total)
            if self._start_pos is not None:
                sx, sz = self._start_pos
                sp = self._world_to_screen(sx, sz)
                cx, cy = int(sp.x()) - 4, int(sp.y()) - 4
                cell = 2
                p.setPen(Qt.NoPen)
                for row in range(4):
                    for col in range(4):
                        white = (row + col) % 2 == 0
                        p.setBrush(QBrush(QColor(255, 255, 255) if white else QColor(10, 10, 10)))
                        p.drawRect(cx + col * cell, cy + row * cell, cell, cell)

            # Opponents — bright white with dark outline so they pop on every track colour
            for car in self._cars:
                if car.get("x") == 0 and car.get("z") == 0:
                    continue
                if car.get("is_player"):
                    continue
                pt = self._world_to_screen(car["x"], car["z"])
                p.setPen(QPen(QColor(10, 10, 10), 2))
                p.setBrush(QBrush(QColor(240, 240, 240, 245)))
                p.drawEllipse(pt, 7, 7)

            # Player on top of everything
            for car in self._cars:
                if car.get("x") == 0 and car.get("z") == 0:
                    continue
                if car.get("is_player"):
                    self.draw_player_marker(p, self._world_to_screen(car["x"], car["z"]))

        finally:
            if p.isActive():
                p.end()


# =========================================================
# Track Card
# =========================================================

class TrackCard(QFrame):
    _MODES = ["self", "vs_best", "vs_avg"]
    _MODE_LABELS = {"self": "SELF", "vs_best": "VS BEST", "vs_avg": "VS FIELD"}
    _SESSION_MODES = ["qualifying", "race"]
    _SESSION_LABELS = {"qualifying": "QUALI", "race": "RACE"}

    def __init__(self):
        super().__init__()
        self.setObjectName("trackCard")
        self._mode_idx = 0
        self._session_idx = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header = QHBoxLayout()

        title = QLabel("MAP")
        title.setObjectName("sectionLabel")

        self.track_name = QLabel("—")
        self.track_name.setObjectName("trackName")
        self.track_name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.session_btn = QPushButton(self._SESSION_LABELS[self._SESSION_MODES[0]])
        self.session_btn.setObjectName("sessionBtn")
        self.session_btn.setFixedWidth(52)
        self.session_btn.clicked.connect(self._cycle_session)

        self.mode_btn = QPushButton(self._MODE_LABELS[self._MODES[0]])
        self.mode_btn.setObjectName("modeBtn")
        self.mode_btn.setFixedWidth(72)
        self.mode_btn.clicked.connect(self._cycle_mode)

        header.addWidget(title)
        header.addWidget(self.track_name, 1)
        header.addWidget(self.session_btn)
        header.addWidget(self.mode_btn)

        self.map = MiniMapWidget()

        root.addLayout(header)
        root.addWidget(self.map, 1)

    def _cycle_mode(self):
        self._mode_idx = (self._mode_idx + 1) % len(self._MODES)
        mode = self._MODES[self._mode_idx]
        self.map.set_compare_mode(mode)
        self.mode_btn.setText(self._MODE_LABELS[mode])

    def _cycle_session(self):
        self._session_idx = (self._session_idx + 1) % len(self._SESSION_MODES)
        mode = self._SESSION_MODES[self._session_idx]
        self.map.set_session_mode(mode)
        self.session_btn.setText(self._SESSION_LABELS[mode])

    def update_view(self, d):
        new_name = d.get("track_name", "—")
        if new_name != self.track_name.text():
            self.map.reset_paces()
        self.track_name.setText(new_name)
        self.map.set_data(
            d.get("track_points"),
            d.get("cars_coordinates", []),
            d.get("player_car_id", None),
            d.get("player_car_rotation", None),
            d.get("start_pos", None),
            new_name,
        )
        self.map.compute_paces()
        self.map.update()


# =========================================================
# Tyre Tile
# =========================================================

class TyreTile(QWidget):
    def __init__(self, label):
        super().__init__()
        self.label = label
        self.temp = None
        self.setMinimumSize(70, 50)

    def set_values(self, temp, *_):
        self.temp = temp
        self.update()

    def _temp_color(self):
        if self.temp is None:
            return QColor(38, 38, 44)
        if self.temp < 70:
            return QColor(32, 80, 185)
        if self.temp < 90:
            return QColor(30, 155, 80)
        if self.temp < 105:
            return QColor(185, 108, 15)
        return QColor(185, 35, 35)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)

        # Fill entire tile with temp colour
        p.setBrush(self._temp_color())
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(rect, 3, 3)

        # Corner label (FL / FR / RL / RR)
        f = p.font()
        f.setPointSize(6)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 110))
        p.drawText(rect.adjusted(5, 4, -3, 0), Qt.AlignTop | Qt.AlignLeft, self.label)

        # Temperature — dominant value
        temp_text = "—" if self.temp is None else f"{self.temp:.0f}°"
        f.setPointSize(13)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 230))
        p.drawText(rect, Qt.AlignCenter, temp_text)


# =========================================================
# Tyres Card
# =========================================================

class TiresCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("tiresCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 5, 8, 5)
        root.setSpacing(4)

        lbl = QLabel("TYRES")
        lbl.setObjectName("sectionLabel")
        header = QHBoxLayout()
        header.addWidget(lbl)
        header.addStretch()
        root.addLayout(header)

        grid = QGridLayout()
        grid.setSpacing(6)
        self.fl = TyreTile("FL")
        self.fr = TyreTile("FR")
        self.rl = TyreTile("RL")
        self.rr = TyreTile("RR")
        grid.addWidget(self.fl, 0, 0)
        grid.addWidget(self.fr, 0, 1)
        grid.addWidget(self.rl, 1, 0)
        grid.addWidget(self.rr, 1, 1)
        root.addLayout(grid, 1)

    def update_view(self, d):
        self.fl.set_values(d["front_left_temp"], d["front_left_wear"])
        self.fr.set_values(d["front_right_temp"], d["front_right_wear"])
        self.rl.set_values(d["rear_left_temp"], d["rear_left_wear"])
        self.rr.set_values(d["rear_right_temp"], d["rear_right_wear"])


# =========================================================
# Inputs Graph
# =========================================================

class InputsGraphWidget(QWidget):
    _N = 150  # samples (~30 s at 200 ms/tick)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._throttle = deque([0.0] * self._N, maxlen=self._N)
        self._brake    = deque([0.0] * self._N, maxlen=self._N)
        self._steer    = deque([0.5] * self._N, maxlen=self._N)
        self.setMinimumHeight(60)

    def push(self, throttle, brake, steer):
        self._throttle.append(throttle)
        self._brake.append(brake)
        self._steer.append((steer + 1.0) / 2.0)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            w, h = self.width(), self.height()
            n = self._N

            def x_of(i):
                return i / (n - 1) * w

            def y_of(v):
                return (1.0 - max(0.0, min(1.0, v))) * h

            for color, buf in (
                (QColor(0, 210, 70),   self._throttle),
                (QColor(232, 0, 45),   self._brake),
                (QColor(60, 140, 255), self._steer),
            ):
                p.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                data = list(buf)
                for i in range(1, n):
                    p.drawLine(
                        QPointF(x_of(i - 1), y_of(data[i - 1])),
                        QPointF(x_of(i),     y_of(data[i])),
                    )
        finally:
            if p.isActive():
                p.end()


class InputsCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("inputsCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(6)

        header = QHBoxLayout()
        lbl = QLabel("INPUTS")
        lbl.setObjectName("sectionLabel")

        self._t_dot = QLabel("● T")
        self._t_dot.setObjectName("inputLegendThrottle")
        self._b_dot = QLabel("● B")
        self._b_dot.setObjectName("inputLegendBrake")
        self._s_dot = QLabel("● S")
        self._s_dot.setObjectName("inputLegendSteer")

        header.addWidget(lbl)
        header.addStretch()
        header.addWidget(self._t_dot)
        header.addWidget(self._b_dot)
        header.addWidget(self._s_dot)
        root.addLayout(header)

        self.graph = InputsGraphWidget()
        root.addWidget(self.graph, 1)

    def update_view(self, d):
        self.graph.push(d["throttle"], d["brake"], d["steer"])


# =========================================================
# Fuel Card
# =========================================================

class FuelCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("fuelCard")
        self._max_seen = 1.0

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        # Row 1: section label + current fuel (most at-a-glance value)
        header = QHBoxLayout()
        fuel_lbl = QLabel("FUEL")
        fuel_lbl.setObjectName("sectionLabel")
        self.fuel_now = QLabel("— L")
        self.fuel_now.setObjectName("fuelNow")
        self.fuel_now.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(fuel_lbl)
        header.addWidget(self.fuel_now)
        root.addLayout(header)

        # Row 2: ultra-thin progress bar
        self.bar = QProgressBar()
        self.bar.setObjectName("fuelBar")
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(3)
        root.addWidget(self.bar)

        # Row 3: NEED (left) and MARGIN (right — the actionable number)
        vals = QHBoxLayout()
        vals.setSpacing(0)

        left_col = QVBoxLayout()
        left_col.setSpacing(1)
        need_lbl = QLabel("NEED")
        need_lbl.setObjectName("valLabel")
        self.need_val = QLabel("— L")
        self.need_val.setObjectName("valBig")
        left_col.addWidget(need_lbl)
        left_col.addWidget(self.need_val)

        right_col = QVBoxLayout()
        right_col.setSpacing(1)
        margin_lbl = QLabel("MARGIN")
        margin_lbl.setObjectName("valLabel")
        margin_lbl.setAlignment(Qt.AlignRight)
        self.margin_val = QLabel("— L")
        self.margin_val.setObjectName("marginVal")
        self.margin_val.setAlignment(Qt.AlignRight)
        right_col.addWidget(margin_lbl)
        right_col.addWidget(self.margin_val)

        vals.addLayout(left_col)
        vals.addStretch()
        vals.addLayout(right_col)
        root.addLayout(vals)

        # Row 4: per-lap consumption
        self.per_lap = QLabel("— L / LAP")
        self.per_lap.setObjectName("perLap")
        root.addWidget(self.per_lap)

    def update_view(self, d):
        fuel = d["fuel_left"]
        need = d["fuel_needed_to_finish"]
        margin = d["margin"]

        self.fuel_now.setText(f"{fuel:.1f} L")
        self.need_val.setText(f"{need:.1f} L")
        self.per_lap.setText(f"{d['fuel_per_lap']:.2f} L / LAP")

        self._max_seen = max(self._max_seen, fuel, need, 1.0)
        self.bar.setValue(int((fuel / self._max_seen) * 1000))

        self.margin_val.setText(f"{margin:+.1f} L")
        self.margin_val.setProperty("state", "good" if margin >= 0 else "bad")
        self.margin_val.style().unpolish(self.margin_val)
        self.margin_val.style().polish(self.margin_val)


# =========================================================
# Main Window
# =========================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EasyDash")
        self.resize(960, 500)

        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        main = QHBoxLayout()
        root.addLayout(main, 1)

        self.track = TrackCard()
        main.addWidget(self.track, 2)

        right = QVBoxLayout()
        right.setSpacing(10)
        main.addLayout(right, 1)

        self.fuel = FuelCard()
        self.fuel.setMaximumHeight(130)
        self.inputs = InputsCard()
        self.tyres = TiresCard()
        right.addWidget(self.fuel)
        right.addWidget(self.inputs, 1)
        right.addWidget(self.tyres, 2)

        self._binds, vk_binds, joy_binds = _load_binds()
        self._hotkey_ids = {}
        self._hotkey_filter = None
        self._register_global_hotkeys(vk_binds)

        self._joy_binds        = joy_binds   # {0-based btn idx: action}
        self._joy_prev_buttons = 0           # bitmask from last poll
        if joy_binds:
            self._joy_timer = QTimer(self)
            self._joy_timer.setInterval(50)  # 50 ms → 20 Hz, responsive enough
            self._joy_timer.timeout.connect(self._poll_joy)
            self._joy_timer.start()

        self.setStyleSheet("""
            QWidget {
                background: #070707;
                color: rgba(255,255,255,215);
                font-family: "Segoe UI";
            }
            QLabel { background: transparent; border: none; padding: 0; }

            /* Cards — sharp corners, F1 red left accent bar */
            #fuelCard, #tiresCard, #trackCard, #inputsCard {
                background: #0c0c0e;
                border-top:    1px solid rgba(255,255,255,10);
                border-right:  1px solid rgba(255,255,255,10);
                border-bottom: 1px solid rgba(255,255,255,10);
                border-left:   3px solid #E8002D;
                border-radius: 3px;
            }

            /* Small section labels — uppercase, dimmed */
            #sectionLabel {
                font-size: 9px;
                font-weight: 700;
                color: rgba(255,255,255,55);
            }

            /* Track name next to MAP label */
            #trackName {
                font-size: 10px;
                color: rgba(255,255,255,110);
            }

            /* Fuel — current amount is the first number eye lands on */
            #fuelNow {
                font-size: 20px;
                font-weight: 900;
                color: rgba(255,255,255,230);
            }

            /* Sublabels under NEED / MARGIN */
            #valLabel {
                font-size: 8px;
                font-weight: 700;
                color: rgba(255,255,255,45);
            }

            /* NEED value */
            #valBig {
                font-size: 16px;
                font-weight: 900;
                color: rgba(255,255,255,200);
            }

            /* MARGIN — largest fuel number, coloured by state */
            #marginVal {
                font-size: 22px;
                font-weight: 900;
            }
            QLabel#marginVal[state="good"] { color: #00FF88; }
            QLabel#marginVal[state="bad"]  { color: #FF2040; }

            /* Per-lap consumption */
            #perLap {
                font-size: 10px;
                color: rgba(255,255,255,90);
            }

            /* Fuel progress bar — 3 px red strip */
            #fuelBar {
                background: rgba(255,255,255,8);
                border: none;
                border-radius: 1px;
            }
            #fuelBar::chunk {
                background: #E8002D;
                border-radius: 1px;
            }

            /* Inputs legend dots */
            #inputLegendThrottle { font-size: 8px; font-weight: 700; color: #00D246; }
            #inputLegendBrake    { font-size: 8px; font-weight: 700; color: #E8002D; }
            #inputLegendSteer    { font-size: 8px; font-weight: 700; color: #3C8CFF; }

            /* Mode toggle button — red pill matching card accent */
            #modeBtn {
                background: rgba(232,0,45,0.10);
                border: 1px solid rgba(232,0,45,0.45);
                border-radius: 2px;
                color: #E8002D;
                font-size: 8px;
                font-weight: 700;
                padding: 2px 6px;
            }
            #modeBtn:hover   { background: rgba(232,0,45,0.22); }
            #modeBtn:pressed { background: rgba(232,0,45,0.38); }

            /* Session mode button — blue pill */
            #sessionBtn {
                background: rgba(60,140,255,0.10);
                border: 1px solid rgba(60,140,255,0.45);
                border-radius: 2px;
                color: #3C8CFF;
                font-size: 8px;
                font-weight: 700;
                padding: 2px 6px;
            }
            #sessionBtn:hover   { background: rgba(60,140,255,0.22); }
            #sessionBtn:pressed { background: rgba(60,140,255,0.38); }
        """)

    def _poll_joy(self):
        info = _JOYINFOEX()
        info.dwSize  = ctypes.sizeof(_JOYINFOEX)
        info.dwFlags = _JOY_RETURNBUTTONS
        if ctypes.windll.winmm.joyGetPosEx(0, ctypes.byref(info)) != _JOYERR_NOERROR:
            return
        buttons = info.dwButtons
        pressed = (buttons ^ self._joy_prev_buttons) & buttons  # newly pressed bits
        for btn_idx, action in self._joy_binds.items():
            if pressed & (1 << btn_idx):
                self._on_hotkey(action)
        self._joy_prev_buttons = buttons

    def _register_global_hotkeys(self, vk_binds: dict):
        callbacks = {}
        for vk, action in vk_binds.items():
            hid = len(self._hotkey_ids) + 1
            if ctypes.windll.user32.RegisterHotKey(None, hid, 0, vk):
                self._hotkey_ids[hid] = action
                callbacks[hid] = lambda a=action: self._on_hotkey(a)
        if callbacks:
            self._hotkey_filter = GlobalHotKeyFilter(callbacks)
            QApplication.instance().installNativeEventFilter(self._hotkey_filter)

    def _on_hotkey(self, action: str):
        if action == "cycle_pace_mode":
            self.track._cycle_mode()

    def keyPressEvent(self, event):
        # Fallback for when EasyDash window has focus
        action = self._binds.get(event.key())
        if action:
            self._on_hotkey(action)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        for hid in self._hotkey_ids:
            ctypes.windll.user32.UnregisterHotKey(None, hid)
        if self._hotkey_filter:
            QApplication.instance().removeNativeEventFilter(self._hotkey_filter)
        super().closeEvent(event)


# =========================================================
# Run
# =========================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
