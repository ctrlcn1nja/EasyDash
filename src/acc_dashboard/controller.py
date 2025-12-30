from PySide6.QtCore import QTimer
from .processors.fuel import process_fuel
from .processors.tires import process_tires
from .processors.track import process_track


class AppController:
    def __init__(self, telemetry, window):
        self.telemetry = telemetry
        self.window = window

        self.timer = QTimer()
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.tick)

    def start(self):
        self.telemetry.connect()
        self.window.show()
        self.timer.start()

    def tick(self):
        sm = self.telemetry.get_sm()
        if sm is None:
            return
        d = process_fuel(sm)
        self.window.fuel.update_view(d)
        tire_data = process_tires(sm)
        self.window.tyres.update_view(tire_data)
        track_data = process_track(sm)
        self.window.track.update_view(track_data)