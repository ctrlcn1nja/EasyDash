import sys
from PySide6.QtWidgets import QApplication

from .controller import AppController
from .telemetry.shared_memory import Telemetry
from .ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)

    telemetry = Telemetry()
    window = MainWindow()

    controller = AppController(telemetry, window)
    controller.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
