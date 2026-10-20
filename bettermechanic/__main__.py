"""Start BetterMechanic:  python -m bettermechanic [folder] [--ingest]"""
import json
import os
import sys
import time


def _selftest(app, win, path):
    """`--selftest=<file.json>`: wait for thumbnails, write a report, quit (used to check builds)."""
    from PySide6.QtCore import QTimer
    t0 = time.time()

    def check():
        done = sum(1 for it in win.items if it.tstate != 0)
        if (win.items and done == len(win.items)) or time.time() - t0 > 30:
            from . import __version__
            report = {'version': __version__, 'items': len(win.items), 'thumbs': done,
                      'previews_ok': sum(1 for it in win.items if it.tstate == 2), 'seconds': round(time.time() - t0, 2)}
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(report, fh)
            app.quit()
        else:
            QTimer.singleShot(200, check)

    QTimer.singleShot(200, check)


def main():
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from . import theme
    from .app import MainWindow
    from .config import Config

    if sys.platform == 'win32':
        try:        # own taskbar identity/icon instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('BetterMechanic.App')
        except (AttributeError, OSError):
            pass
    app = QApplication(sys.argv)
    app.setApplicationName('BetterMechanic')
    app.setWindowIcon(QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'icon.png')))
    cfg = Config()
    theme.apply(app, cfg.settings.get('appearance', 'system'))
    win = MainWindow(cfg)
    win.show()
    argv = app.arguments()[1:]
    folders = [a for a in argv if not a.startswith('-') and os.path.isdir(a)]
    if folders:
        win.open_folder(os.path.abspath(folders[0]), ingest='--ingest' in argv)
    test = next((a.split('=', 1)[1] for a in argv if a.startswith('--selftest=')), None)
    if test:
        _selftest(app, win, test)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
