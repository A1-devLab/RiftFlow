"""Light and dark colour themes that follow the Windows app setting.

화면마다 색을 하드코딩하면 다크·라이트를 바꿀 수 없어서, 스타일시트에는 '@토큰' 이름만 쓰고
여기서 지금 테마의 색으로 바꿔 넣는다. 시스템 설정이 바뀌면 등록된 스타일시트를 모두 다시 입힌다.
"""
import re

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

DARK = {
    'bg': '#0f141c', 'sidebar': '#0b1017', 'surface': '#151c27', 'raised': '#1b2431', 'inset': '#0f151e',
    'border': '#232e3e', 'border_strong': '#33415a',
    'text': '#e8edf4', 'text2': '#b4c1d2', 'muted': '#7d8ca2',
    'accent': '#3fcfa9', 'on_accent': '#052a20', 'accent_soft': '#13332f', 'accent_fg': '#5de3c0',
    'blue': '#4c8dff', 'blue_soft': '#14233a', 'blue_fg': '#8ab8ff',
    'red': '#e5566a', 'red_soft': '#2a1a21', 'red_fg': '#ff8a99',
    'gold': '#f0c35b', 'warn': '#f0a14a', 'on_warn': '#2b1a05', 'warn_fg': '#ffb86b',
    'button': '#1d2633', 'button_hover': '#26313f', 'button_border': '#2e3a4d',
    'disabled': '#18202b', 'disabled_fg': '#5c6b80', 'accent_disabled': '#1f4a41', 'on_accent_disabled': '#7fa39a',
    'scroll': '#2f3b4e', 'scroll_hover': '#3d4b62', 'selection': '#1f4b43', 'track': '#243246',
}
LIGHT = {
    'bg': '#f3f5f8', 'sidebar': '#ffffff', 'surface': '#ffffff', 'raised': '#f4f6f9', 'inset': '#eceff4',
    'border': '#e1e6ed', 'border_strong': '#ccd4df',
    'text': '#141b26', 'text2': '#3d4a5c', 'muted': '#6a7788',
    'accent': '#11a07f', 'on_accent': '#ffffff', 'accent_soft': '#e0f4ee', 'accent_fg': '#0b8467',
    'blue': '#2f6fde', 'blue_soft': '#eaf1fd', 'blue_fg': '#2258b8',
    'red': '#d6455a', 'red_soft': '#fcedef', 'red_fg': '#bf3346',
    'gold': '#a87908', 'warn': '#e8892a', 'on_warn': '#ffffff', 'warn_fg': '#b45f0c',
    'button': '#ffffff', 'button_hover': '#eef2f6', 'button_border': '#d3dae4',
    'disabled': '#eef1f4', 'disabled_fg': '#a3adba', 'accent_disabled': '#a9dccd', 'on_accent_disabled': '#ffffff',
    'scroll': '#c9d1dc', 'scroll_hover': '#aeb8c6', 'selection': '#cdeee4', 'track': '#e3e8ef',
}
MODES = ('system', 'light', 'dark')
MODE_NAMES = {'system': '시스템 설정 따르기', 'light': '라이트', 'dark': '다크'}
TOKEN = re.compile(r'@([a-z_0-9]+)')
SCHEMES = {'system': Qt.ColorScheme.Unknown, 'light': Qt.ColorScheme.Light, 'dark': Qt.ColorScheme.Dark}


class Theme(QObject):
    """지금 테마의 색과, 테마가 바뀌면 다시 입힐 스타일시트 목록."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.styled = []            # (위젯 또는 앱, 토큰이 든 스타일시트)
        self.settings = QSettings('RiftFlow', 'RiftFlow')
        self.mode = self.settings.value('theme', 'system')
        if self.mode not in MODES:
            self.mode = 'system'
        self.connected = False

    def _hints(self):
        app = QGuiApplication.instance()
        return app.styleHints() if app is not None else None

    def _connect(self):
        hints = self._hints()
        if hints is not None and not self.connected:
            self.connected = True
            hints.colorSchemeChanged.connect(lambda _scheme: self.refresh())
            # 강제 설정(라이트·다크)은 Qt에 알려 창 제목 표시줄 색도 같이 바뀌게 한다.
            hints.setColorScheme(SCHEMES[self.mode])

    @property
    def dark(self):
        if self.mode != 'system':
            return self.mode == 'dark'
        hints = self._hints()
        return hints is not None and hints.colorScheme() == Qt.ColorScheme.Dark

    @property
    def tokens(self):
        return DARK if self.dark else LIGHT

    def color(self, name):
        return QColor(self.tokens[name])

    def css(self, template):
        tokens = self.tokens
        return TOKEN.sub(lambda match: tokens[match.group(1)], template)

    def style(self, target, template):
        """스타일시트를 입히고, 테마가 바뀌면 다시 입히도록 기억한다."""
        self._connect()
        self.styled.append((target, template))
        target.setStyleSheet(self.css(template))

    def set_mode(self, mode):
        if mode not in MODES or mode == self.mode:
            return
        self.mode = mode
        self.settings.setValue('theme', mode)
        hints = self._hints()
        if hints is not None:
            hints.setColorScheme(SCHEMES[mode])     # 바뀌면 colorSchemeChanged로 refresh가 불린다
        self.refresh()

    def palette(self):
        """스타일시트가 닿지 않는 곳(콤보 상자 목록, 메시지 상자, 툴팁)의 색."""
        t = self.tokens
        palette = QPalette()
        for role, name in ((QPalette.Window, 'bg'), (QPalette.WindowText, 'text'), (QPalette.Base, 'surface'),
                           (QPalette.AlternateBase, 'raised'), (QPalette.Text, 'text'), (QPalette.Button, 'button'),
                           (QPalette.ButtonText, 'text'), (QPalette.ToolTipBase, 'surface'),
                           (QPalette.ToolTipText, 'text'), (QPalette.Highlight, 'selection'),
                           (QPalette.HighlightedText, 'text'), (QPalette.PlaceholderText, 'muted'),
                           (QPalette.Link, 'blue_fg'), (QPalette.Mid, 'border'), (QPalette.Dark, 'border_strong')):
            palette.setColor(role, QColor(t[name]))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            palette.setColor(QPalette.Disabled, role, QColor(t['disabled_fg']))
        return palette

    def refresh(self):
        app = QApplication.instance()
        if app is not None:
            app.setPalette(self.palette())
        self.styled = [(target, template) for target, template in self.styled if isValid(target)]
        for target, template in self.styled:
            target.setStyleSheet(self.css(template))
        self.changed.emit()
        if app is not None:
            for widget in app.allWidgets():     # 직접 그리는 위젯(로고, 골드 막대, 그래프)도 새 색으로
                widget.update()


theme = Theme()
