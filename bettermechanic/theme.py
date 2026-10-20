"""Dark theme (photo work wants a neutral, dark surround)."""
from PySide6.QtGui import QColor, QPalette

QSS = """
QWidget { background: #141518; color: #e4e6ea; font-size: 10pt; }
QLabel { background: transparent; }
QToolBar { background: #1b1d21; border: none; border-bottom: 1px solid #2a2d33; spacing: 6px; padding: 5px 8px; }
QLabel#brand { color: #f5a524; font-weight: 800; font-size: 11pt; }
QPushButton, QToolButton { background: #262931; border: 1px solid #343843; border-radius: 6px; padding: 5px 11px; }
QPushButton:hover, QToolButton:hover { background: #2f333d; border-color: #464b57; }
QPushButton:pressed, QToolButton:pressed { background: #1f2229; }
QPushButton#primary { background: #f5a524; color: #15120b; border-color: #f5a524; font-weight: 700; }
QPushButton#primary:hover { background: #ffb63f; }
QPushButton#mini { padding: 2px 8px; font-size: 9pt; }
QPushButton#apply { text-align: left; padding: 5px 9px; }
QPushButton#link { background: transparent; border: none; color: #9db9ff; text-decoration: underline; }
QPushButton#addcol { border: 2px dashed #3a3e48; border-radius: 12px; font-size: 12pt; color: #9aa0aa; }
QToolButton::menu-indicator { image: none; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QTextBrowser { background: #0f1013; border: 1px solid #2f333b;
  border-radius: 5px; padding: 4px 6px; selection-background-color: #2f6fd6; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #f5a524; }
QComboBox QAbstractItemView { background: #1b1d21; selection-background-color: #2f6fd6; }
QListView, QListWidget { background: #141518; border: none; outline: none; }
QListWidget#people { background: #0f1013; border: 1px solid #2f333b; border-radius: 5px; }
QScrollBar:vertical { background: #141518; width: 11px; margin: 0; }
QScrollBar:horizontal { background: #141518; height: 11px; margin: 0; }
QScrollBar::handle { background: #353943; border-radius: 5px; min-height: 30px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QSplitter::handle { background: #2a2d33; }
QStatusBar { background: #1b1d21; border-top: 1px solid #2a2d33; color: #aab0ba; }
QStatusBar QLabel { color: #aab0ba; padding: 0 6px; }
QLabel#h { color: #8b9099; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }
QLabel#group { color: #8b9099; font-size: 8pt; margin-top: 6px; }
QLabel#dim { color: #8b9099; }
QLabel#big { font-size: 13pt; font-weight: 600; }
QLabel#hero { font-size: 28pt; font-weight: 800; color: #f5a524; }
QLabel#fileinfo { color: #cfd3da; line-height: 140%; }
QLabel#kbd { background: #262931; border: 1px solid #3a3e48; border-bottom-width: 2px; border-radius: 4px;
  font-family: Consolas, Menlo, monospace; font-weight: 700; color: #e4e6ea; }
QFrame#slot { border-radius: 6px; background: transparent; }
QFrame#slot:hover { background: #22252b; }
QFrame#slot[state="on"] { background: #f5a524; }
QFrame#slot[state="on"] QLabel { color: #15120b; font-weight: 700; }
QFrame#slot[state="on"] QLabel#kbd { background: #15120b; color: #f5a524; border-color: #15120b; }
QFrame#slot[state="part"] { background: rgba(245, 165, 36, 70); }
QFrame#slot[state="empty"] QLabel { color: #5b606a; }
QFrame#slot[state="empty"] QLabel#kbd { color: #6b707a; }
QToolButton#editslot { background: transparent; border: none; color: #6b707a; padding: 0 3px; }
QToolButton#editslot:hover { color: #f5a524; }
QToolButton#star { background: transparent; border: none; color: #4a4e57; font-size: 15pt; padding: 0 1px; }
QToolButton#star[on="true"] { color: #f5a524; }
QToolButton:checked { background: #5a1f22; border-color: #e5484d; }
QFrame#pcol { background: #1b1d21; border: 1px solid #2f333b; border-radius: 14px; }
QFrame#pcol[active="true"] { border: 2px solid #f5a524; }
QLineEdit#ptitle { font-size: 15pt; font-weight: 800; border: 2px solid #4a4e57; border-radius: 18px;
  padding: 4px 14px; background: #141518; }
QLabel#pill { background: #f5a524; color: #15120b; border-radius: 8px; padding: 2px 8px; font-weight: 800; font-size: 8pt; }
QFrame#banner { background: #3a2a0b; border-bottom: 1px solid #6b4d14; }
QFrame#banner QLabel { color: #ffd28a; }
QProgressBar { background: #0f1013; border: 1px solid #2f333b; border-radius: 5px; height: 14px; text-align: center; }
QProgressBar::chunk { background: #f5a524; border-radius: 4px; }
QCheckBox::indicator { width: 15px; height: 15px; }
QSlider::groove:horizontal { height: 4px; background: #343843; border-radius: 2px; }
QSlider::handle:horizontal { background: #f5a524; width: 14px; margin: -6px 0; border-radius: 7px; }
QMenu { background: #1b1d21; border: 1px solid #343843; }
QMenu::item:selected { background: #2f6fd6; }
QToolTip { background: #24272e; color: #e4e6ea; border: 1px solid #3a3e48; }
"""


def apply(app):
    app.setStyle('Fusion')
    pal = QPalette()
    for role, col in ((QPalette.Window, '#141518'), (QPalette.WindowText, '#e4e6ea'), (QPalette.Base, '#0f1013'),
                      (QPalette.AlternateBase, '#1b1d21'), (QPalette.Text, '#e4e6ea'), (QPalette.Button, '#262931'),
                      (QPalette.ButtonText, '#e4e6ea'), (QPalette.Highlight, '#2f6fd6'),
                      (QPalette.HighlightedText, '#ffffff'), (QPalette.ToolTipBase, '#24272e'),
                      (QPalette.ToolTipText, '#e4e6ea'), (QPalette.PlaceholderText, '#6b707a')):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
