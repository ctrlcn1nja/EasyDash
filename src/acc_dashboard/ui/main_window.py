import sys
import ctypes
import ctypes.wintypes as _wt
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QLabel, QFrame,
    QVBoxLayout, QHBoxLayout, QGridLayout, QProgressBar, QPushButton
)
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPixmap
from PySide6.QtCore import Qt, QPointF, QRectF, QAbstractNativeEventFilter
import time

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


def _load_binds(path=_BINDS_PATH):
    """Return ({qt_key: action}, {vk_code: action}) for window-focus and global hotkeys."""
    qt_binds = {}
    vk_binds = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                action, key_name = line.split("=", 1)
                action = action.strip()
                key_name = key_name.strip()
                qt_key = _KEY_MAP.get(key_name)
                vk = _VK_MAP.get(key_name)
                if qt_key is not None:
                    qt_binds[qt_key] = action
                if vk is not None:
                    vk_binds[vk] = action
    except FileNotFoundError:
        pass
    return qt_binds, vk_binds


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

        self.setMinimumHeight(260)

    def set_sector_count(self, n: int):
        self._sector_count = max(0, int(n))

    def set_data(self, track_pts, cars, player_car_id=None, player_car_rotation=None):
        self._track_pts = [(float(x), float(z)) for x, z in (track_pts or [])]
        self._cars = cars or []
        self._bounds = self._compute_bounds(self._track_pts) if self._track_pts else None
        self._player_car_id = player_car_id
        self._player_car_rotation = player_car_rotation
        self._pt_index = {pt: i for i, pt in enumerate(self._track_pts)}

        if self._track_pts:
            if self._sector_count > 0:
                self._sector_len = max(1, len(self._track_pts) // self._sector_count)
            else:
                self._sector_count = max(
                    1, (len(self._track_pts) + self._sector_len - 1) // self._sector_len
                )

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

    def set_compare_mode(self, mode: str):
        self._compare_mode = mode
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

            if (self._pt_index.get(closest_pt) < self._pt_index.get(last_point_seen)) & (self._pt_index.get(closest_pt) > (self._pt_index.get(last_point_seen) + self._sector_len)):
                pace_data["last_point_seen"] = closest_pt
                pace_data["last_time_seen"] = now
                pace_data["last_sector"] = None
                continue

            if closest_pt != last_point_seen:
                dx = closest_pt[0] - last_point_seen[0]
                dz = closest_pt[1] - last_point_seen[1]
                distance = (dx * dx + dz * dz) ** 0.5
                speed = distance / dt

                while last_point_seen != closest_pt:
                    points[last_point_seen]["last_speed"] = points[last_point_seen]["speed"]
                    points[last_point_seen]["speed"] = speed

                    idx = self._pt_index.get(last_point_seen)
                    if idx is not None and self._sector_count > 0:
                        s = idx // self._sector_len
                        if s >= self._sector_count:
                            s = self._sector_count - 1

                        prev_s = pace_data.get("last_sector")
                        if prev_s is None:
                            pace_data["last_sector"] = s
                        elif s != prev_s:
                            self._commit_sector(pace_data, prev_s)
                            pace_data["last_sector"] = s

                        sec = pace_data["sectors"][s]
                        sec["sum"] += speed
                        sec["cnt"] += 1

                    last_point_seen = points[last_point_seen]["next_point"]

                pace_data["last_point_seen"] = closest_pt
                pace_data["last_time_seen"] = now

    def compute_track_dominance(self, x, z):
        if self._player_car_id is None:
            return None
        player_pace = self._pace_list.get(self._player_car_id)
        if not player_pace:
            return None

        idx = self._pt_index.get((x, z))
        if idx is None or self._sector_count <= 0:
            return None

        s = idx // self._sector_len
        if s >= self._sector_count:
            s = self._sector_count - 1

        sec = player_pace["sectors"].get(s)
        if not sec:
            return None

        v = float(sec.get("avg", 0.0))
        if v <= 0.0:
            return None

        if self._compare_mode == "self":
            ref = float(sec.get("prev_avg", 0.0))
            if ref <= 0.0:
                return None
        else:
            opponent_speeds = [
                float(pd["sectors"][s]["avg"])
                for pd in self._pace_list.values()
                if pd is not player_pace
                and s in pd["sectors"]
                and pd["sectors"][s]["avg"] > 0.0
            ]
            if not opponent_speeds:
                return None
            ref = max(opponent_speeds) if self._compare_mode == "vs_best" else sum(opponent_speeds) / len(opponent_speeds)

        rel = (v - ref) / max(ref, 1e-6)

        if abs(rel) < 0.03:
            return None

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

    def __init__(self):
        super().__init__()
        self.setObjectName("trackCard")
        self._mode_idx = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header = QHBoxLayout()

        title = QLabel("MAP")
        title.setObjectName("sectionLabel")

        self.track_name = QLabel("—")
        self.track_name.setObjectName("trackName")
        self.track_name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.mode_btn = QPushButton(self._MODE_LABELS[self._MODES[0]])
        self.mode_btn.setObjectName("modeBtn")
        self.mode_btn.setFixedWidth(72)
        self.mode_btn.clicked.connect(self._cycle_mode)

        header.addWidget(title)
        header.addWidget(self.track_name, 1)
        header.addWidget(self.mode_btn)

        self.map = MiniMapWidget()

        root.addLayout(header)
        root.addWidget(self.map, 1)

    def _cycle_mode(self):
        self._mode_idx = (self._mode_idx + 1) % len(self._MODES)
        mode = self._MODES[self._mode_idx]
        self.map.set_compare_mode(mode)
        self.mode_btn.setText(self._MODE_LABELS[mode])

    def update_view(self, d):
        self.track_name.setText(d.get("track_name", "—"))
        self.map.set_data(
            d.get("track_points"),
            d.get("cars_coordinates", []),
            d.get("player_car_id", None),
            d.get("player_car_rotation", None),
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
        self.grip = None
        self.setMinimumSize(100, 72)

    def set_values(self, temp, grip):
        self.temp = temp
        self.grip = grip
        self.update()

    def _temp_color(self):
        if self.temp is None:
            return QColor(55, 55, 62)
        if self.temp < 70:
            return QColor(55, 125, 255)
        if self.temp < 90:
            return QColor(45, 215, 125)
        if self.temp < 105:
            return QColor(255, 160, 25)
        return QColor(255, 55, 55)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)

        # Background
        p.setBrush(QColor(13, 13, 15))
        p.setPen(QPen(QColor(255, 255, 255, 14)))
        p.drawRoundedRect(rect, 3, 3)

        # Left accent bar — temperature colour
        p.setBrush(self._temp_color())
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(rect.left(), rect.top(), 3, rect.height()), 1.5, 1.5)

        # Corner label (FL / FR / RL / RR)
        f = p.font()
        f.setPointSize(7)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 75))
        p.drawText(rect.adjusted(10, 5, -4, 0), Qt.AlignTop | Qt.AlignLeft, self.label)

        # Temperature — dominant value
        temp_text = "—" if self.temp is None else f"{self.temp:.0f}°"
        f.setPointSize(15)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 225))
        p.drawText(rect.adjusted(6, 0, 0, -10), Qt.AlignCenter, temp_text)

        # Wear bar at bottom
        if self.grip is not None:
            w = max(0.0, min(1.0, self.grip))
            bg_bar = QRectF(rect.left() + 10, rect.bottom() - 10, rect.width() - 16, 4)
            fill_bar = QRectF(rect.left() + 10, rect.bottom() - 10, (rect.width() - 16) * w, 4)
            p.setBrush(QColor(255, 255, 255, 18))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(bg_bar, 2, 2)
            if w > 0.5:
                wear_col = QColor(45, 215, 125)
            elif w > 0.25:
                wear_col = QColor(255, 160, 25)
            else:
                wear_col = QColor(255, 55, 55)
            p.setBrush(wear_col)
            p.drawRoundedRect(fill_bar, 2, 2)


# =========================================================
# Tyres Card
# =========================================================

class TiresCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("tiresCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

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
        root.addLayout(grid)

    def update_view(self, d):
        self.fl.set_values(d["front_left_temp"], d["front_left_wear"])
        self.fr.set_values(d["front_right_temp"], d["front_right_wear"])
        self.rl.set_values(d["rear_left_temp"], d["rear_left_wear"])
        self.rr.set_values(d["rear_right_temp"], d["rear_right_wear"])


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
        self.tyres = TiresCard()
        right.addWidget(self.fuel)
        right.addWidget(self.tyres)

        self._binds, vk_binds = _load_binds()
        self._hotkey_ids = {}
        self._hotkey_filter = None
        self._register_global_hotkeys(vk_binds)

        self.setStyleSheet("""
            QWidget {
                background: #070707;
                color: rgba(255,255,255,215);
                font-family: "Segoe UI";
            }
            QLabel { background: transparent; border: none; padding: 0; }

            /* Cards — sharp corners, F1 red left accent bar */
            #fuelCard, #tiresCard, #trackCard {
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
        """)

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
