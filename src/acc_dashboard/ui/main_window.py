from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGridLayout
)
from PySide6.QtCore import Qt


class TiresCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tiresCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        self.title = QLabel("Tyres")
        self.title.setObjectName("cardTitle")
        self.status = QLabel("Grip est.")
        self.status.setObjectName("cardSubtitle")
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.title, 1)
        header.addWidget(self.status, 1)

        root.addLayout(header)
        root.addWidget(self._divider())

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        # FL / FR
        self.fl = QLabel("FL: —")
        self.fr = QLabel("FR: —")
        # RL / RR
        self.rl = QLabel("RL: —")
        self.rr = QLabel("RR: —")

        for w in (self.fl, self.fr, self.rl, self.rr):
            w.setObjectName("valueLine")
            w.setTextFormat(Qt.PlainText)

        grid.addWidget(self.fl, 0, 0)
        grid.addWidget(self.fr, 0, 1)
        grid.addWidget(self.rl, 1, 0)
        grid.addWidget(self.rr, 1, 1)

        root.addLayout(grid)

        root.addWidget(self._divider())

        self.hint = QLabel("Tip: keep 27.3–27.7 PSI hot, 80–95°C core")
        self.hint.setObjectName("cardHint")
        root.addWidget(self.hint)

    def _divider(self) -> QFrame:
        d = QFrame()
        d.setObjectName("divider")
        d.setFixedHeight(1)
        d.setFrameShape(QFrame.HLine)
        return d

    @staticmethod
    def _fmt_line(label: str, temp: float, grip: float) -> str:
        # grip is 0..1 where 1 is "new"
        return f"{label}: {temp:>5.1f}°C   grip {grip*100:>5.1f}%"

    def update_view(self, d: dict) -> None:
        # Expect keys from your process_tires(sm) return dict
        self.fl.setText(self._fmt_line("FL", d["front_left_temp"],  d["front_left_wear"]))
        self.fr.setText(self._fmt_line("FR", d["front_right_temp"], d["front_right_wear"]))
        self.rl.setText(self._fmt_line("RL", d["rear_left_temp"],   d["rear_left_wear"]))
        self.rr.setText(self._fmt_line("RR", d["rear_right_temp"],  d["rear_right_wear"]))


class FuelCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fuelCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        self.title = QLabel("Fuel")
        self.title.setObjectName("cardTitle")
        self.status = QLabel("ACC")
        self.status.setObjectName("cardSubtitle")
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self.title, 1)
        header.addWidget(self.status, 1)

        self.fuel_left = QLabel("Fuel left: —")
        self.fuel_per_lap = QLabel("Fuel / lap: —")
        self.last_lap = QLabel("Last lap: —")
        self.need = QLabel("Need to finish: —")
        self.margin = QLabel("Margin: —")

        for w in (self.fuel_left, self.fuel_per_lap, self.last_lap, self.need, self.margin):
            w.setObjectName("valueLine")

        root.addLayout(header)
        root.addWidget(self._divider())
        root.addWidget(self.fuel_left)
        root.addWidget(self.fuel_per_lap)
        root.addWidget(self.last_lap)
        root.addWidget(self._divider())
        root.addWidget(self.need)
        root.addWidget(self.margin)

    def _divider(self) -> QFrame:
        d = QFrame()
        d.setObjectName("divider")
        d.setFixedHeight(1)
        d.setFrameShape(QFrame.HLine)
        return d

    def update_view(self, d: dict) -> None:
        self.fuel_left.setText(f"Fuel left: {d['fuel_left']:.1f} L")
        self.fuel_per_lap.setText(f"Fuel / lap: {d['fuel_per_lap']:.2f} L")
        self.last_lap.setText(f"Last lap: {int(d['last_lap_time'])} s")
        self.need.setText(f"Need to finish: {d['fuel_needed_to_finish']:.1f} L")

        m = d.get("margin")
        if m is None:
            self.margin.setText("Margin: —")
            self.margin.setStyleSheet("")
        else:
            self.margin.setText(f"Margin: {m:+.1f} L")
            # subtle color
            if m >= 0:
                self.margin.setStyleSheet("color: rgba(120, 255, 180, 235); font-weight: 700;")
            else:
                self.margin.setStyleSheet("color: rgba(255, 120, 140, 235); font-weight: 700;")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EasyDash")
        self.resize(520, 320)

        central = QWidget(self)
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        title = QLabel("EasyDash")
        title.setObjectName("appTitle")
        layout.addWidget(title)

        # Content row: Fuel (left) + Tyres (right)
        top_row = QHBoxLayout()
        top_row.setSpacing(14)

        self.fuel_card = FuelCard(self)
        self.tires_card = TiresCard(self)

        top_row.addWidget(self.fuel_card, 1)
        top_row.addWidget(self.tires_card, 1)

        layout.addLayout(top_row)

        self.setStyleSheet("""
            QWidget { background: #0f1116; color: rgba(255,255,255,230); }
            #appTitle { font-size: 20px; font-weight: 800; margin-bottom: 6px; }

            #fuelCard, #tiresCard {
                background: rgba(18,18,22,255);
                border: 1px solid rgba(255,255,255,25);
                border-radius: 16px;
            }

            #cardHint { font-size: 10px; color: rgba(255,255,255,120); }
            #cardTitle { font-size: 14px; font-weight: 800; }
            #cardSubtitle { font-size: 10px; color: rgba(255,255,255,120); }
            #valueLine { font-size: 12px; color: rgba(255,255,255,210); }
            #divider { background: rgba(255,255,255,22); }
        """)

