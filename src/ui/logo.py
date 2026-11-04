"""RiftFlow logo, drawn in code so the packaged app needs no image files."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QIcon, QLinearGradient, QPainter,
                           QPen, QPixmap)
from PySide6.QtWidgets import QWidget

from .theme import theme

TEAL, SKY = QColor('#3fd6b0'), QColor('#3a8fe0')
# 'R' 위를 가로지르는 균열(rift). 비율 좌표라 어떤 크기로 그려도 같은 모양이다.
RIFT = ((0.63, 0.12), (0.47, 0.50), (0.57, 0.50), (0.39, 0.90))


def _font(pixel_size, weight):
    font = QFont()
    font.setFamilies(['Segoe UI', 'Arial'])
    font.setPixelSize(pixel_size)
    font.setWeight(weight)
    return font


def paint_mark(painter, rect):
    """Rounded tile in a teal→sky gradient with a white R split by a rift."""
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0, TEAL)
    gradient.setColorAt(1, SKY)
    radius = rect.width() * 0.26
    painter.setPen(Qt.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(rect, radius, radius)
    painter.setFont(_font(int(rect.height() * 0.74), QFont.Black))
    painter.setPen(QColor('#ffffff'))
    painter.drawText(rect, Qt.AlignCenter, 'R')
    # 균열은 타일과 같은 그라데이션으로 그려 글자를 잘라 낸 것처럼 보이게 한다.
    painter.setPen(QPen(QBrush(gradient), rect.width() * 0.075, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin))
    points = [QPointF(rect.x() + rect.width() * x, rect.y() + rect.height() * y) for x, y in RIFT]
    painter.drawPolyline(points)


def logo_icon(size=64):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    paint_mark(painter, QRectF(0, 0, size, size))
    painter.end()
    return QIcon(pixmap)


def icon_font():
    """윈도우 기본 아이콘 글꼴 (11은 Fluent, 10은 MDL2). 둘 다 없으면 None."""
    families = set(QFontDatabase.families())
    return next((name for name in ('Segoe Fluent Icons', 'Segoe MDL2 Assets') if name in families), None)


def glyph_icon(glyph, color, checked_color, size=18):
    """아이콘 글꼴 글자 하나를 아이콘으로. 선택된(checked) 버튼에는 강조색으로 그린다."""
    family = icon_font()
    if family is None:
        return QIcon()
    icon = QIcon()
    for state, pen in ((QIcon.Off, color), (QIcon.On, checked_color)):
        for scale in (1, 2):        # 화면 배율 200%에서도 흐리지 않게
            pixmap = QPixmap(size * scale, size * scale)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.TextAntialiasing)
            font = QFont(family)
            font.setPixelSize(int(size * scale * 0.9))
            painter.setFont(font)
            painter.setPen(pen)
            painter.drawText(pixmap.rect(), Qt.AlignCenter, glyph)
            painter.end()
            pixmap.setDevicePixelRatio(scale)
            icon.addPixmap(pixmap, QIcon.Normal, state)
    return icon


class BrandLogo(QWidget):
    """Sidebar logo: the mark, 'Rift' + gradient 'Flow', and a short tagline."""

    MARK = 40

    def sizeHint(self):
        return QSize(172, 48)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        top = (self.height() - self.MARK) / 2
        paint_mark(painter, QRectF(0, top, self.MARK, self.MARK))

        word = _font(23, QFont.Black)
        word.setLetterSpacing(QFont.AbsoluteSpacing, -0.4)
        metrics = QFontMetricsF(word)
        x = self.MARK + 11
        baseline = top + metrics.ascent() - 3
        painter.setFont(word)
        painter.setPen(theme.color('text'))
        painter.drawText(QPointF(x, baseline), 'Rift')
        x += metrics.horizontalAdvance('Rift')
        flow = QLinearGradient(QPointF(x, 0), QPointF(x + metrics.horizontalAdvance('Flow'), 0))
        flow.setColorAt(0, TEAL)
        flow.setColorAt(1, SKY)
        painter.setPen(QPen(QBrush(flow), 1))
        painter.drawText(QPointF(x, baseline), 'Flow')

        painter.setFont(_font(11, QFont.DemiBold))
        painter.setPen(theme.color('muted'))
        painter.drawText(QPointF(self.MARK + 12, top + self.MARK - 1), 'AI 롤 가이드')
        painter.end()
