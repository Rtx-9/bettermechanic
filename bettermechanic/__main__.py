"""Start BetterMechanic:  python -m bettermechanic [folder]"""
import os
import sys


def main():
    from PySide6.QtWidgets import QApplication

    from . import theme
    from .app import MainWindow
    from .config import Config

    app = QApplication(sys.argv)
    app.setApplicationName('BetterMechanic')
    cfg = Config()
    theme.apply(app, cfg.settings.get('appearance', 'system'))
    win = MainWindow(cfg)
    win.show()
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    if args and os.path.isdir(args[0]):
        win.open_folder(os.path.abspath(args[0]), ingest='--ingest' in sys.argv)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
