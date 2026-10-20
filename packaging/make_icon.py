"""Draw the app icon: bettermechanic/assets/icon.png and packaging/icon.ico.

    python packaging/make_icon.py
"""
import io
import os
import sys

from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def draw(size=1024):
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 100, size / 100)
    g = QLinearGradient(0, 0, 0, 100)
    g.setColorAt(0, QColor('#3d9bff'))
    g.setColorAt(1, QColor('#0a5fd6'))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(QRectF(6, 6, 88, 88), 21, 21)
    # viewfinder brackets
    pen = QPen(QColor('white'), 6.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    for (x, y, dx, dy) in ((24, 24, 1, 1), (76, 24, -1, 1), (24, 76, 1, -1), (76, 76, -1, -1)):
        path = QPainterPath(QPointF(x, y + 12 * dy))
        path.lineTo(x, y)
        path.lineTo(x + 12 * dx, y)
        p.drawPath(path)
    # player chip
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 235))
    p.drawEllipse(QPointF(50, 44), 8.5, 8.5)
    body = QPainterPath()
    body.moveTo(35, 66)
    body.cubicTo(35, 55, 65, 55, 65, 66)
    body.closeSubpath()
    p.drawPath(body)
    # tagged check badge
    p.setBrush(QColor('#ff9f0a'))
    p.setPen(QPen(QColor('white'), 3.2))
    p.drawEllipse(QPointF(76, 76), 13, 13)
    p.setPen(QPen(QColor('white'), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline([QPointF(70.5, 76.5), QPointF(74.5, 80.5), QPointF(82, 72.5)])
    p.end()
    return img


def to_pil(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, 'PNG')
    return Image.open(io.BytesIO(bytes(ba.data())))


if __name__ == '__main__':
    app = QGuiApplication(sys.argv[:1] + ['-platform', 'offscreen'])
    big = to_pil(draw(1024))
    os.makedirs(os.path.join(ROOT, 'bettermechanic', 'assets'), exist_ok=True)
    big.resize((256, 256), Image.Resampling.LANCZOS).save(os.path.join(ROOT, 'bettermechanic', 'assets', 'icon.png'))
    big.save(os.path.join(HERE, 'icon.ico'), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print('icon written')
