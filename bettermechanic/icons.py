"""Line icons drawn with QPainter (SF Symbols-like), so they follow the theme colour."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _folder(p):
    path = QPainterPath()
    path.moveTo(3, 6.5)
    path.lineTo(3, 15)
    path.quadTo(3, 16.5, 4.5, 16.5)
    path.lineTo(15.5, 16.5)
    path.quadTo(17, 16.5, 17, 15)
    path.lineTo(17, 8.5)
    path.quadTo(17, 7, 15.5, 7)
    path.lineTo(9.6, 7)
    path.lineTo(8.2, 5)
    path.lineTo(4.5, 5)
    path.quadTo(3, 5, 3, 6.5)
    p.drawPath(path)
    p.drawLine(QPointF(3, 9.2), QPointF(17, 9.2))


def _card(p):
    path = QPainterPath()
    path.moveTo(8.5, 2.8)
    path.lineTo(14, 2.8)
    path.quadTo(15.5, 2.8, 15.5, 4.3)
    path.lineTo(15.5, 15.7)
    path.quadTo(15.5, 17.2, 14, 17.2)
    path.lineTo(6, 17.2)
    path.quadTo(4.5, 17.2, 4.5, 15.7)
    path.lineTo(4.5, 6.8)
    path.closeSubpath()
    p.drawPath(path)
    for x in (8.5, 10.5, 12.5):
        p.drawLine(QPointF(x, 5.2), QPointF(x, 7.4))


def _export(p):
    path = QPainterPath()
    path.moveTo(7.2, 8)
    path.lineTo(5.5, 8)
    path.quadTo(4.5, 8, 4.5, 9)
    path.lineTo(4.5, 16)
    path.quadTo(4.5, 17, 5.5, 17)
    path.lineTo(14.5, 17)
    path.quadTo(15.5, 17, 15.5, 16)
    path.lineTo(15.5, 9)
    path.quadTo(15.5, 8, 14.5, 8)
    path.lineTo(12.8, 8)
    p.drawPath(path)
    p.drawLine(QPointF(10, 12), QPointF(10, 2.8))
    p.drawPolyline([QPointF(7.2, 5.6), QPointF(10, 2.8), QPointF(12.8, 5.6)])


def _tag(p):
    path = QPainterPath()
    path.moveTo(3, 4.5)
    path.quadTo(3, 3, 4.5, 3)
    path.lineTo(9.6, 3)
    path.lineTo(17, 10.4)
    path.lineTo(10.4, 17)
    path.lineTo(3, 9.6)
    path.closeSubpath()
    p.drawPath(path)
    p.drawEllipse(QPointF(6.7, 6.7), 1.1, 1.1)


def _text(p):
    p.drawRoundedRect(QRectF(4, 2.8, 12, 14.4), 2, 2)
    for y in (7, 10, 13):
        p.drawLine(QPointF(7, y), QPointF(13, y if y != 13 else y))


def _gear(p):
    c = QPointF(10, 10)
    p.drawEllipse(c, 2.6, 2.6)
    p.drawEllipse(c, 5.4, 5.4)
    for i in range(8):
        a = i * math.pi / 4
        p.drawLine(QPointF(10 + 5.4 * math.cos(a), 10 + 5.4 * math.sin(a)),
                   QPointF(10 + 7.4 * math.cos(a), 10 + 7.4 * math.sin(a)))


def _help(p):
    p.drawEllipse(QPointF(10, 10), 7.2, 7.2)
    path = QPainterPath()
    path.moveTo(7.6, 8)
    path.cubicTo(7.6, 5.2, 12.4, 5.2, 12.4, 8)
    path.cubicTo(12.4, 9.8, 10, 9.8, 10, 11.6)
    p.drawPath(path)
    p.drawPoint(QPointF(10, 14.2))


def _sidebar(p, right=False):
    p.drawRoundedRect(QRectF(2.5, 4, 15, 12), 2.5, 2.5)
    x = 12.8 if right else 7.2
    p.drawLine(QPointF(x, 4), QPointF(x, 16))


def _grid(p):
    for x in (3.5, 10.8):
        for y in (3.5, 10.8):
            p.drawRoundedRect(QRectF(x, y, 5.7, 5.7), 1.3, 1.3)


def _photo(p):
    p.drawRoundedRect(QRectF(2.5, 4, 15, 12), 2, 2)
    p.drawPolyline([QPointF(2.8, 14.5), QPointF(7.5, 9.5), QPointF(11, 13), QPointF(13, 11), QPointF(17.2, 15)])
    p.drawEllipse(QPointF(13, 7.6), 1.2, 1.2)


def _search(p):
    p.drawEllipse(QPointF(8.6, 8.6), 5, 5)
    p.drawLine(QPointF(12.2, 12.2), QPointF(16.6, 16.6))


def _people(p):
    p.drawEllipse(QPointF(7.6, 7), 2.6, 2.6)
    p.drawArc(QRectF(2.6, 11.4, 10, 9), 0, 180 * 16)
    p.drawEllipse(QPointF(13.6, 6.4), 2.2, 2.2)
    p.drawArc(QRectF(10.2, 10.6, 7.6, 7.4), 15 * 16, 120 * 16)


DRAW = {'people': _people, 'folder': _folder, 'card': _card, 'export': _export, 'tag': _tag, 'text': _text, 'gear': _gear,
        'help': _help, 'sidebar_left': _sidebar, 'sidebar_right': lambda p: _sidebar(p, True), 'grid': _grid,
        'photo': _photo, 'search': _search}


def icon(name, color: QColor, size=20) -> QIcon:
    ico = QIcon()
    for scale in (1, 2, 3):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        pm.setDevicePixelRatio(scale)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(size / 20, size / 20)
        pen = QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        DRAW[name](p)
        p.end()
        ico.addPixmap(pm)
    return ico
