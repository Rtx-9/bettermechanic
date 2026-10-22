"""Appearance: semantic colours for light and dark mode, system font, style sheet.

Loosely follows Apple's Human Interface Guidelines: system colours, an accent
colour for selection and default buttons, quiet toolbars, a players panel
and an inspector made of grouped sections. The photo preview always
stays dark so it never competes with the pictures.
"""
from __future__ import annotations

import os
import sys
import tempfile
from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

DARK = {
    'bg': '#1c1c1e',          # content (contact sheet)
    'window': '#2a2a2d',      # toolbar / title area
    'sidebar': '#232326',
    'inspector': '#232326',
    'card': '#2c2c2f',        # grouped section / thumbnail cell
    'cell': '#262629',
    'control': '#3a3a3d',
    'control_hover': '#48484b',
    'field': '#1c1c1e',
    'field_border': '#424246',
    'separator': '#3a3a3d',
    'label': '#f5f5f7',
    'secondary': '#a1a1a6',
    'tertiary': '#6c6c70',
    'accent': '#0a84ff',
    'accent_text': '#ffffff',
    'accent_soft': 'rgba(10, 132, 255, 0.24)',
    'hover': 'rgba(255, 255, 255, 0.06)',
    'orange': '#ff9f0a', 'red': '#ff453a', 'green': '#30d158', 'yellow': '#ffd60a',
    'blue': '#0a84ff', 'purple': '#bf5af2',
    'shadow': 'rgba(0, 0, 0, 0.5)',
}

LIGHT = {
    'bg': '#ffffff',
    'window': '#f6f6f6',
    'sidebar': '#efeff1',
    'inspector': '#f6f6f6',
    'card': '#ffffff',
    'cell': '#f2f2f5',
    'control': '#ffffff',
    'control_hover': '#f0f0f3',
    'field': '#ffffff',
    'field_border': '#c9c9ce',
    'separator': '#dcdce0',
    'label': '#1d1d1f',
    'secondary': '#6e6e73',
    'tertiary': '#a8a8ad',
    'accent': '#007aff',
    'accent_text': '#ffffff',
    'accent_soft': 'rgba(0, 122, 255, 0.16)',
    'hover': 'rgba(0, 0, 0, 0.05)',
    'orange': '#ff9500', 'red': '#ff3b30', 'green': '#34c759', 'yellow': '#ffcc00',
    'blue': '#007aff', 'purple': '#af52de',
    'shadow': 'rgba(0, 0, 0, 0.18)',
}

C = dict(DARK)            # current tokens (read by painting code)
IS_DARK = True


def qc(key, alpha=None):
    """Token as QColor (handles rgba(...) tokens)."""
    v = C[key]
    if v.startswith('rgba'):
        r, g, b, a = [x.strip() for x in v[5:-1].split(',')]
        col = QColor(int(r), int(g), int(b), round(float(a) * 255))
    else:
        col = QColor(v)
    if alpha is not None:
        col.setAlphaF(alpha)
    return col


def label_colors():
    return {'red': qc('red'), 'yellow': qc('yellow'), 'green': qc('green'), 'blue': qc('blue'), 'purple': qc('purple')}


QSS = Template("""
QWidget { color: $label; font-size: ${fs}pt; }
QMainWindow, QDialog { background: $window; }
QLabel { background: transparent; }
QToolTip { background: $card; color: $label; border: 1px solid $separator; padding: 4px 6px; border-radius: 6px; }

/* toolbar: quiet, borderless items */
QToolBar { background: $window; border: none; border-bottom: 1px solid $separator; spacing: 4px; padding: 6px 10px; }
QToolBar QToolButton { background: transparent; border: none; border-radius: 6px; padding: 5px 7px; color: $label; }
QToolBar QToolButton:hover { background: $hover; }
QToolBar QToolButton:pressed { background: $control_hover; }
QToolBar QToolButton:checked { background: $control; }
QLabel#title { font-weight: 600; font-size: ${fs_title}pt; }
QLabel#subtitle { color: $secondary; font-size: ${fs_small}pt; }

/* segmented control */
QFrame#segmented { background: $control; border-radius: 7px; padding: 2px; }
QFrame#segmented QToolButton { background: transparent; border-radius: 5px; padding: 3px 12px; }
QFrame#segmented QToolButton:checked { background: $card; border: 1px solid $separator; }

/* buttons */
QPushButton { background: $control; border: 1px solid $field_border; border-radius: 6px; padding: 5px 14px; min-height: 18px; }
QPushButton:hover { background: $control_hover; }
QPushButton:pressed { background: $separator; }
QPushButton#primary { background: $accent; color: $accent_text; border: 1px solid $accent; font-weight: 600; }
QPushButton#primary:hover { border-color: $label; }
QPushButton:disabled { color: $tertiary; }
QPushButton#plain { background: transparent; border: none; color: $accent; padding: 4px 6px; text-align: left; }
QPushButton#plain:hover { background: $hover; }
QPushButton#row { background: transparent; border: none; border-radius: 6px; padding: 5px 8px; text-align: left; }
QPushButton#row:hover { background: $hover; }
QPushButton#addcol { background: transparent; border: 2px dashed $separator; border-radius: 12px; color: $secondary; }
QToolButton { background: $control; border: 1px solid $field_border; border-radius: 6px; padding: 3px 8px; }
QToolButton:hover { background: $control_hover; }
QToolButton::menu-indicator { image: none; }

/* text fields */
QLineEdit, QPlainTextEdit, QSpinBox, QTextBrowser {
  background: $field; border: 1px solid $field_border; border-radius: 6px; padding: 4px 7px;
  selection-background-color: $accent; selection-color: $accent_text; }
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus { border: 2px solid $accent; padding: 3px 6px; }
QLineEdit#search { border-radius: 8px; padding-left: 4px; background: $control; border-color: transparent; }
QLineEdit#search:focus { background: $field; }
QComboBox { background: $control; border: 1px solid $field_border; border-radius: 6px; padding: 4px 26px 4px 9px; min-height: 18px; }
QComboBox:hover { background: $control_hover; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url("$chevron"); width: 10px; height: 10px; margin-right: 8px; }
QSpinBox { padding-right: 22px; }
QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin: border; width: 18px; border: none; background: transparent; }
QSpinBox::up-button { subcontrol-position: top right; }
QSpinBox::down-button { subcontrol-position: bottom right; }
QSpinBox::up-arrow { image: url("$chevron_up"); width: 8px; height: 8px; }
QSpinBox::down-arrow { image: url("$chevron"); width: 8px; height: 8px; }
QComboBox QAbstractItemView { background: $card; border: 1px solid $separator; border-radius: 8px; padding: 4px;
  selection-background-color: $accent; selection-color: $accent_text; outline: none; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator { width: 15px; height: 15px; border-radius: 4px; border: 1px solid $field_border; background: $field; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QCheckBox::indicator:indeterminate { background: $accent_soft; border-color: $accent; }

/* lists & scroll bars */
QListView, QListWidget { background: $bg; border: none; outline: none; }
QListView#grid { background: $bg; }
QListView#strip { background: #111113; }
QListWidget#people { background: $field; border: 1px solid $field_border; border-radius: 6px; padding: 2px; }
QListWidget#people::item { padding: 3px 6px; border-radius: 4px; }
QListWidget#people::item:selected { background: $accent; color: $accent_text; }
QListWidget#presetlist { background: $sidebar; border-radius: 8px; padding: 4px; }
QListWidget#presetlist::item { padding: 6px 8px; border-radius: 6px; }
QListWidget#presetlist::item:selected { background: $accent; color: $accent_text; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: $tertiary; border-radius: 3px; min-height: 30px; min-width: 30px; }
QScrollBar::handle:hover { background: $secondary; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QSplitter::handle { background: $separator; }

/* sidebar (source list) */
QWidget#sidebar { background: $sidebar; }
QFrame#teams, QFrame#teams QScrollArea, QFrame#teams QScrollArea > QWidget > QWidget { background: $sidebar; }
QLabel#section { color: $secondary; font-weight: 600; font-size: ${fs_small}pt; padding: 10px 2px 3px 2px; }
QLabel#hint, QLabel#dim { color: $tertiary; font-size: ${fs_small}pt; }
QLabel#group { color: $tertiary; font-size: ${fs_small}pt; padding: 6px 2px 2px 2px; }
QLabel#kbd { background: $control; border: 1px solid $field_border; border-radius: 5px;
  font-family: "Cascadia Mono", Consolas, Menlo, monospace; font-size: ${fs_small}pt; font-weight: 600; color: $secondary; }
QFrame#slot { border-radius: 6px; background: transparent; }
QFrame#slot:hover { background: $hover; }
QFrame#slot[state="on"] { background: $accent; }
QFrame#slot[state="on"] QLabel { color: $accent_text; font-weight: 600; }
QFrame#slot[state="on"] QLabel#kbd { background: rgba(255,255,255,0.22); border-color: transparent; color: $accent_text; }
QFrame#slot[state="part"] { background: $accent_soft; }
QFrame#slot[state="empty"] QLabel { color: $tertiary; }
QToolButton#editslot { background: transparent; border: none; color: $tertiary; padding: 0 4px; }
QToolButton#editslot:hover { color: $accent; }
QFrame#slot[state="on"] QToolButton#editslot { color: $accent_text; }

/* inspector */
QWidget#inspector { background: $inspector; }
QFrame#card { background: $card; border: 1px solid $separator; border-radius: 10px; }
QFrame#card QLabel#formlabel { color: $secondary; }
QLabel#fileinfo { color: $label; }
QLabel#filename { font-weight: 600; font-size: ${fs_title}pt; }
QToolButton#star { background: transparent; border: none; color: $tertiary; font-size: 15pt; padding: 0 1px; }
QToolButton#star[on="true"] { color: $orange; }
QToolButton#reject { background: transparent; border: 1px solid $field_border; border-radius: 6px; padding: 3px 9px; color: $secondary; }
QToolButton#reject:checked { background: $red; border-color: $red; color: #ffffff; }

/* preset board */
QFrame#pcol { background: $card; border: 1px solid $separator; border-radius: 14px; }
QFrame#pcol[active="true"] { border: 2px solid $accent; }
QLineEdit#ptitle { font-size: ${fs_big}pt; font-weight: 700; border: 1.5px solid $field_border; border-radius: 16px;
  padding: 4px 14px; background: $field; }
QLabel#pill { background: $accent; color: $accent_text; border-radius: 9px; padding: 2px 9px; font-weight: 600; font-size: ${fs_small}pt; }

/* player picker */
QFrame#picker { background: $card; border: 1px solid $separator; border-radius: 16px; }
QLineEdit#pickersearch { font-size: ${fs_big}pt; padding: 8px 10px; border-radius: 10px; background: $field; }
QListWidget#cards { background: transparent; }
QTableWidget { background: $field; border: 1px solid $field_border; border-radius: 8px; gridline-color: $separator;
  selection-background-color: $accent_soft; selection-color: $label; }
QHeaderView::section { background: $window; color: $secondary; border: none; border-bottom: 1px solid $separator;
  padding: 5px 6px; font-weight: 600; }

/* misc */
QFrame#banner { background: $accent_soft; border-bottom: 1px solid $separator; }
QLabel#big { font-size: ${fs_big}pt; font-weight: 600; }
QLabel#hero { font-size: 26pt; font-weight: 700; }
QLabel#herosub { color: $secondary; }
QWidget#empty { background: $bg; }
QStatusBar { background: $window; border-top: 1px solid $separator; color: $secondary; }
QStatusBar QLabel { color: $secondary; padding: 0 8px; font-size: ${fs_small}pt; }
QProgressBar { background: $control; border: none; border-radius: 4px; max-height: 8px; text-align: center; color: transparent; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QSlider::groove:horizontal { height: 4px; background: $control_hover; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { background: #ffffff; border: 1px solid $field_border; width: 16px; height: 16px; margin: -7px 0; border-radius: 8px; }
QMenu { background: $card; border: 1px solid $separator; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 5px 18px 5px 12px; border-radius: 5px; }
QMenu::item:selected { background: $accent; color: $accent_text; }
QMenu::item:disabled { color: $tertiary; }
QDialogButtonBox QPushButton { min-width: 72px; }
""")


def _chevron(color, up=False):
    """Write a small chevron SVG for the style sheet (Qt can't draw CSS triangles)."""
    d = os.path.join(tempfile.gettempdir(), 'bettermechanic')
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f'chevron-{"up" if up else "down"}-{color.strip("#")}.svg')
    if not os.path.exists(path):
        pts = '2,7 6,3 10,7' if up else '2,4 6,8 10,4'
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
                     f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6" '
                     f'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    return path.replace('\\', '/')


def system_font():
    fams = set(QFontDatabase.families())
    if sys.platform == 'darwin':
        f = QFont('.AppleSystemUIFont')
        f.setPointSize(13)
        return f
    for fam in ('Segoe UI Variable Text', 'Segoe UI', 'Inter', 'Cantarell', 'Noto Sans', 'DejaVu Sans'):
        if fam in fams:
            f = QFont(fam)
            f.setPointSize(10 if sys.platform == 'win32' else 10)
            return f
    return QFont()


def resolve(mode, app):
    if mode == 'dark':
        return True
    if mode == 'light':
        return False
    try:
        return app.styleHints().colorScheme() != Qt.ColorScheme.Light
    except AttributeError:          # Qt < 6.5
        return True


def apply(app, mode='system'):
    global IS_DARK
    IS_DARK = resolve(mode, app)
    C.clear()
    C.update(DARK if IS_DARK else LIGHT)
    app.setStyle('Fusion')
    font = system_font()
    app.setFont(font)
    fs = font.pointSizeF() if font.pointSizeF() > 0 else 10
    pal = QPalette()
    for role, key in ((QPalette.Window, 'window'), (QPalette.WindowText, 'label'), (QPalette.Base, 'field'),
                      (QPalette.AlternateBase, 'card'), (QPalette.Text, 'label'), (QPalette.Button, 'control'),
                      (QPalette.ButtonText, 'label'), (QPalette.Highlight, 'accent'),
                      (QPalette.HighlightedText, 'accent_text'), (QPalette.ToolTipBase, 'card'),
                      (QPalette.ToolTipText, 'label'), (QPalette.PlaceholderText, 'tertiary'),
                      (QPalette.Link, 'accent'), (QPalette.Mid, 'separator')):
        pal.setColor(role, qc(key))
    app.setPalette(pal)
    app.setStyleSheet(QSS.substitute(C, chevron=_chevron(C['secondary']), chevron_up=_chevron(C['secondary'], True),
                                     fs=f'{fs:g}', fs_small=f'{fs - 1:g}', fs_title=f'{fs + 1:g}',
                                     fs_big=f'{fs + 4:g}'))
    return IS_DARK
