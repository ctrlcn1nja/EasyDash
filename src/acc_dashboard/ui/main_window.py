import sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QLabel, QFrame,
    QVBoxLayout, QHBoxLayout, QGridLayout, QProgressBar
)
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPainterPath
from PySide6.QtCore import Qt, QPointF, QRectF
import time 


# =========================================================
# Mini Map
# =========================================================

import time

from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtCore import Qt, QPointF


class MiniMapWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._track_pts = []
        self._cars = []
        self._bounds = None
        self._player_car_id = None

        # car_id -> per-car pace data
        self._pace_list = {}

        self.clock = time.perf_counter

        # sector config
        self._sector_len = 10
        self._sector_count = 0
        self._pt_index = {}

        self.setMinimumHeight(260)

    def set_sector_count(self, n: int):
        self._sector_count = max(0, int(n))

    def set_data(self, track_pts, cars, player_car_id=None):
        self._track_pts = [(float(x), float(z)) for x, z in (track_pts or [])]
        self._cars = cars or []
        self._bounds = self._compute_bounds(self._track_pts) if self._track_pts else None
        self._player_car_id = player_car_id

        # point -> index
        self._pt_index = {pt: i for i, pt in enumerate(self._track_pts)}

        # sector sizing
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
                # per-point map (linked list)
                points = {}
                for i in range(len(self._track_pts)):
                    pt = self._track_pts[i]
                    points[pt] = {
                        "speed": 0.0,
                        "last_speed": 0.0,
                        "next_point": self._track_pts[(i + 1) % len(self._track_pts)],
                    }

                # per-sector stats:
                # avg = latest completed sector value
                # prev_avg = previous completed value (for delta)
                sectors = {}
                for s in range(self._sector_count):
                    sectors[s] = {
                        "avg": 0.0,
                        "prev_avg": 0.0,
                        "sum": 0.0,
                        "cnt": 0,
                    }

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
            dist = (dx * dx) + (dz * dz)
            if dist < closest_dist:
                closest_dist = dist
                closest_pt = pt
        return closest_pt

    def _commit_sector(self, pace_data, sector_id: int):
        """Commit the running sum/cnt into avg, shifting avg -> prev_avg."""
        if sector_id is None:
            return
        sec = pace_data["sectors"].get(sector_id)
        if not sec:
            return
        if sec["cnt"] <= 0:
            return

        new_avg = sec["sum"] / max(sec["cnt"], 1)
        sec["prev_avg"] = sec["avg"]
        sec["avg"] = new_avg
        sec["sum"] = 0.0
        sec["cnt"] = 0

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

            # First observation
            if last_point_seen is None:
                pace_data["last_point_seen"] = closest_pt
                pace_data["last_time_seen"] = now
                pace_data["last_sector"] = None
                continue

            if dt <= 1e-6:
                continue
            
            if (self._pt_index.get(closest_pt) < self._pt_index.get(last_point_seen)) & (self._pt_index.get(closest_pt) > (self._pt_index.get(last_point_seen) + self._sector_len)):
                # jumped backwards or too far forwards - reset
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
                    # per-point
                    points[last_point_seen]["last_speed"] = points[last_point_seen]["speed"]
                    points[last_point_seen]["speed"] = speed

                    # sector id for this point
                    idx = self._pt_index.get(last_point_seen)
                    if idx is not None and self._sector_count > 0:
                        s = idx // self._sector_len
                        if s >= self._sector_count:
                            s = self._sector_count - 1

                        prev_s = pace_data.get("last_sector")
                        if prev_s is None:
                            pace_data["last_sector"] = s
                        elif s != prev_s:
                            # leaving prev sector -> commit it
                            self._commit_sector(pace_data, prev_s)
                            pace_data["last_sector"] = s

                        # accumulate current sector
                        sec = pace_data["sectors"][s]
                        sec["sum"] += speed
                        sec["cnt"] += 1

                    last_point_seen = points[last_point_seen]["next_point"]

                pace_data["last_point_seen"] = closest_pt
                pace_data["last_time_seen"] = now

    def compute_track_dominance(self, x, z):
        NEUTRAL = QColor(200, 200, 200)

        if self._player_car_id is None:
            return NEUTRAL
        player_pace = self._pace_list.get(self._player_car_id)
        if not player_pace:
            return NEUTRAL

        idx = self._pt_index.get((x, z))
        if idx is None or self._sector_count <= 0:
            return NEUTRAL

        s = idx // self._sector_len
        if s >= self._sector_count:
            s = self._sector_count - 1

        sec = player_pace["sectors"].get(s)
        if not sec:
            return NEUTRAL

        v = float(sec.get("avg", 0.0))
        v_prev = float(sec.get("prev_avg", 0.0))

        # Need at least two completed passes of that sector to compare
        # if v <= 0.0 or v_prev <= 0.0:
        #     return NEUTRAL

        rel = (v - v_prev) / max(v_prev, 1e-6)

        dead = 0.03
        if abs(rel) < dead:
            return NEUTRAL

        sat = 0.10
        t = max(-1.0, min(1.0, rel / sat))
        a = abs(t)

        base_r, base_g, base_b = 200, 200, 200
        if t > 0:
            target_r, target_g, target_b = 100, 255, 100
        else:
            target_r, target_g, target_b = 255, 100, 100

        r = int(base_r + (target_r - base_r) * a)
        g = int(base_g + (target_g - base_g) * a)
        b = int(base_b + (target_b - base_b) * a)
        return QColor(r, g, b)

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
        sy = (z - cz) * s + self.height() / 2
        sy = self.height() - sy

        return QPointF(sx, sy)

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)

            if not self._track_pts or len(self._track_pts) < 2:
                return
            if self._player_car_id is None:
                return
            if self._player_car_id not in self._pace_list:
                return

            # draw track segments
            for (x1, z1), (x2, z2) in zip(self._track_pts, self._track_pts[1:]):
                col = self.compute_track_dominance(x1, z1)
                p.setPen(QPen(col, 3))
                p.drawLine(self._world_to_screen(x1, z1), self._world_to_screen(x2, z2))

            # close loop
            x1, z1 = self._track_pts[-1]
            x2, z2 = self._track_pts[0]
            col = self.compute_track_dominance(x1, z1)
            p.setPen(QPen(col, 3))
            p.drawLine(self._world_to_screen(x1, z1), self._world_to_screen(x2, z2))

            # draw cars
            for car in self._cars:
                if car.get("x") == 0 and car.get("z") == 0:
                    continue
                pt = self._world_to_screen(car["x"], car["z"])
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(120, 255, 180) if car.get("is_player") else QColor(255, 255, 255, 160))
                r = 6 if car.get("is_player") else 4
                p.drawEllipse(pt, r, r)

        finally:
            if p.isActive():
                p.end()
# =========================================================
# Track Card
# =========================================================

class TrackCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("trackCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        self.title = QLabel("Track")
        self.title.setObjectName("cardTitle")
        self.track_name = QLabel("—")
        self.track_name.setObjectName("cardSubtitle")
        self.track_name.setAlignment(Qt.AlignRight)

        header.addWidget(self.title)
        header.addWidget(self.track_name)

        self.map = MiniMapWidget()

        root.addLayout(header)
        root.addWidget(self.map, 1)

    def update_view(self, d):
        self.track_name.setText(d.get("track_name", "—"))
        self.map.set_data(d.get("track_points"), d.get("cars_coordinates", []), d.get("player_car_id", None))
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
        self.setMinimumSize(120, 80)

    def set_values(self, temp, grip):
        self.temp = temp
        self.grip = grip
        self.update()

    def _temp_color(self):
        if self.temp is None:
            return QColor(255, 255, 255, 20)
        if self.temp < 70:
            return QColor(80, 160, 255, 150)
        if self.temp < 90:
            return QColor(120, 255, 180, 160)
        if self.temp < 105:
            return QColor(255, 200, 120, 170)
        return QColor(255, 120, 120, 180)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        p.setBrush(self._temp_color())
        p.setPen(QPen(QColor(255, 255, 255, 40)))
        p.drawRoundedRect(rect, 14, 14)

        p.setPen(Qt.white)
        p.drawText(rect.adjusted(10, 6, -10, -6), Qt.AlignTop | Qt.AlignLeft, self.label)

        temp_text = "—" if self.temp is None else f"{self.temp:.0f}°"
        f = p.font()
        f.setPointSize(14)
        f.setBold(True)
        p.setFont(f)
        p.drawText(rect, Qt.AlignCenter, temp_text)

        if self.grip is not None:
            w = max(0.0, min(1.0, self.grip))
            bar = QRectF(rect.left() + 10, rect.bottom() - 14, (rect.width() - 20) * w, 6)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(120, 255, 180) if w > 0.4 else QColor(255, 120, 120))
            p.drawRoundedRect(bar, 3, 3)


# =========================================================
# Tyres Card
# =========================================================

class TiresCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("tiresCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(QLabel("Tyres"))
        header.addStretch()
        root.addLayout(header)

        grid = QGridLayout()
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
# Fuel Card (FINAL VERSION)
# =========================================================

class FuelCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("fuelCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        self.title = QLabel("Fuel")
        self.title.setObjectName("cardTitle")
        header.addWidget(self.title)
        header.addStretch()
        root.addLayout(header)

        root.addWidget(self._divider())

        # Small fuel left + bar
        top = QHBoxLayout()
        self.fuel_left_small = QLabel("— L")
        self.fuel_left_small.setObjectName("fuelLeftSmall")

        self.bar = QProgressBar()
        self.bar.setObjectName("fuelBar")
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(14)

        top.addWidget(self.fuel_left_small, 0)
        top.addWidget(self.bar, 1)
        root.addLayout(top)

        # Big info
        big = QGridLayout()
        self.need_big = QLabel("Need: — L")
        self.need_big.setObjectName("fuelNeedBig")

        self.margin_big = QLabel("Margin: — L")
        self.margin_big.setObjectName("fuelMarginBig")
        self.margin_big.setAlignment(Qt.AlignRight)

        big.addWidget(self.need_big, 0, 0)
        big.addWidget(self.margin_big, 0, 1)
        root.addLayout(big)

        # Secondary
        secondary = QHBoxLayout()
        self.fuel_per_lap = QLabel("— L / lap")
        self.fuel_per_lap.setObjectName("valueLine")
        secondary.addWidget(self.fuel_per_lap)
        secondary.addStretch()
        root.addLayout(secondary)

        self._max_seen = 1.0

    def _divider(self):
        d = QFrame()
        d.setObjectName("divider")
        d.setFixedHeight(1)
        return d

    def update_view(self, d):
        fuel = d["fuel_left"]
        need = d["fuel_needed_to_finish"]
        margin = d["margin"]

        self.fuel_left_small.setText(f"{fuel:.1f} L")
        self.fuel_per_lap.setText(f"{d['fuel_per_lap']:.2f} L / lap")
        self.need_big.setText(f"Need: {need:.1f} L")

        self._max_seen = max(self._max_seen, fuel, need, 1.0)
        self.bar.setValue(int((fuel / self._max_seen) * 1000))

        self.margin_big.setText(f"Margin: {margin:+.1f} L")
        self.margin_big.setProperty("state", "good" if margin >= 0 else "bad")
        self.margin_big.style().unpolish(self.margin_big)
        self.margin_big.style().polish(self.margin_big)


# =========================================================
# Main Window
# =========================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EasyDash")
        self.resize(920, 480)

        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        title = QLabel("EasyDash")
        title.setObjectName("appTitle")
        root.addWidget(title)

        main = QHBoxLayout()
        root.addLayout(main, 1)

        self.track = TrackCard()
        main.addWidget(self.track, 2)

        right = QVBoxLayout()
        right.setSpacing(14)
        main.addLayout(right, 1)

        self.fuel = FuelCard()
        self.tyres = TiresCard()

        right.addWidget(self.fuel)
        right.addWidget(self.tyres)

        self.setStyleSheet("""
            QWidget { background: #0f1116; color: rgba(255,255,255,230); }
            QLabel { background: transparent; border: none; padding: 0; }

            #appTitle { font-size: 20px; font-weight: 800; }

            #fuelCard, #tiresCard, #trackCard {
                background: rgba(18,18,22,255);
                border: 1px solid rgba(255,255,255,25);
                border-radius: 16px;
            }

            #cardTitle { font-size: 14px; font-weight: 800; }
            #cardSubtitle { font-size: 10px; color: rgba(255,255,255,120); }
            #valueLine { font-size: 12px; color: rgba(255,255,255,210); }

            #fuelLeftSmall { font-size: 14px; font-weight: 800; }
            #fuelNeedBig, #fuelMarginBig { font-size: 16px; font-weight: 900; }

            QLabel#fuelMarginBig[state="good"] { color: rgba(120,255,180,235); }
            QLabel#fuelMarginBig[state="bad"]  { color: rgba(255,120,140,235); }

            #fuelBar {
                background: rgba(255,255,255,10);
                border: 1px solid rgba(255,255,255,18);
                border-radius: 7px;
            }
            #fuelBar::chunk {
                background: rgba(120,255,180,200);
                border-radius: 7px;
            }

            #divider { background: rgba(255,255,255,22); }
        """)


# =========================================================
# Run
# =========================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
