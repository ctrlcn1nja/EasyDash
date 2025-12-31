# quick_minimap_preview.py
# Run: python quick_minimap_preview.py
# Expects: car_coordinates.json in the same folder

import json
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QPainterPath
from PySide6.QtCore import Qt, QPointF


def load_points_from_file(path: Path):
    """
    Accepts either:
      1) a JSON array: [ {"x":..,"y":..,"z":..}, ... ]
      2) or an object: { "track": "...", "points": [ {"x":..,"y":..,"z":..}, ... ] }
      3) or: { "points": [ [x,z], [x,z], ... ] }
    Returns list[(x, z)].
    """
    raw = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(raw, dict):
        pts = raw.get("points", raw.get("points_Barcelona", raw.get("coords")))
    else:
        pts = raw

    if not isinstance(pts, list) or len(pts) == 0:
        raise ValueError("Could not find a non-empty points list in JSON.")

    out = []
    # points as dicts with x,z
    if isinstance(pts[0], dict):
        for p in pts:
            out.append((float(p["x"]), float(p["z"])))
        return out

    # points as [x,z]
    if isinstance(pts[0], (list, tuple)) and len(pts[0]) >= 2:
        for p in pts:
            out.append((float(p[0]), float(p[1])))
        return out

    raise ValueError("Unsupported point format. Use dicts {x,z} or pairs [x,z].")


class MiniMapWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pts_world = []   # list[(x,z)]
        self._bounds = None    # (minx,maxx,minz,maxz)
        self.setMinimumSize(600, 600)

    def set_points(self, pts_world):
        self._pts_world = [(float(x), float(z)) for x, z in pts_world]
        self._bounds = self._compute_bounds(self._pts_world) if self._pts_world else None
        self.update()

    @staticmethod
    def _compute_bounds(pts):
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        return (min(xs), max(xs), min(zs), max(zs))

    def _world_to_screen(self, x, z):
        if not self._bounds:
            return QPointF(0, 0)

        minx, maxx, minz, maxz = self._bounds
        w = maxx - minx
        h = maxz - minz
        if w <= 1e-6 or h <= 1e-6:
            return QPointF(0, 0)

        pad = 18
        W = max(1, self.width() - 2 * pad)
        H = max(1, self.height() - 2 * pad)

        # uniform scale, keep aspect ratio
        s = min(W / w, H / h)

        # center the track
        cx = (minx + maxx) / 2.0
        cz = (minz + maxz) / 2.0

        sx = (x - cx) * s + self.width() / 2.0
        sy = (z - cz) * s + self.height() / 2.0

        # flip Y so it looks natural on screen
        sy = self.height() - sy
        return QPointF(sx, sy)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # background
        p.fillRect(self.rect(), QColor(15, 17, 22))

        if len(self._pts_world) < 2:
            p.setPen(QPen(QColor(255, 255, 255, 160)))
            p.drawText(self.rect(), Qt.AlignCenter, "No points loaded.")
            return

        # track polyline
        path = QPainterPath()
        first = self._world_to_screen(*self._pts_world[0])
        path.moveTo(first)
        for x, z in self._pts_world[1:]:
            path.lineTo(self._world_to_screen(x, z))

        p.setPen(QPen(QColor(255, 255, 255, 110), 3))
        p.drawPath(path)

        # start marker (green) + end marker (red)
        start = self._world_to_screen(*self._pts_world[0])
        end = self._world_to_screen(*self._pts_world[-1])

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(120, 255, 180, 230)))
        p.drawEllipse(start, 7, 7)

        p.setBrush(QBrush(QColor(255, 120, 140, 230)))
        p.drawEllipse(end, 7, 7)

        # sample dots (subtle)
        p.setBrush(QBrush(QColor(255, 255, 255, 120)))
        step = max(1, len(self._pts_world) // 200)  # cap dot count
        for i in range(0, len(self._pts_world), step):
            pt = self._world_to_screen(*self._pts_world[i])
            p.drawEllipse(pt, 2.2, 2.2)


class MainWindow(QMainWindow):
    def __init__(self, points):
        super().__init__()
        self.setWindowTitle("ACC Track Map Preview (from car_coordinates.json)")

        central = QWidget(self)
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel(f"Loaded {len(points)} points")
        title.setStyleSheet("color: rgba(255,255,255,210); font-size: 14px; font-weight: 700;")
        layout.addWidget(title)

        self.map = MiniMapWidget(self)
        self.map.set_points(points)
        layout.addWidget(self.map, 1)


def main():
    path = Path(__file__).resolve().parent / "car_coordinates.json"
    if not path.exists():
        print(f"ERROR: {path} not found.")
        print("Create it next to this script. Example format:")
        print('[{"x":-955.9,"y":1.29,"z":-1354.1}, ... ]')
        sys.exit(1)

    points = load_points_from_file(path)

    app = QApplication(sys.argv)
    w = MainWindow(points)
    w.resize(760, 820)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
