"""Run the desktop MVP: python -m ui."""
import argparse
import html
import os
from datetime import datetime
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QLineEdit, QMainWindow, QPushButton, QScrollArea,
    QStackedWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from knowledge.documents import has_records
from rag.config import load_env
from rag import llm
from rag.llm import generate
from riot import (LiveMatchStatus, get_gameflow_phase, get_match_detail, get_current_summoner, get_live_state,
                  get_recent_history, get_solo_rank, start_login_watcher)
from game_phases.before_game.desktop import describe_session, answer_before_game, get_before_game_context
from game_phases.before_game.runes import apply_recommended_page, format_explanation, recommend_runes
from game_phases.in_game.augments import recommend_augments
from game_phases.in_game.desktop import (RECOMMEND_QUESTION, answer_in_game, describe_scoreboard, get_in_game_context,
                                         prompt_player)
from knowledge.augments import catalog_path, ensure_catalog
from knowledge.before_game import champion_catalog, save_observations, personal_context, rune_catalog, named_rune_page, canonical_champion
from knowledge.in_game import item_catalog
from .pages.out_game import OutGamePage
from .pages.before_game import BeforeGamePage
from .pages.in_game import InGamePage
from .logo import BrandLogo, glyph_icon, logo_icon
from .theme import MODE_NAMES, MODES, theme
from .voice import DEFAULT_HOTKEY, HOTKEYS, GlobalHotkey, Speaker, VoiceRecorder, beep
from .match_assets import MatchAssets
from .portraits import ChampionPortraits
from .match_detail import MatchDetailDialog
from .services import ask_general, create_demo, profile_context, sync_database
from .chat_history import SCREEN_NAMES, ChatHistory
from .capture import capture_game
from knowledge.before_game import recent_rune_pages

# 앱 전체에 쓰는 기본 모양. 색은 '@토큰'으로 쓰고 theme이 다크·라이트 값으로 바꿔 넣는다.
# 화면별 스타일시트에는 그 화면에만 있는 부품만 둔다.
STYLE = """
QWidget { color: @text; font-size: 14px; }
QMainWindow, QDialog, QMessageBox { background: @bg; }
QLabel { background: transparent; }
QToolTip { background: @surface; color: @text; border: 1px solid @border_strong; border-radius: 6px; padding: 6px 8px; }
QFrame#sidebar { background: @sidebar; border: none; border-right: 1px solid @border; }
QLabel#heading { font-size: 24px; font-weight: 700; }
QLabel#sectionHeading { font-size: 16px; font-weight: 700; }
QLabel#muted { color: @muted; font-size: 13px; }
QLabel#statusLine { color: @muted; font-size: 12px; padding: 6px 2px 0 2px; }
QLabel#badge { background: @accent_soft; color: @accent_fg; border-radius: 8px; padding: 9px 12px; font-weight: 600; }
QFrame#card, QFrame#settingsCard { background: @surface; border: 1px solid @border; border-radius: 12px; }
QPushButton { background: @button; color: @text; border: 1px solid @button_border; border-radius: 8px; padding: 9px 14px; font-weight: 600; }
QPushButton:hover { background: @button_hover; border-color: @border_strong; }
QPushButton:pressed { background: @raised; }
QPushButton:focus { border-color: @accent; }
QPushButton:disabled { color: @disabled_fg; background: @disabled; border-color: @border; }
QPushButton#primary { background: @accent; color: @on_accent; border: 1px solid @accent; font-weight: 700; }
QPushButton#primary:hover { background: @accent_fg; border-color: @accent_fg; }
QPushButton#primary:disabled { background: @accent_disabled; color: @on_accent_disabled; border-color: @accent_disabled; }
QPushButton#nav { text-align: left; background: transparent; color: @text2; border: none; border-radius: 8px; padding: 11px 12px; font-weight: 600; }
QPushButton#nav:hover { background: @raised; color: @text; }
QPushButton#nav:checked { background: @accent_soft; color: @accent_fg; font-weight: 700; }
QPushButton#nav:focus { border: none; }
QComboBox, QLineEdit { background: @surface; color: @text; border: 1px solid @button_border; border-radius: 8px; padding: 9px 11px; selection-background-color: @selection; selection-color: @text; }
QComboBox:hover, QLineEdit:hover { border-color: @border_strong; }
QComboBox:focus, QLineEdit:focus { border-color: @accent; }
QComboBox:disabled, QLineEdit:disabled { color: @disabled_fg; background: @disabled; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView { background: @surface; color: @text; border: 1px solid @border_strong; selection-background-color: @selection; selection-color: @text; outline: none; padding: 4px; }
QTextBrowser { background: @surface; color: @text; border: 1px solid @border; border-radius: 10px; padding: 12px; selection-background-color: @selection; selection-color: @text; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: @scroll; border-radius: 3px; min-height: 32px; }
QScrollBar::handle:horizontal { background: @scroll; border-radius: 3px; min-width: 32px; }
QScrollBar::handle:hover { background: @scroll_hover; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QCheckBox { spacing: 8px; }
"""
LEGAL = ("RiftFlow isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games "
         "or anyone officially involved in producing or managing Riot Games properties. Riot Games, "
         "and all associated properties are trademarks or registered trademarks of Riot Games, Inc.")


def label(text, name=None):
    item = QLabel(text)
    item.setWordWrap(True)
    if name:
        item.setObjectName(name)
    return item


def browser():
    item = QTextBrowser()
    item.setOpenLinks(False)
    item.anchorClicked.connect(open_link)
    return item


def open_link(url):
    if url.scheme() == 'https':
        QDesktopServices.openUrl(url)


HOME, PICK, INGAME, CHAT, SETTINGS = range(5)
AUGMENT_HOTKEY = 'F10'
# 사이드바 아이콘 (Segoe Fluent Icons / MDL2 글리프): 기록, 사람들, 게임 패드, 대화, 설정
NAV_GLYPHS = ('\ue81c', '\ue716', '\ue7fc', '\ue8bd', '\ue713')
NAV_TIPS = ('최근 전적과 AI 채팅', '챔피언 선택 중 픽, 밴, 추천 룬', '게임 중 스코어보드와 추천 아이템',
            '롤에 대해 자유롭게 질문', '자료 업데이트, 연결 상태, 화면 테마')
RETRY_HINT = " 문제를 해결한 뒤 '클라이언트에 적용'을 누르면 다시 적용합니다."
# 픽창이 끝나고 게임 화면이 뜨기 전(로딩 화면)에는 Live Client가 아직 열려 있지 않다.
# 이때 대기로 보면 전적 화면으로 튕겼다가 다시 인게임으로 넘어가므로 로딩으로 따로 구분한다.
LOADING_FLOWS = ('GameStart', 'InProgress', 'Reconnect')
# 단계가 바뀔 때 자동으로 보여 줄 화면. 대기(idle)는 없음 = 보고 있던 단계 화면에서 전적으로 돌아간다.
PHASE_PAGES = {'champ_select': PICK, 'loading': INGAME, 'in_game': INGAME}


def collect_phase(db_path):
    """게임 단계를 한 번에 판별한다: in_game / loading / champ_select / idle.

    단계마다 타이머를 따로 두면 LCU·Live Client 호출이 겹치므로 폴러 하나로 합쳤다.

    클라이언트 단계를 먼저 묻는다. 예전에는 매번 Live Client(2999)부터 물어서, 게임 밖에서도
    연결 시간 초과(1초)를 기다린 뒤에야 픽창을 읽었다. 이제 Live Client는 게임 단계이거나
    클라이언트를 못 찾았을 때만(클라이언트 없이 게임만 떠 있는 경우) 짧게 확인한다.
    """
    flow = get_gameflow_phase()
    if flow in LOADING_FLOWS or flow is None:
        state = get_live_state(timeout=1.0 if flow else 0.3)
        if state.status is LiveMatchStatus.IN_GAME:
            view = describe_scoreboard(get_in_game_context(state), item_catalog(db_path))
            if view.get('in_game'):
                return {'phase': 'in_game', 'view': view}
        return {'phase': 'loading'} if flow else {'phase': 'idle'}
    if flow == 'ChampSelect':
        session = get_before_game_context()
        if session is not None:
            return {'phase': 'champ_select', 'session': session, 'catalog': champion_catalog(db_path)}
    return {'phase': 'idle'}


class Job(QThread):
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.result.emit(self.function())
        except Exception as error:
            # Avoid disclosing provider credentials through arbitrary exception text.
            self.failed.emit('작업을 완료하지 못했습니다. 연결 또는 데이터 파일을 확인하세요. (%s)' % type(error).__name__)


class Window(QMainWindow):
    riot_login_detected = Signal(object)
    riot_login_failed = Signal(str)

    def __init__(self, data_dir, auto_sync=False):
        super().__init__()
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.demo_path = self.data_dir / 'demo.db'
        self.live_path = self.data_dir / 'riftflow.db'
        create_demo(self.demo_path)
        self.jobs = []
        self.pending_riot_player = None
        self.riot_context = None
        self.match_cache = {}
        self.login_watcher = None
        # 화면 셋이 아이콘 목록·그림을 따로 받지 않도록 하나를 함께 쓴다 (예전에는 같은 파일을 세 번 받았다).
        self.assets, self.portraits = MatchAssets(self), ChampionPortraits(self)
        self.poll_failures = self.live_misses = 0
        self.matchup_key = None
        self.personal_path = self.data_dir / "personal_matches.db"
        # AI 대화 기록은 이 PC에만 저장한다. 일반 질문은 앱을 다시 켜도 마지막 대화를 이어 가고,
        # 픽창·인게임 대화는 픽창·게임마다 새로 시작한다.
        self.chats = ChatHistory(self.data_dir / "chat_history.db")
        self.chat_ids = {'general': self.chats.latest('general'), 'pick': None, 'in_game': None}
        self.poll_job = None
        self.augment_job = None       # 증강 목록 받기. 다른 작업(질문)을 막지 않게 따로 돈다
        self.augment_catalog = []
        self.pick_mode = None                 # 직전 픽창의 모드. 게임 중 데이터가 증바람을 ARAM으로 줄 때 쓴다
        # 음성 질문: 녹음 → 글자로 바꾸기(작업) → 그 작업이 끝난 뒤 질문(작업) → 답을 소리로 읽기
        self.voice = theme.settings          # 화면 테마와 같은 사용자 설정 파일
        self.recorder = VoiceRecorder(self)
        self.recorder.started.connect(self.on_voice_started)
        self.recorder.finished.connect(self.on_voice_audio)
        self.recorder.failed.connect(self.on_voice_failed)
        self.hotkey = GlobalHotkey(self)
        self.hotkey.pressed.connect(self.toggle_voice)
        self.augment_hotkey = GlobalHotkey(self, hotkey_id=0x5247)      # F10: 증바람 증강 화면 읽기
        self.augment_hotkey.pressed.connect(self.read_augment_screen)
        self.pending_augments = None          # 화면에서 읽은 증강 ID. 지금 작업이 끝나면 추천도를 묻는다
        self.speak_augments = False           # F10으로 시작한 추천도는 결과를 소리로 읽는다
        self.speaker = Speaker(self)
        self.pending_voice = None             # 받아 적은 질문. 지금 작업이 끝나면 보낸다
        self.speak_next = False               # 다음 답을 소리로 읽을지 (음성으로 물은 질문만)
        self.phase = 'idle'
        self.rune_cache = {}          # 같은 챔피언·상대·성향이면 다시 부르지 않는다 (Gemini 하루 호출 한도)
        self.rune_candidate = None    # 직전 폴링에서 본 조건. 두 번 연속 같으면 자동 추천
        self.rune_shown_key = None    # 지금 화면에 보이거나 요청 중인 추천의 조건
        self.rune_applied_page = None  # 마지막으로 클라이언트에 적용한 추천 페이지 (같은 페이지를 반복 적용하지 않음)
        self.pending_rune_apply = None  # 추천 작업이 끝나면 자동 적용할 페이지
        self.closing = False
        self.setWindowTitle('RiftFlow')
        self.setWindowIcon(logo_icon())
        self.resize(1580, 880)
        self.setMinimumSize(1180, 720)
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        side = QFrame()
        side.setObjectName('sidebar')
        side.setFixedWidth(220)
        nav = QVBoxLayout(side)
        nav.setContentsMargins(16, 26, 16, 18)
        nav.setSpacing(4)
        brand = BrandLogo()
        nav.addWidget(brand)
        nav.addSpacing(28)
        self.stack = QStackedWidget()
        self.nav_buttons = []
        for i, name in enumerate(('전적', '픽창', '인게임', 'AI에게 질문', '설정 및 데이터')):
            button = QPushButton(name)
            button.setObjectName('nav')
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setIconSize(QSize(18, 18))
            button.setToolTip(NAV_TIPS[i])
            button.clicked.connect(lambda checked=False, index=i: self.navigate(index))
            nav.addWidget(button)
            self.nav_buttons.append(button)
        self.paint_nav_icons()
        theme.changed.connect(self.paint_nav_icons)
        nav.addStretch()
        row.addWidget(side)
        body = QVBoxLayout()
        body.setContentsMargins(28, 24, 28, 14)
        self.mode = QComboBox()
        self.mode.addItems(['예시 자료 · 오프라인', '수집한 자료 · 로컬 DB'])
        self.mode.currentIndexChanged.connect(self.reload)
        body.addWidget(self.stack, 1)
        self.status = label('키 없이 예시 자료를 둘러볼 수 있습니다.', 'statusLine')
        body.addWidget(self.status)
        row.addLayout(body, 1)
        self.setCentralWidget(root)
        self.make_home()
        self.make_before_game()
        self.make_in_game()
        self.make_chat()
        self.make_settings()
        theme.changed.connect(lambda: self.render_general(*self.general_view))
        self.navigate(HOME)
        self.refresh_chat_list()
        self.render_general()
        if self.chat_ids['general']:
            self.out_game.load_history(self.chats.messages(self.chat_ids['general']))
        try:
            has_live_data = self.live_path.exists() and has_records(self.live_path)
        except Exception:
            has_live_data = False
        if has_live_data:
            self.mode.setCurrentIndex(1)
        self.reload()
        if auto_sync and not has_live_data:
            # 배포판 첫 실행: 공식 자료가 없으면 알아서 받는다 (설정 화면을 찾을 필요 없게).
            QTimer.singleShot(1500, self.sync_data)
        self.riot_login_detected.connect(self.on_riot_login_detected)
        self.riot_login_failed.connect(self.out_game.show_unavailable)
        self.champ_timer = QTimer(self)
        self.champ_timer.setInterval(2500)
        self.champ_timer.timeout.connect(self.poll_champ_select)
        self.champ_timer.start()
        QTimer.singleShot(800, self.poll_champ_select)
        # 배포판은 라이엇 키 없이 RiftFlow 서버를 쓰므로 둘 중 하나만 있어도 전적을 불러온다.
        if os.environ.get('RIOT_API_KEY') or os.environ.get('RIFTFLOW_SERVER_URL'):
            self.login_watcher = start_login_watcher(self.riot_login_detected.emit,
                                                     on_error=self.riot_login_failed.emit)
            self.status.setText('롤 클라이언트 로그인을 자동으로 기다리고 있습니다.')
        else:
            # 예전에는 이 문장을 숨겨진 로딩 화면 뒤에 써서 'Loading …'만 끝없이 보였다.
            self.out_game.show_unavailable('Riot API 키를 설정하면 롤 클라이언트 로그인을 자동 감지합니다.')

    def paint_nav_icons(self):
        for button, glyph in zip(self.nav_buttons, NAV_GLYPHS):
            button.setIcon(glyph_icon(glyph, theme.color('text2'), theme.color('accent_fg')))

    def page(self, title, subtitle):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 8)
        layout.setSpacing(14)
        layout.addWidget(label(title, 'heading'))
        layout.addWidget(label(subtitle, 'muted'))
        layout.addSpacing(4)
        self.stack.addWidget(widget)
        return layout

    @staticmethod
    def card(parent_layout, title, description=None):
        """설정 화면의 묶음 상자 하나. 안쪽 레이아웃을 돌려준다."""
        frame = QFrame(objectName='settingsCard')
        box = QVBoxLayout(frame)
        box.setContentsMargins(20, 16, 20, 18)
        box.setSpacing(10)
        box.addWidget(label(title, 'sectionHeading'))
        if description:
            box.addWidget(label(description, 'muted'))
        parent_layout.addWidget(frame)
        return box

    def make_home(self):
        self.out_game = OutGamePage(assets=self.assets, portraits=self.portraits)
        self.out_game.askRequested.connect(self.ask_out_game)
        self.out_game.profileRequested.connect(self.load_riot_profile)
        self.out_game.matchRequested.connect(self.load_match_detail)
        self.stack.addWidget(self.out_game)

    def make_before_game(self):
        self.before_game = BeforeGamePage(assets=self.assets, portraits=self.portraits)
        self.before_game.askRequested.connect(self.ask_before_game)
        self.before_game.runeRequested.connect(self.request_runes)
        self.before_game.runeApplyRequested.connect(self.apply_runes)
        self.before_game.refreshRequested.connect(self.poll_champ_select)
        self.before_game.personalContextChanged.connect(self.update_personal_matchup)
        self.stack.addWidget(self.before_game)

    def make_in_game(self):
        self.in_game = InGamePage(assets=self.assets, portraits=self.portraits)
        self.in_game.askRequested.connect(self.ask_in_game)
        self.in_game.refreshRequested.connect(self.poll_champ_select)
        self.in_game.augmentRequested.connect(self.ask_augments)
        self.in_game.augmentCatalogRequested.connect(self.load_augments)
        self.in_game.voiceRequested.connect(self.toggle_voice)
        self.stack.addWidget(self.in_game)

    def poll_champ_select(self):
        """게임 단계 폴링 (이름은 기존 연결을 위해 유지). 질문 작업 중에도 스코어보드는 계속 갱신한다."""
        if self.poll_job is not None or self.closing:
            return
        path = self.db_path
        job = Job(lambda: collect_phase(path), self)
        self.poll_job = job
        job.result.connect(self.on_phase)
        job.failed.connect(self.on_poll_failed)
        job.finished.connect(self.finish_champ_poll)
        job.start()

    def on_poll_failed(self, _message):
        """폴링 한 번 실패로 픽창 입력(챔피언)을 지우면 추천 룬까지 버려졌다. 몇 번 연속 실패할 때만 대기로 본다."""
        self.poll_failures += 1
        if self.poll_failures >= 3 and not self.closing:
            self.status.setText('롤 클라이언트 상태를 읽지 못하고 있습니다. 클라이언트를 확인해 주세요.')
            self.on_phase({'phase': 'idle'})

    def on_phase(self, payload):
        if self.closing:
            return
        self.poll_failures = 0
        # 게임 중 Live Client 응답을 한 번 놓치면 로딩으로 보였다가 스코어보드와 추천 아이템이 지워졌다.
        # 게임 중에서 로딩으로 바뀐 경우는 두 번까지 직전 화면을 유지한다.
        if payload['phase'] == 'loading' and self.phase == 'in_game' and self.live_misses < 2:
            self.live_misses += 1
            return
        self.live_misses = 0
        phase, previous = payload['phase'], self.phase
        self.phase = phase
        if phase == 'champ_select' and previous != 'champ_select':
            # 새 픽창: 채팅으로 말한 성향, 적용 기록, 픽창 대화, 자동 추천 상태를 새로 시작한다.
            # (rune_shown_key를 지우지 않아 같은 챔피언으로 다음 픽창에 들어가면 자동 추천이 멈췄다.)
            self.before_game.reset_conversation()
            self.rune_applied_page = None
            self.rune_candidate = self.rune_shown_key = self.pending_rune_apply = None
            self.chat_ids['pick'] = None
            self.before_game.answer.setPlainText('픽창에서 궁금한 점을 물어보세요. 이번 픽창의 대화는 이어서 기억합니다.')
        if phase in ('loading', 'in_game') and previous not in ('loading', 'in_game'):
            self.chat_ids['in_game'] = None       # 새 게임: 인게임 대화를 새로 시작
            self.in_game.answer.setPlainText('게임 중 궁금한 점을 물어보세요. 이번 게임의 대화는 이어서 기억합니다.')
            self.in_game.items.clear()
        if phase == 'champ_select':
            self.on_champ_select((payload['session'], payload['catalog']))
        else:
            self.before_game.show_disconnected()
        if phase == 'champ_select':
            self.pick_mode = payload.get('mode') or (self.before_game.view or {}).get('game_mode')
        if phase == 'in_game':
            view = payload['view']
            # 게임 중 데이터는 증바람도 ARAM으로 줄 수 있다. 픽창에서 증바람이었으면 증바람으로 보여 준다.
            if view.get('game_mode') == 'ARAM' and self.pick_mode == 'KIWI':
                view = dict(view, game_mode='KIWI', mode_name='증바람')
            self.in_game.show_view(view)
        elif phase == 'loading':
            self.in_game.show_loading()
        elif previous in ('loading', 'in_game'):
            self.in_game.show_disconnected()
            self.refresh_history_later()
        self.follow_phase(previous, phase)

    def follow_phase(self, previous, phase):
        """클라이언트 단계가 바뀔 때만 화면을 넘긴다. 같은 단계 동안에는 사용자가 다른 화면으로 옮기면 그대로 둔다."""
        new, old = PHASE_PAGES.get(phase), PHASE_PAGES.get(previous)
        if new == old:
            return
        if new is not None:
            self.navigate(new)
        elif self.stack.currentIndex() == old:
            self.navigate(HOME)

    def refresh_history_later(self):
        """방금 끝난 경기가 전적에 보이도록 잠시 뒤 다시 불러온다. MATCH-V5 반영에 1분 안팎이 걸린다."""
        if not self.riot_context:
            return
        player = self.riot_context['player']
        QTimer.singleShot(90_000, lambda: None if self.closing else self.on_riot_login_detected(player))

    def ask_in_game(self, request):
        if self.jobs:
            return
        if not self.ai_ready():
            self.in_game.answer.setPlainText('AI 답변에 필요한 API 키(%s)를 .env에 설정해 주세요.' % llm.key_env())
            return
        model = self.model.text().strip() or llm.default_model()
        path = self.db_path
        self.in_game.answer.setPlainText('현재 스코어보드와 공식 자료를 확인하고 있습니다…')
        server, history, question = self.server(), self.chat_context('in_game'), request['question']
        if server is not None:
            from api_client.coach import coach_in_game
            work = lambda: coach_in_game(server, request['view'], question, history=history)
        else:
            work = lambda: answer_in_game(path, request['view'], question, history=history,
                                          generate=lambda prompt, **options: generate(prompt, model=model,
                                                                                       retries=0, **options))
        self.start_job(
            work,
            lambda result: self.show_in_game_answer(result, question), on_error=self.in_game.answer.setPlainText)

    # --- 음성 질문
    def setting(self, name, default):
        value = self.voice.value('voice/' + name, default)
        return value if not isinstance(default, bool) else str(value).lower() in ('true', '1')

    def apply_voice_settings(self):
        """단축키를 등록한다. 앱을 켤 때(main)와 설정을 바꿀 때만 부른다 (테스트에서 창을 만들 때는 등록하지 않는다)."""
        enabled = self.setting('enabled', True)
        hotkey = self.setting('hotkey', DEFAULT_HOTKEY)
        self.hotkey.unregister()
        message = '음성 질문을 끄면 단축키도 해제됩니다.'
        if enabled:
            ok = self.hotkey.register(hotkey)
            message = (f'게임 중 {hotkey}를 누르고 말하면 질문합니다. 말을 멈추면 자동으로 끝납니다.' if ok else
                       f'{hotkey}는 다른 프로그램이 쓰고 있어 등록하지 못했습니다. 다른 단축키를 골라 주세요.')
        self.augment_hotkey.unregister()
        if self.setting('augment_key', True) and not self.augment_hotkey.register(AUGMENT_HOTKEY):
            message += f' {AUGMENT_HOTKEY}는 다른 프로그램이 쓰고 있어 증강 읽기를 등록하지 못했습니다.'
        self.voice_note.setText(message)

    def save_voice_setting(self, name, value):
        self.voice.setValue('voice/' + name, value)
        if name in ('enabled', 'hotkey', 'augment_key'):
            self.apply_voice_settings()

    def toggle_voice(self):
        """단축키나 마이크 버튼. 녹음 중이면 끝내고, 아니면 시작한다."""
        if self.recorder.recording:
            self.recorder.stop()
            return
        self.in_game.set_listening(False)
        if self.jobs or self.pending_voice is not None:
            self.status.setText('다른 작업이 끝난 뒤 다시 눌러 주세요.')
            return
        if not self.ai_ready():
            self.status.setText('음성 질문에 필요한 AI 연결이 없습니다.')
            return
        self.recorder.start()

    def on_voice_started(self):
        self.in_game.set_listening(True)
        self.status.setText('듣고 있습니다. 말을 멈추면 자동으로 질문합니다.')

    def on_voice_failed(self, message):
        self.in_game.set_listening(False)
        if message:
            self.status.setText(message)

    def on_voice_audio(self, audio):
        self.in_game.set_listening(False)
        self.status.setText('음성을 글자로 바꾸고 있습니다…')
        server = self.server()
        if server is not None:
            from api_client.coach import transcribe
            work = lambda: transcribe(server, audio)
        else:
            def work():
                from rag import speech
                from rag.gemini import GeminiError
                try:
                    return {'text': speech.transcribe(audio), 'message': None}
                except GeminiError as error:
                    return {'text': None, 'message': error.message}
        self.start_job(work, self.on_voice_text)

    def on_voice_text(self, result):
        text = (result or {}).get('text')
        if not text:
            message = (result or {}).get('message') or '목소리를 알아듣지 못했습니다.'
            self.status.setText(message)
            if self.setting('speak', True):
                self.speaker.say(message)
            return
        self.pending_voice = text           # 받아 적기 작업이 끝나면(job_done) 질문으로 보낸다

    def ask_voice(self, text):
        """받아 적은 질문을 게임 중이면 인게임 AI에, 아니면 일반 AI 질문에 보낸다."""
        self.speak_next = self.setting('speak', True)
        if self.phase in ('in_game', 'loading') or self.in_game.view.get('in_game'):
            self.in_game.question.setText(text)
            self.in_game.submit()
        else:
            self.out_game.question.setText(text)
            self.out_game.submit()
        self.status.setText('음성 질문: ' + text)

    def speak_answer(self, text):
        if self.speak_next:
            self.speak_next = False
            if text:
                self.speaker.say(text)

    def read_augment_screen(self):
        """F10: 게임 모니터를 한 장 찍어 증강 이름을 읽고, 증강 탭에 채운 뒤 추천도를 묻는다."""
        if self.jobs or self.pending_augments is not None or self.pending_voice is not None:
            self.status.setText('다른 작업이 끝난 뒤 다시 눌러 주세요.')
            return
        if not self.ai_ready():
            self.status.setText('증강 읽기에 필요한 AI 연결이 없습니다.')
            return
        image, message = capture_game()
        if image is None:
            self.status.setText(message)
            if self.setting('speak', True):
                self.speaker.say(message)
            return
        beep(True)
        self.status.setText('증강 선택 화면을 읽고 있습니다…')
        server = self.server()
        if server is not None:
            from api_client.coach import detect_augments
            work = lambda: detect_augments(server, image)
        else:
            path, known = catalog_path(self.data_dir), list(self.augment_catalog)

            def work():
                from rag import vision
                from rag.gemini import GeminiError
                try:
                    return {'augments': vision.read_augments(image, known or ensure_catalog(path)), 'message': None}
                except GeminiError as error:
                    return {'augments': [], 'message': error.message}
        self.start_job(work, self.on_augments_read)

    def on_augments_read(self, result):
        augments = [a for a in (result or {}).get('augments') or [] if isinstance(a, dict) and isinstance(a.get('id'), int)]
        if len(augments) < 2:
            message = (result or {}).get('message') or '증강 이름을 읽지 못했습니다. 증강 선택 화면에서 다시 눌러 주세요.'
            self.status.setText(message)
            if self.setting('speak', True):
                self.speaker.say(message)
            return
        known = {a['id'] for a in self.augment_catalog}
        added = [a for a in augments if a['id'] not in known]
        if added or not self.in_game.augments.catalog:
            self.augment_catalog += added
            self.in_game.augments.set_catalog(self.augment_catalog)
        self.navigate(INGAME)
        self.in_game.show_tab(1)
        for combo, augment in zip(self.in_game.augments.choices, augments + [None] * 3):
            combo.setEditText(augment['name'] if augment else '')
        self.status.setText('읽은 증강: ' + ', '.join(a['name'] for a in augments))
        self.pending_augments = [a['id'] for a in augments][:3]   # 읽기 작업이 끝나면(job_done) 추천도를 묻는다

    # --- 증바람 증강 추천도
    def load_augments(self):
        """증강 목록을 한 번 받는다. 배포판은 서버가 하루마다 새로 받아 둔 목록을, 개발 모드는 직접 받는다."""
        if self.augment_catalog or self.augment_job is not None or self.closing:
            return
        server, path = self.server(), catalog_path(self.data_dir)
        if server is not None:
            from api_client.coach import augment_catalog
            work = lambda: augment_catalog(server)
        else:
            work = lambda: ensure_catalog(path)
        job = Job(work, self)
        self.augment_job = job
        job.result.connect(self.show_augment_catalog)
        job.failed.connect(lambda _message: self.in_game.augments.set_catalog([]))
        job.finished.connect(self.finish_augment_job)
        job.start()

    def show_augment_catalog(self, augments):
        self.augment_catalog = list(augments or [])
        self.in_game.augments.set_catalog(self.augment_catalog)

    def finish_augment_job(self):
        job, self.augment_job = self.augment_job, None
        if job is not None:
            job.deleteLater()

    def ask_augments(self, request):
        if self.jobs:
            return
        if not self.ai_ready():
            self.in_game.augments.show_result({'message': 'AI 답변에 필요한 API 키(%s)를 .env에 설정해 주세요.' % llm.key_env()})
            return
        ids, view = request['augment_ids'], request['view']
        by_id = {a['id']: a for a in self.augment_catalog}
        names = ', '.join(by_id[i]['name'] for i in ids if i in by_id)
        server, path = self.server(), self.db_path
        if server is not None:
            from api_client.coach import recommend_augments as recommend_remote
            work = lambda: recommend_remote(server, view, ids)
        else:
            model = self.model.text().strip() or llm.default_model()
            offered = [by_id[i] for i in ids if i in by_id]
            work = lambda: recommend_augments(path, view, offered, prompt_player=prompt_player,
                                              generate=lambda prompt, **options: generate(prompt, model=model,
                                                                                           retries=0, **options))
        self.in_game.augments.caption.setText('받은 증강과 지금 조합을 비교하고 있습니다…')
        self.status.setText('증강 추천도 계산 중')
        self.start_job(work, lambda result: self.show_augment_result(result, names),
                       on_error=lambda message: self.in_game.augments.show_result({'message': message}))

    def show_augment_result(self, result, names):
        self.in_game.augments.show_result(result)
        if self.speak_augments:
            self.speak_augments = False
            if self.setting('speak', True):
                self.speaker.say(result.get('answer') or result.get('message'))
        self.record_chat('in_game', '증강 추천도: ' + names, result.get('answer') or result.get('message'))
        self.show_transcript(self.in_game.answer, 'in_game')
        self.status.setText('증강 추천도 완료' if result.get('generated') else '증강 추천도 확인 필요')

    def show_in_game_answer(self, result, question=None):
        if result.get('options') is not None or question == RECOMMEND_QUESTION:
            self.in_game.items.show_result(result)     # 아이템 추천은 대화창이 아니라 추천 칸에 보여 준다
        self.record_chat('in_game', question, result.get('answer') or result.get('message'))
        self.show_transcript(self.in_game.answer, 'in_game')
        self.speak_answer(result.get('answer') or result.get('message'))
        self.status.setText('인게임 답변 완료' if result['generated'] else '인게임 자료 확인 필요')

    # --- AI 대화 기록
    def chat_context(self, screen):
        """모델에 넘길 이 화면의 최근 대화."""
        return self.chats.context(self.chat_ids.get(screen))

    def record_chat(self, screen, question, answer):
        if not self.chat_ids.get(screen):
            self.chat_ids[screen] = ChatHistory.new_id()
        if question:
            self.chats.add(self.chat_ids[screen], screen, 'user', question)
        if answer:
            self.chats.add(self.chat_ids[screen], screen, 'assistant', answer)
        self.refresh_chat_list()

    def show_transcript(self, widget, screen):
        """픽창·인게임 답변 칸에 이번 픽창·게임의 대화 전체를 보여 준다 (최신이 아래)."""
        messages = self.chats.messages(self.chat_ids[screen]) if self.chat_ids.get(screen) else []
        widget.setPlainText('\n\n'.join(('나: ' if m['role'] == 'user' else 'AI: ') + m['text'] for m in messages))
        bar = widget.verticalScrollBar()
        bar.setValue(bar.maximum())

    def finish_champ_poll(self):
        job = self.poll_job
        self.poll_job = None
        if job is not None:
            job.deleteLater()

    def on_champ_select(self, payload):
        session, catalog = payload
        if session is None:
            self.before_game.show_disconnected()
            return
        view = describe_session(session, catalog)
        self.before_game.show_session(view)
        self.update_personal_matchup()
        self.maybe_auto_recommend()

    @staticmethod
    def rune_key(request):
        # 채팅 내용은 조건에 넣지 않는다. 룬 이야기를 하면 채팅이 직접 새 추천을 요청한다.
        return (request['champion'], request['opponent'], (request.get('view') or {}).get('game_mode'))

    def maybe_auto_recommend(self):
        """op.gg처럼 픽창에서 내 챔피언(올려놓기 포함)이 잠깐 그대로면 룬을 자동으로 추천한다.

        챔피언을 이리저리 올려 보는 동안 호출하지 않도록 두 번의 폴링(약 2.5초) 동안 같아야 부른다.
        같은 조건의 추천은 캐시로 바로 보여 주고, 자동 요청은 조건마다 한 번만 한다(실패해도 반복하지 않음).
        """
        if not self.ai_ready() or self.before_game.no_runes():
            return                  # 증바람, 아레나는 룬 페이지가 없다
        request = self.before_game._request()
        if not request['champion']:
            self.rune_candidate = None
            return
        key = self.rune_key(request)
        if key == self.rune_shown_key and (self.before_game.rune_page is not None or key not in self.rune_cache):
            # 이미 보여 주는 중이거나, 이 조건의 자동 요청이 실패한 경우(반복하지 않음).
            # 챔피언을 바꿨다 돌아와 화면의 추천이 버려졌으면 저장해 둔 추천을 다시 보여 준다.
            return
        if key != self.rune_candidate:
            self.rune_candidate = key
            return
        if key in self.rune_cache:
            self.rune_shown_key = key
            self.show_rune_recommendation(self.rune_cache[key], request['champion'], key)
            return
        self.request_runes(request)

    def update_personal_matchup(self, force=False):
        """개인 상성 문구. 픽창 폴링(2.5초)마다 개인 기록 DB를 다시 읽지 않도록 조건이 바뀔 때만 계산한다."""
        if not self.riot_context:
            return
        view = self.before_game.view
        champion = self.before_game.champion.text().strip()
        if not champion:
            return
        from game_phases.before_game.desktop import opponent_for_lane
        opponent = self.before_game.opponent.text().strip() or opponent_for_lane(view)
        lane = (view.get('mine') or {}).get('position')
        key = (self.riot_context['player'].puuid, champion, opponent, lane)
        if key == self.matchup_key and not force:
            return
        self.matchup_key = key
        summary = personal_context(self.personal_path, self.riot_context['player'].puuid,
                                   canonical_champion(self.db_path, champion),
                                   canonical_champion(self.db_path, opponent), lane)
        if summary['matchup_games']:
            self.before_game.personal.setText(
                f"내 조회 경기 중 {champion} 대 {opponent}: "
                f"{summary['matchup_games']}전 {summary['matchup_wins']}승 · 개인 기록, 전체 상성 통계 아님")
        elif summary['champion_games']:
            self.before_game.personal.setText(
                f"내 조회 경기에서 {champion} {summary['champion_games']}회 플레이 · 해당 맞라인 상대 표본 없음")
        else:
            self.before_game.personal.setText('조회한 협곡 경기에서 해당 챔피언의 개인 기록이 없습니다.')
        page = named_rune_page(summary.get('latest_rune_page'), rune_catalog(self.db_path))
        self.before_game.runes.setText(
            '최근 사용한 룬: ' + ' / '.join(', '.join(style['runes']) for style in page)
            if page else '이 챔피언으로 사용한 룬 페이지 기록이 없습니다.')

    def ask_before_game(self, request):
        if self.jobs:
            return
        if not self.ai_ready():
            self.before_game.answer.setPlainText('AI 답변에 필요한 API 키(%s)를 .env에 설정해 주세요.' % llm.key_env())
            return
        model = self.model.text().strip() or llm.default_model()
        puuid = self.riot_context['player'].puuid if self.riot_context else None
        server, path, history = self.server(), self.db_path, self.chat_context('pick')
        if request['champion'] in ('', '선택 전'):
            # 챔피언을 고르기 전(또는 픽창 밖)에도 '티모 서폿이랑 어울리는 거?' 같은 질문에는 답한다.
            # 예전에는 빈 챔피언을 서버가 형식 오류(422)로 거절해 '요청이 실패했습니다 (422)'만 보였다.
            self.before_game.answer.setPlainText('공식 자료를 확인하고 있습니다…')
            profile = self.riot_context
            self.start_job(lambda: self.general_answer(path, request['question'], profile, model, history),
                           lambda result: self.show_before_game_answer(result, request['question']),
                           on_error=self.before_game.answer.setPlainText)
            return
        self.before_game.answer.setPlainText('확정된 픽과 공식 자료를 확인하고 있습니다…')
        if server is not None:
            # 개인 상성 기록은 이 PC에서 계산해 요약만 보낸다 (PUUID는 보내지 않음).
            from api_client.coach import coach_pick
            lane = (request['view'].get('mine') or {}).get('position')
            observations = (personal_context(self.personal_path, puuid, canonical_champion(path, request['champion']),
                                             canonical_champion(path, request['opponent']), lane) if puuid else None)
            work = lambda: coach_pick(server, request['view'], request['question'], champion=request['champion'],
                                      opponent=request['opponent'], user_requests=request['user_requests'],
                                      observations=observations, history=history)
        else:
            work = lambda: answer_before_game(
                path, self.personal_path, puuid, request['view'], request['question'],
                generate=lambda prompt: generate(prompt, model=model, retries=0),
                champion=request['champion'], opponent=request['opponent'],
                user_requests=request['user_requests'], history=history)
        self.start_job(
            work,
            lambda result: self.show_before_game_answer(result, request['question']),
            on_error=self.before_game.answer.setPlainText,
        )

    def request_runes(self, request):
        """룬 추천을 요청한다. 버튼은 항상 새로 받고, 자동 추천은 maybe_auto_recommend가 캐시를 먼저 본다."""
        if self.jobs:
            return False
        if not self.ai_ready():
            self.before_game.rune_view.show_message('룬 추천에 필요한 API 키(%s)를 .env에 설정해 주세요.' % llm.key_env())
            return False
        model = self.model.text().strip() or llm.default_model()
        path, personal = self.db_path, self.personal_path
        # 룬 트리 구조가 없을 때 내려받아 채우는 건 수집한 자료 DB에서만 한다. 예시 자료는 건드리지 않는다.
        download = path == self.live_path
        puuid = self.riot_context['player'].puuid if self.riot_context else None
        champion, key = request['champion'], self.rune_key(request)
        self.rune_shown_key = key
        if request.get('question'):
            self.record_chat('pick', request['question'], None)
        self.before_game.rune_view.show_message('챔피언과 상대 조합, 공식 룬 설명을 바탕으로 룬을 고르고 있습니다…')
        self.status.setText('룬 추천 중')
        server = self.server()
        if server is not None:
            from api_client.coach import recommend_runes as recommend_remote
            pages = recent_rune_pages(personal, puuid, canonical_champion(path, champion)) if puuid else []
            work = lambda: recommend_remote(server, request['view'], champion=champion, opponent=request['opponent'],
                                            user_requests=request['user_requests'], recent_pages=pages)
        else:
            work = lambda: recommend_runes(
                path, personal, puuid, request['view'], champion=champion, opponent=request['opponent'],
                user_requests=request['user_requests'], download=download,
                generate=lambda prompt, **options: generate(prompt, model=model, retries=0, **options))
        self.start_job(
            work,
            lambda result: self.show_rune_recommendation(result, champion, key),
            on_error=self.before_game.rune_view.show_message)
        return True

    def apply_runes(self, request):
        """룬 페이지를 클라이언트에 적용한다. 버튼(수동)과 추천 직후(자동) 모두 여기로 온다."""
        if self.jobs:
            return
        page, champion = request['page'], request['champion']
        request = dict(request, key=request.get('key') or self.rune_shown_key)
        self.before_game.show_apply_status('롤 클라이언트에 룬 페이지를 적용하고 있습니다…')
        self.status.setText('룬 페이지 적용 중')
        self.start_job(lambda: apply_recommended_page(page, champion),
                       lambda result: self.show_rune_applied(result, request),
                       on_error=lambda message: self.before_game.show_apply_status(message + RETRY_HINT, ok=False))

    def show_rune_applied(self, result, request=None):
        request = request or {}
        if result['applied']:
            self.rune_applied_page = request.get('page')
            self.before_game.show_apply_status(result['message'], ok=True)
        else:
            prefix = '자동 적용하지 못했습니다. ' if request.get('auto') else ''
            self.before_game.show_apply_status(prefix + result['message'] + RETRY_HINT, ok=False)
        self.status.setText('룬 페이지 적용 완료' if result['applied'] else '룬 페이지 적용 실패')

    def show_rune_recommendation(self, result, champion, key=None):
        if result.get('page') and key is not None:
            self.rune_cache[key] = result
        self.before_game.show_rune_result(result, champion)
        self.record_chat('pick', None, '[추천 룬] ' + format_explanation(result))
        self.show_transcript(self.before_game.answer, 'pick')
        self.status.setText('룬 추천 완료' if result['generated'] else '룬 추천 확인 필요')
        # 픽창에서는 추천을 바로 클라이언트에 적용한다. 이미 적용한 조건이면 다시 쓰지 않는다.
        if (result.get('page') and key is not None and self.phase == 'champ_select'
                and result['page'] is not self.rune_applied_page):
            self.pending_rune_apply = {'page': result['page'], 'champion': champion, 'key': key, 'auto': True}
            self.before_game.show_apply_status('추천 룬을 클라이언트에 자동으로 적용합니다…')
            if not self.jobs:
                self.run_pending_rune_apply()

    def run_pending_rune_apply(self):
        request, self.pending_rune_apply = self.pending_rune_apply, None
        if request is None:
            return
        # 기다리는 사이 챔피언이 바뀌었거나(추천 무효) 픽창이 끝났으면 적용하지 않는다.
        if self.phase != 'champ_select' or self.before_game.rune_page is not request['page']:
            self.before_game.show_apply_status('')
            return
        self.apply_runes(request)

    def show_before_game_answer(self, result, question=None):
        self.record_chat('pick', question, self.answer_text(result) or '답변을 받지 못했습니다.')
        self.show_transcript(self.before_game.answer, 'pick')
        self.status.setText('픽창 답변 완료' if result.get('generated') else '픽창 자료 확인 필요')

    def make_chat(self):
        layout = self.page('AI에게 질문', '롤 전적 분석, 챔피언 추천, 연습 방법과 패치에 대해 질문하세요. '
                                          '대화는 이 PC에만 저장되고, 이어지는 질문은 앞 대화를 기억합니다.')
        tools = QHBoxLayout()
        self.chat_list = QComboBox()
        self.chat_list.setMinimumWidth(420)
        self.chat_list.activated.connect(self.open_chat)
        tools.addWidget(label('지난 대화', 'muted'))
        tools.addWidget(self.chat_list, 1)
        new_chat = QPushButton('새 대화')
        new_chat.clicked.connect(self.new_chat)
        clear_chats = QPushButton('기록 지우기')
        clear_chats.clicked.connect(self.clear_chats)
        tools.addWidget(new_chat)
        tools.addWidget(clear_chats)
        layout.addLayout(tools)
        self.reply = browser()
        layout.addWidget(self.reply, 1)
        form = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setPlaceholderText('질문을 입력하세요')
        self.question.setMaxLength(1000)
        self.question.returnPressed.connect(self.ask)
        self.send = QPushButton('AI에게 질문')
        self.send.setObjectName('primary')
        self.send.clicked.connect(self.ask)
        form.addWidget(self.question, 1)
        form.addWidget(self.send)
        layout.addLayout(form)

    def make_settings(self):
        page = self.page('설정 및 데이터', 'API 연결 상태, 공식 게임 자료 업데이트, 화면 테마를 관리합니다.')
        # 설정이 늘어나도 창이 작을 때 잘리지 않게 스크롤 안에 묶음 상자를 쌓는다.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        page.addWidget(scroll, 1)

        box = self.card(layout, '연결 상태')
        self.connection = label('', 'badge')
        box.addWidget(self.connection)

        box = self.card(layout, 'AI가 참고할 자료',
                        'AI는 일반 지식과 연결된 전적을 활용하고, 선택한 자료도 보조로 참고합니다. '
                        '예시 자료는 과거 버전의 소량 데이터이니 실제로 쓸 때는 공식 자료를 업데이트하세요.')
        box.addWidget(self.mode)
        row = QHBoxLayout()
        self.sync = QPushButton('공식 게임 자료 수집 / 업데이트')
        self.sync.setObjectName('primary')
        self.sync.clicked.connect(self.sync_data)
        row.addWidget(self.sync)
        row.addStretch()
        box.addLayout(row)
        box.addWidget(label('Data Dragon과 최근 패치 노트 3개를 로컬 DB에 저장합니다. '
                            '라이엇 키는 필요하지 않고, 자동 예약 업데이트는 아닙니다.', 'muted'))

        box = self.card(layout, '화면', '다크 모드와 라이트 모드는 기본으로 윈도우 설정을 따릅니다.')
        self.theme_mode = QComboBox()
        for mode in MODES:
            self.theme_mode.addItem(MODE_NAMES[mode], mode)
        self.theme_mode.setCurrentIndex(MODES.index(theme.mode))
        self.theme_mode.currentIndexChanged.connect(lambda index: theme.set_mode(self.theme_mode.itemData(index)))
        self.theme_mode.setMaximumWidth(320)
        box.addWidget(self.theme_mode)

        box = self.card(layout, '음성 질문', '게임 중 단축키를 누르고 말하면 질문하고, 답을 소리로 읽어 줍니다. '
                                          '음성은 글자로 바꾸는 데만 쓰고 저장하지 않습니다 (HASA 음성 인식).')
        enabled = QCheckBox('음성 질문 사용')
        enabled.setChecked(self.setting('enabled', True))
        enabled.toggled.connect(lambda on: self.save_voice_setting('enabled', on))
        box.addWidget(enabled)
        row = QHBoxLayout()
        row.addWidget(label('단축키', 'muted'))
        self.hotkey_choice = QComboBox()
        self.hotkey_choice.addItems(HOTKEYS)
        current = self.setting('hotkey', DEFAULT_HOTKEY)
        self.hotkey_choice.setCurrentIndex(HOTKEYS.index(current) if current in HOTKEYS else 0)
        self.hotkey_choice.currentTextChanged.connect(lambda text: self.save_voice_setting('hotkey', text))
        self.hotkey_choice.setMaximumWidth(220)
        row.addWidget(self.hotkey_choice)
        row.addStretch()
        box.addLayout(row)
        speak = QCheckBox('답을 소리로 읽어 주기 (윈도우 한국어 음성)')
        speak.setChecked(self.setting('speak', True))
        speak.toggled.connect(lambda on: self.save_voice_setting('speak', on))
        box.addWidget(speak)
        augment_key = QCheckBox(f'{AUGMENT_HOTKEY}로 증바람 증강 선택 화면 읽기 (게임 모니터를 한 장 찍어 이름만 읽고 저장하지 않음)')
        augment_key.setChecked(self.setting('augment_key', True))
        augment_key.toggled.connect(lambda on: self.save_voice_setting('augment_key', on))
        box.addWidget(augment_key)
        self.voice_note = label('설정한 단축키는 앱을 켜면 등록됩니다.', 'muted')
        box.addWidget(self.voice_note)

        box = self.card(layout, '고급', 'AI 모델 ID를 비워 두면 기본 모델을 씁니다. '
                                      'API 키는 .env에서 관리하고, 실제 키는 채팅이나 GitHub에 올리지 마세요.')
        self.model = QLineEdit(llm.default_model())
        self.model.setPlaceholderText('AI 모델 ID (비워 두면 기본 모델)')
        box.addWidget(self.model)
        row = QHBoxLayout()
        portal = QPushButton('라이엇 개발자 포털 열기')
        portal.clicked.connect(lambda: open_link(QUrl('https://developer.riotgames.com/')))
        row.addWidget(portal)
        row.addStretch()
        box.addLayout(row)
        layout.addStretch()
        legal = label(LEGAL, 'muted')
        legal.setStyleSheet('font-size: 11px;')
        layout.addWidget(legal)

    @staticmethod
    def server():
        """RIFTFLOW_SERVER_URL이 있으면 AI·전적을 서버로 처리한다 (배포판은 키 없이 이 방식)."""
        url = os.environ.get('RIFTFLOW_SERVER_URL')
        if not url:
            return None
        from api_client import shared_client
        return shared_client(url)

    def ai_ready(self):
        return self.server() is not None or llm.has_key()

    @property
    def db_path(self):
        return self.demo_path if self.mode.currentIndex() == 0 else self.live_path

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)

    def reload(self, *_):
        if not hasattr(self, 'connection'):
            return
        riot = ('RiftFlow 서버' if os.environ.get('RIFTFLOW_SERVER_URL') else
                'Riot 키 ' + ('설정됨' if os.environ.get('RIOT_API_KEY') else '미설정'))
        ai = 'RiftFlow 서버' if os.environ.get('RIFTFLOW_SERVER_URL') else (
            '%s 키 ' % ('HASA' if llm.provider() == 'hasa' else 'Gemini') + ('설정됨' if llm.has_key() else '미설정'))
        self.connection.setText('AI: %s  ·  전적: %s' % (ai, riot))

    def start_job(self, function, callback, on_error=None):
        if self.closing:
            return              # 닫는 중에는 새 작업(대기 중이던 룬 적용·전적 새로고침)을 시작하지 않는다
        job = Job(function, self)
        self.jobs.append(job)
        self.send.setEnabled(False)
        self.sync.setEnabled(False)
        self.mode.setEnabled(False)
        self.out_game.set_busy(True)
        self.before_game.set_busy(True)
        self.in_game.set_busy(True)
        job.result.connect(callback)
        job.failed.connect(self.failed)
        if on_error is not None:
            job.failed.connect(on_error)
        job.finished.connect(lambda: self.job_done(job))
        job.start()

    def job_done(self, job):
        self.jobs.remove(job)
        job.deleteLater()
        self.send.setEnabled(True)
        self.sync.setEnabled(True)
        self.mode.setEnabled(True)
        self.out_game.set_busy(False)
        self.before_game.set_busy(False)
        self.in_game.set_busy(False)
        if not self.jobs and self.pending_rune_apply is not None:
            # 픽창 시간 안에 끝나야 하므로 전적 새로고침보다 먼저 한다.
            QTimer.singleShot(0, self.run_pending_rune_apply)
        elif not self.jobs and self.pending_augments is not None:
            ids, self.pending_augments = self.pending_augments, None
            self.speak_augments = True
            QTimer.singleShot(0, lambda: self.ask_augments({'augment_ids': ids, 'view': self.in_game.view}))
        elif not self.jobs and self.pending_voice is not None:
            text, self.pending_voice = self.pending_voice, None
            QTimer.singleShot(0, lambda: self.ask_voice(text))
        elif not self.jobs and self.pending_riot_player is not None:
            player = self.pending_riot_player
            self.pending_riot_player = None
            QTimer.singleShot(0, lambda: self.load_riot_profile(player))

    def failed(self, message):
        """작업 실패는 상태줄에만 쓴다. 화면별 안내는 작업을 시작한 쪽이 on_error로 넘긴다.

        예전에는 모든 실패를 네 화면에 한꺼번에 써서, 룬 적용 실패가 픽창 대화와 AI 질문 화면을 덮어썼다.
        """
        self.status.setText(message)
        self.speak_answer(message)

    def ask_out_game(self, question):
        if self.jobs:
            return
        if not self.ai_ready():
            self.out_game.show_error('AI 답변에 필요한 API 키(%s)를 .env에 설정한 뒤 앱을 다시 실행하세요.' % llm.key_env())
            return
        model = self.model.text().strip() or llm.default_model()
        path, profile = self.db_path, self.riot_context
        self.status.setText('AI 답변을 준비하고 있습니다.')
        history = self.chat_context('general')
        self.start_job(lambda: self.general_answer(path, question, profile, model, history),
                       lambda result: self.show_out_game_answer(result, question),
                       on_error=self.out_game.show_error)

    def general_answer(self, path, question, profile, model, history=None):
        server = self.server()
        if server is not None:
            from api_client.coach import coach_general
            return coach_general(server, question, profile_context(profile), history=history)
        return ask_general(path, question, profile=profile, history=history,
                           generate=lambda prompt: generate(prompt, model=model, retries=0))

    @staticmethod
    def answer_text(result):
        return result.get('answer') or result.get('message') or result.get('error')

    def show_out_game_answer(self, result, question=None):
        self.record_chat('general', question, self.answer_text(result))
        self.render_general()
        self.out_game.show_answer(result)
        self.speak_answer(self.answer_text(result))
        self.status.setText('완료 · ' + ('AI 답변' if result.get('generated') else '공식 자료 검색'))

    def riot_profile(self, player=None):
        player = player or get_current_summoner()
        history = get_recent_history(player.puuid, 20)
        save_observations(self.personal_path, player.puuid, history['observations'])
        matches, details = history['summaries'], history['details']
        return {'player': player, 'rank': get_solo_rank(player.puuid),
                'matches': matches, 'details': details}

    def on_riot_login_detected(self, player):
        if self.jobs:
            self.pending_riot_player = player
            self.status.setText('롤 로그인을 감지했습니다. 진행 중인 작업 후 전적을 불러옵니다.')
            return
        self.load_riot_profile(player)

    def load_riot_profile(self, player=None):
        if self.jobs:
            return
        self.status.setText('롤 클라이언트와 최근 전적을 확인하고 있습니다.')
        self.start_job(lambda: self.riot_profile(player), self.show_riot_profile,
                       on_error=self.out_game.show_unavailable)

    def show_riot_profile(self, payload):
        self.riot_context = payload
        self.out_game.show_profile(payload)
        self.match_cache.update({d.get('metadata', {}).get('matchId'): d
                                 for d in payload.get('details', []) if d.get('metadata', {}).get('matchId')})
        self.update_personal_matchup(force=True)        # 새 전적이 저장됐으니 같은 조건이라도 다시 계산
        self.status.setText('로그인한 플레이어와 최근 전적을 불러왔습니다.')

    def load_match_detail(self, match_id):
        if self.jobs or not self.riot_context:
            return
        puuid = self.riot_context['player'].puuid
        def show(detail):
            self.match_cache[match_id] = detail
            dialog = MatchDetailDialog(detail, puuid, self)
            dialog.setAttribute(Qt.WA_DeleteOnClose)
            dialog.setWindowModality(Qt.WindowModal)
            dialog.show()
            self.status.setText('경기 상세 통계를 불러왔습니다.')
        if match_id in self.match_cache:
            show(self.match_cache[match_id])
            return
        self.status.setText('선택한 경기의 상세 통계를 불러오고 있습니다…')
        self.start_job(lambda: get_match_detail(match_id), show)

    def ask(self):
        if self.jobs:
            return
        question = self.question.text().strip()
        if not question:
            return
        model = self.model.text().strip() or llm.default_model()
        if not self.ai_ready():
            self.reply.setPlainText('AI 답변에 필요한 API 키가 없습니다. .env 파일에 %s를 설정한 뒤 앱을 다시 실행하세요.' % llm.key_env())
            return
        path, profile = self.db_path, self.riot_context
        self.render_general(pending=question)
        self.status.setText('연결된 전적과 질문을 바탕으로 답변 중' if profile else '질문을 바탕으로 답변 중')
        history = self.chat_context('general')
        self.question.clear()
        self.start_job(lambda: self.general_answer(path, question, profile, model, history),
                       lambda result: self.show_answer(result, question),
                       on_error=self.reply.setPlainText)

    def show_answer(self, result, question=None):
        text = self.answer_text(result) or ('질문에 맞는 자료를 확인하지 못했습니다.'
                                            if result.get('status') == 'insufficient_evidence' else '답변을 받지 못했습니다.')
        self.record_chat('general', question, text)
        self.out_game.add_exchange(question, text)      # 전적 화면 채팅에도 같은 대화가 보이게
        self.render_general()
        self.status.setText('완료 · 대화는 이 PC에만 저장됩니다. · ' + ('Gemini 답변' if result['generated'] else '자료 검색 / 상태 안내'))

    def render_general(self, pending=None, conversation_id=None):
        """AI에게 질문 화면에 대화 전체를 보여 준다. pending은 아직 답을 기다리는 질문."""
        esc = html.escape
        conversation_id = conversation_id or self.chat_ids.get('general')
        messages = self.chats.messages(conversation_id) if conversation_id else []
        blocks = []
        self.general_view = (pending, conversation_id)      # 테마가 바뀌면 같은 내용을 새 색으로 다시 그린다
        tokens = theme.tokens
        for message in messages + ([{'role': 'user', 'text': pending}] if pending else []):
            # QTextBrowser는 둥근 모서리를 못 그려서 배경색 표로 말풍선을 만든다.
            user = message['role'] == 'user'
            who, color, fill = (('나', tokens['blue_fg'], tokens['blue_soft']) if user
                                else ('AI', tokens['accent_fg'], tokens['raised']))
            blocks.append('<table width="100%%" cellpadding="12" cellspacing="0" style="margin-bottom:10px">'
                          '<tr><td style="background-color:%s"><b style="color:%s">%s</b><br>'
                          '<span style="white-space:pre-wrap">%s</span></td></tr></table>'
                          % (fill, color, who, esc(message['text'])))
        muted = tokens['muted']
        if pending:
            blocks.append('<p style="color:%s">AI 답변을 준비하고 있습니다… 최대 약 60초 걸릴 수 있습니다.</p>' % muted)
        self.reply.setHtml(''.join(blocks) or '<p style="color:%s">아직 대화가 없습니다. 아래에 질문을 입력하세요. '
                                              '대화는 이 PC에만 저장되고, 이어지는 질문은 앞 대화를 기억해서 답합니다.</p>' % muted)
        bar = self.reply.verticalScrollBar()
        bar.setValue(bar.maximum())

    def refresh_chat_list(self):
        if not hasattr(self, 'chat_list'):
            return
        self.chat_list.blockSignals(True)
        self.chat_list.clear()
        self.chat_list.addItem('현재 대화', None)
        for chat in self.chats.conversations():
            when = datetime.fromtimestamp(chat['updated_at']).strftime('%m/%d %H:%M')
            self.chat_list.addItem('[%s] %s · %s' % (SCREEN_NAMES.get(chat['screen'], chat['screen']), chat['title'], when),
                                   (chat['id'], chat['screen']))
        self.chat_list.blockSignals(False)

    def open_chat(self, index):
        data = self.chat_list.itemData(index)
        if not data:
            self.render_general()
            return
        conversation_id, screen = data
        if screen == 'general':
            self.chat_ids['general'] = conversation_id       # 지난 일반 대화를 이어서 질문할 수 있다
            self.out_game.load_history(self.chats.messages(conversation_id))
        self.render_general(conversation_id=conversation_id)
        if screen != 'general':
            self.status.setText('%s 대화 기록입니다. 여기서 질문하면 일반 대화로 이어집니다.' % SCREEN_NAMES.get(screen, screen))

    def new_chat(self):
        self.chat_ids['general'] = None
        self.out_game.load_history([])
        self.chat_list.setCurrentIndex(0)
        self.render_general()
        self.status.setText('새 대화를 시작했습니다.')

    def clear_chats(self):
        answer = QMessageBox.question(self, '대화 기록 지우기', '이 PC에 저장된 AI 대화 기록을 모두 지울까요? 되돌릴 수 없습니다.')
        if answer != QMessageBox.Yes:
            return
        self.chats.clear()
        self.chat_ids = {'general': None, 'pick': None, 'in_game': None}
        self.out_game.load_history([])
        self.refresh_chat_list()
        self.render_general()
        self.status.setText('대화 기록을 모두 지웠습니다.')

    def sync_data(self):
        if self.jobs:
            return
        self.status.setText('공식 자료를 다운로드하고 있습니다. 실패하면 기존 DB를 유지합니다.')
        self.start_job(lambda: sync_database(self.live_path), self.synced)

    def synced(self, result):
        self.mode.setCurrentIndex(1)
        self.reload()
        self.status.setText('업데이트 완료 · 신규 %(new)s / 변경 %(updated)s / 동일 %(unchanged)s' % result)

    def closeEvent(self, event):
        if self.jobs:
            # 예전에는 작업(느린 AI 답변, 자료 업데이트)이 끝날 때까지 창을 닫을 수 없었다.
            # 창은 바로 숨기고, 실행 중인 스레드가 끝나면 그때 실제로 닫는다 (실행 중인 QThread를 지우면 앱이 죽는다).
            self.closing = True
            self.champ_timer.stop()
            self.hide()
            for job in self.jobs:
                job.finished.connect(self.close, Qt.QueuedConnection)
            event.ignore()
            return
        # 폴링 스레드가 끝난 뒤 다시 닫는다. 실행 중인 QThread를 지우면 앱이 비정상 종료된다.
        self.closing = True
        self.champ_timer.stop()
        if self.login_watcher is not None:
            self.login_watcher.stop()
        self.hotkey.unregister()
        self.augment_hotkey.unregister()
        self.recorder.cancel('')
        self.speaker.stop()
        for job in (self.poll_job, self.augment_job):
            if job is not None and job.isRunning():
                job.finished.connect(self.close)
                event.ignore()
                return
        event.accept()


def frozen_defaults():
    """배포판(PyInstaller)으로 실행 중이면 (데이터 폴더, .env 경로)를 사용자 폴더 기준으로 정한다.

    더블클릭으로 켜면 실행 위치가 일정하지 않아서 %LOCALAPPDATA%\\RiftFlow에 저장한다.
    서버 주소는 exe 옆의 server.txt에서 읽는다. 주소가 바뀌어도 다시 빌드하지 않고 이 파일만 고치면 된다.
    """
    if not getattr(sys, 'frozen', False):
        return Path('data'), Path('.env')
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'RiftFlow'
    server_file = Path(sys.executable).with_name('server.txt')
    try:
        url = server_file.read_text(encoding='utf-8').strip()
    except OSError:
        url = ''
    if url:
        os.environ.setdefault('RIFTFLOW_SERVER_URL', url)
    return base / 'data', base / '.env'


def main():
    data_default, env_default = frozen_defaults()
    parser = argparse.ArgumentParser(description='RiftFlow desktop MVP')
    parser.add_argument('--data-dir', type=Path, default=data_default)
    parser.add_argument('--env', type=Path, default=env_default)
    parser.add_argument('--screenshot', type=Path, help='오프라인 화면 캡처 후 종료')
    args = parser.parse_args()
    load_env(args.env)
    # 서버 기기 토큰도 데이터 폴더에 둔다.
    os.environ.setdefault('RIFTFLOW_DEVICE_TOKEN_PATH', str(Path(args.data_dir) / 'device_token'))
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle('Fusion')
    font = app.font()
    font.setFamilies(['Segoe UI', 'Malgun Gothic'])     # 영문은 Segoe UI, 한글은 맑은 고딕
    app.setFont(font)
    app.setPalette(theme.palette())
    theme.style(app, STYLE)
    window = Window(args.data_dir, auto_sync=getattr(sys, 'frozen', False) and not args.screenshot)
    window.show()
    window.apply_voice_settings()
    if args.screenshot:
        def capture():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(args.screenshot))
            app.quit()
        QTimer.singleShot(500, capture)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
