"""F10을 눌렀을 때 롤 게임 창이 있는 모니터를 한 장 캡처한다 (증바람 증강 이름 읽기용).

게임 창은 제목으로 찾고, 그 창이 걸친 모니터 전체를 찍는다. 계속 찍거나 저장하지 않는다.
전체 화면(독점) 모드에서는 윈도우가 화면을 검게 넘겨줄 수 있어서, 검은 캡처는 버리고 '테두리 없음' 모드를 안내한다.
"""
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication

GAME_TITLE = 'League of Legends (TM) Client'
WIDTH = 1600            # 모델에 보낼 너비. 증강 이름이 읽힐 만큼만 남기고 줄인다
QUALITY = 82


def game_screen():
    """게임 창이 있는 QScreen. 게임 창이 없으면 None."""
    if sys.platform != 'win32':
        return None
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, GAME_TITLE)
    if not hwnd:
        return None

    class MonitorInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT), ('rcWork', wintypes.RECT),
                    ('dwFlags', wintypes.DWORD), ('szDevice', wintypes.WCHAR * 32)]
    info = MonitorInfo()
    info.cbSize = ctypes.sizeof(MonitorInfo)
    monitor = user32.MonitorFromWindow(hwnd, 2)          # MONITOR_DEFAULTTONEAREST
    if not (monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info))):
        return QGuiApplication.primaryScreen()
    # QScreen.name()은 모니터 모델명(예: LG ULTRAGEAR)이라 장치 이름과 맞출 수 없다. 모니터 왼쪽 위 위치로 맞춘다.
    left, top = info.rcMonitor.left, info.rcMonitor.top
    return min(QGuiApplication.screens(),
               key=lambda s: abs(s.geometry().x() - left) + abs(s.geometry().y() - top))


def is_blank(image):
    """거의 다 검은 캡처인지 (전체 화면 모드). 화면 곳곳 64곳의 밝기만 본다."""
    width, height = image.width(), image.height()
    if not width or not height:
        return True
    total = 0
    for i in range(8):
        for j in range(8):
            color = image.pixelColor(int(width * (i + 0.5) / 8), int(height * (j + 0.5) / 8))
            total += color.red() + color.green() + color.blue()
    return total / 64 < 12


def capture_game():
    """(JPEG 바이트, None) 또는 (None, 안내 문장)."""
    screen = game_screen()
    if screen is None:
        return None, '롤 게임 창을 찾지 못했습니다. 게임 중에 F10을 눌러 주세요.'
    image = screen.grabWindow(0).toImage()
    if is_blank(image):
        return None, '게임 화면이 검게 찍혔습니다. 롤 비디오 설정에서 창 모드를 테두리 없음으로 바꿔 주세요.'
    if image.width() > WIDTH:
        image = image.scaledToWidth(WIDTH, Qt.SmoothTransformation)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, 'JPG', QUALITY)
    return bytes(data), None
