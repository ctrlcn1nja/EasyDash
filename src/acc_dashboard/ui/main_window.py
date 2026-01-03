import sys
from PySide6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QLabel, QFrame,
    QVBoxLayout, QHBoxLayout, QGridLayout, QProgressBar
)
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPainterPath
from PySide6.QtCore import Qt, QPointF, QRectF


# =========================================================
# Mini Map
# =========================================================

class MiniMapWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._track_pts = []
        self._cars = []
        self._player_car_id = None
        self._pace_list = {} # car_id to list of track points
        self.setMinimumHeight(260)

    def set_data(self, track_pts, cars, player_car_id=None):
        self._track_pts = [(float(x), float(z)) for x, z in (track_pts or [])]
        self._cars = cars or []
        self._bounds = self._compute_bounds(self._track_pts) if self._track_pts else None
        self._player_car_id = player_car_id
        for car in self._cars:
            #print(self._cars, cars)
            car_id = car.get("car_id")
            if car_id is not None and car_id not in self._pace_list:
                points = {}
                for i in range(len(self._track_pts)):
                    points[self._track_pts[i]] = {"speed": 0.0, "next_point": self._track_pts[(i + 1) % len(self._track_pts)]}
                self._pace_list[car_id] = {'points': points, 'last_point_seen': None}
        self.update()

    def find_closest_track_point(self, x, z):
        if not self._track_pts:
            return None
        closest_pt = None
        closest_dist = float('inf')
        for pt in self._track_pts:
            dx = pt[0] - x
            dz = pt[1] - z
            dist = (dx * dx) + (dz * dz)
            if dist < closest_dist:
                closest_dist = dist
                closest_pt = pt
        return closest_pt

    
    def compute_paces(self):
        for car in self._cars:
            car_id = car.get("car_id")
            if car_id is None or car_id not in self._pace_list:
                continue
            pace_data = self._pace_list[car_id]
            points = pace_data['points']
            last_point_seen = pace_data['last_point_seen']

            closest_pt = self.find_closest_track_point(self._cars[car_id].get("x"), self._cars[car_id].get("z"))
            if closest_pt is None:
                continue

            if last_point_seen is None:
                pace_data['last_point_seen'] = closest_pt
                continue
            
            if closest_pt != last_point_seen:
                #print(f"Car {car_id} moved from {last_point_seen} to {closest_pt}")
                speed = (closest_pt[0] - last_point_seen[0])**2 + (closest_pt[1] - last_point_seen[1])**2
                while last_point_seen != closest_pt:
                    points[last_point_seen]['speed'] = speed
                    last_point_seen = points[last_point_seen]['next_point']
                pace_data['last_point_seen'] = closest_pt   


    def compute_car_ahead(self):
        pass



    def compute_track_dominance(self):
        self.compute_paces()     

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

            # ---- guards (avoid exceptions inside paint) ----
            if not self._track_pts or len(self._track_pts) < 2:
                return

            if self._player_car_id is None:
                return

            player_pace = self._pace_list.get(self._player_car_id)
            if not player_pace:
                return

            points = player_pace.get("points", {})
            if not points:
                return

            # If you must compute here, keep it safe (but ideally do it elsewhere)
            self.compute_track_dominance()

            # ---- draw track segments ----
            for (x1, z1), (x2, z2) in zip(self._track_pts, self._track_pts[1:]):
                sp = points.get((x1, z1), {}).get("speed", 0.0)
                col = QColor(120, 255, 180) if sp > 0.0 else QColor(255, 120, 120)
                p.setPen(QPen(col, 3))
                p.drawLine(self._world_to_screen(x1, z1), self._world_to_screen(x2, z2))

            # close the loop (use last segment's color safely)
            x1, z1 = self._track_pts[-1]
            x2, z2 = self._track_pts[0]
            sp = points.get((x1, z1), {}).get("speed", 0.0)
            col = QColor(120, 255, 180) if sp > 0.0 else QColor(255, 120, 120)
            p.setPen(QPen(col, 3))
            p.drawLine(self._world_to_screen(x1, z1), self._world_to_screen(x2, z2))

            # ---- draw cars ----
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
