"""Run the desktop MVP: python -m ui."""
import argparse
import html
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPushButton,
    QStackedWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from knowledge.documents import get_documents
from rag.config import load_env
from rag.gemini import DEFAULT_MODEL, generate
from riot import (LiveMatchStatus, get_gameflow_phase, get_match_detail, get_current_summoner, get_live_state,
                  get_recent_matches_with_details, get_solo_rank, start_login_watcher)
from game_phases.before_game.desktop import describe_session, answer_before_game, get_before_game_context
from game_phases.in_game.desktop import answer_in_game, describe_scoreboard, get_in_game_context
from knowledge.before_game import champion_catalog, save_recent_matchups, personal_context, rune_catalog, named_rune_page, canonical_champion
from knowledge.in_game import item_catalog
from .pages.out_game import OutGamePage
from .pages.before_game import BeforeGamePage
from .pages.in_game import InGamePage
from .match_detail import MatchDetailDialog
from .services import ask_general, create_demo, sync_database

STYLE = """
QWidget { background: #101722; color: #e8edf4; font-family: 'Arial'; font-size: 14px; }
QMainWindow { background: #101722; }
QFrame#sidebar { background: #0b111b; border-right: 1px solid #233043; }
QLabel#brand { color: #5de3c0; font-size: 26px; font-weight: bold; }
QLabel#heading { font-size: 28px; font-weight: bold; }
QLabel#muted { color: #97a8bd; }
QLabel#badge { background: #173a38; color: #72e2c7; border-radius: 8px; padding: 9px; }
QFrame#card { background: #182333; border: 1px solid #29394c; border-radius: 12px; }
QFrame#card QLabel { background: transparent; }
QLabel#metric { color: #6fe7c8; font-size: 30px; font-weight: bold; }
QPushButton { background: #223247; border: 1px solid #34475e; border-radius: 7px; padding: 11px 16px; }
QPushButton:hover { background: #2f4660; }
QPushButton:disabled { color: #64758a; background: #18212e; }
QPushButton#primary { background: #56d7b6; color: #09291f; border: none; font-weight: bold; }
QPushButton#nav { text-align: left; background: transparent; border: none; padding: 14px; }
QPushButton#nav:checked { background: #1b3439; color: #72e2c7; }
QComboBox, QLineEdit { background: #172334; border: 1px solid #354860; border-radius: 7px; padding: 10px; }
QListWidget, QTextBrowser { background: #151f2e; border: 1px solid #2a3a4f; border-radius: 9px; padding: 12px; }
QListWidget::item { padding: 12px; border-bottom: 1px solid #263449; }
QListWidget::item:selected { background: #234842; color: #a2f1dd; }
QCheckBox { spacing: 8px; }
QSplitter::handle { background: #101722; width: 12px; }
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
# 픽창이 끝나고 게임 화면이 뜨기 전(로딩 화면)에는 Live Client가 아직 열려 있지 않다.
# 이때 대기로 보면 전적 화면으로 튕겼다가 다시 인게임으로 넘어가므로 로딩으로 따로 구분한다.
LOADING_FLOWS = ('GameStart', 'InProgress', 'Reconnect')
# 단계가 바뀔 때 자동으로 보여 줄 화면. 대기(idle)는 없음 = 보고 있던 단계 화면에서 전적으로 돌아간다.
PHASE_PAGES = {'champ_select': PICK, 'loading': INGAME, 'in_game': INGAME}


def collect_phase(db_path):
    """게임 단계를 한 번에 판별한다: in_game / loading / champ_select / idle.

    단계마다 타이머를 따로 두면 LCU·Live Client 호출이 겹치므로 폴러 하나로 합쳤다.
    """
    state = get_live_state()
    if state.status is LiveMatchStatus.IN_GAME:
        view = describe_scoreboard(get_in_game_context(state), item_catalog(db_path))
        if view.get('in_game'):
            return {'phase': 'in_game', 'view': view}
    if get_gameflow_phase() in LOADING_FLOWS:
        return {'phase': 'loading'}
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

    def __init__(self, data_dir):
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
        self.personal_path = self.data_dir / "personal_matches.db"
        self.poll_job = None
        self.champ_session_active = False
        self.phase = 'idle'
        self.closing = False
        self.setWindowTitle('RiftFlow · Desktop MVP')
        self.resize(1580, 880)
        self.setMinimumSize(1180, 720)
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        side = QFrame()
        side.setObjectName('sidebar')
        side.setFixedWidth(216)
        nav = QVBoxLayout(side)
        nav.setContentsMargins(22, 30, 22, 20)
        nav.addWidget(label('RiftFlow', 'brand'))
        nav.addSpacing(32)
        self.stack = QStackedWidget()
        self.nav_buttons = []
        for i, name in enumerate(('전적', '픽창', '인게임', 'AI에게 질문', '설정 및 데이터')):
            button = QPushButton(name)
            button.setObjectName('nav')
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, index=i: self.navigate(index))
            nav.addWidget(button)
            self.nav_buttons.append(button)
        nav.addStretch()
        nav.addWidget(label('TEAM PROTOTYPE\nv0.2 · 비공개 개발용', 'muted'))
        row.addWidget(side)
        body = QVBoxLayout()
        body.setContentsMargins(28, 25, 28, 20)
        self.mode = QComboBox()
        self.mode.addItems(['예시 자료 · 오프라인', '수집한 자료 · 로컬 DB'])
        self.mode.currentIndexChanged.connect(self.reload)
        body.addWidget(self.stack, 1)
        self.status = label('키 없이 예시 자료를 둘러볼 수 있습니다.', 'muted')
        body.addWidget(self.status)
        row.addLayout(body, 1)
        self.setCentralWidget(root)
        self.make_home()
        self.make_before_game()
        self.make_in_game()
        self.make_chat()
        self.make_settings()
        self.navigate(HOME)
        try:
            has_live_data = self.live_path.exists() and bool(get_documents(db_path=self.live_path))
        except Exception:
            has_live_data = False
        if has_live_data:
            self.mode.setCurrentIndex(1)
        self.reload()
        self.riot_login_detected.connect(self.on_riot_login_detected)
        self.champ_timer = QTimer(self)
        self.champ_timer.setInterval(2500)
        self.champ_timer.timeout.connect(self.poll_champ_select)
        self.champ_timer.start()
        QTimer.singleShot(800, self.poll_champ_select)
        if os.environ.get('RIOT_API_KEY'):
            self.login_watcher = start_login_watcher(self.riot_login_detected.emit)
            self.status.setText('롤 클라이언트 로그인을 자동으로 기다리고 있습니다.')
        else:
            self.out_game.rank.setText('Riot API 키를 설정하면 롤 클라이언트 로그인을 자동 감지합니다.')

    def page(self, title, subtitle):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(16)
        layout.addWidget(label(title, 'heading'))
        layout.addWidget(label(subtitle, 'muted'))
        self.stack.addWidget(widget)
        return layout

    def make_home(self):
        self.out_game = OutGamePage()
        self.out_game.askRequested.connect(self.ask_out_game)
        self.out_game.profileRequested.connect(self.load_riot_profile)
        self.out_game.matchRequested.connect(self.load_match_detail)
        self.stack.addWidget(self.out_game)

    def make_before_game(self):
        self.before_game = BeforeGamePage()
        self.before_game.askRequested.connect(self.ask_before_game)
        self.before_game.refreshRequested.connect(self.poll_champ_select)
        self.before_game.personalContextChanged.connect(self.update_personal_matchup)
        self.stack.addWidget(self.before_game)

    def make_in_game(self):
        self.in_game = InGamePage()
        self.in_game.askRequested.connect(self.ask_in_game)
        self.in_game.refreshRequested.connect(self.poll_champ_select)
        self.stack.addWidget(self.in_game)

    def poll_champ_select(self):
        """게임 단계 폴링 (이름은 기존 연결을 위해 유지). 질문 작업 중에도 스코어보드는 계속 갱신한다."""
        if self.poll_job is not None or self.closing:
            return
        path = self.db_path
        job = Job(lambda: collect_phase(path), self)
        self.poll_job = job
        job.result.connect(self.on_phase)
        job.failed.connect(lambda _message: self.before_game.show_disconnected())
        job.finished.connect(self.finish_champ_poll)
        job.start()

    def on_phase(self, payload):
        if self.closing:
            return
        phase, previous = payload['phase'], self.phase
        self.phase = phase
        if phase == 'champ_select':
            self.on_champ_select((payload['session'], payload['catalog']))
        else:
            self.before_game.show_disconnected()
            self.champ_session_active = False
        if phase == 'in_game':
            self.in_game.show_view(payload['view'])
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
        if not os.environ.get('GEMINI_API_KEY'):
            self.in_game.answer.setPlainText('AI 답변에 필요한 GEMINI_API_KEY를 .env에 설정해 주세요.')
            return
        model = self.model.text().strip() or DEFAULT_MODEL
        path = self.db_path
        self.in_game.answer.setPlainText('현재 스코어보드와 공식 자료를 확인하고 있습니다…')
        self.start_job(
            lambda: answer_in_game(path, request['view'], request['question'],
                                   generate=lambda prompt: generate(prompt, model=model, retries=0)),
            self.show_in_game_answer, on_error=self.in_game.answer.setPlainText)

    def show_in_game_answer(self, result):
        self.in_game.answer.setPlainText(result['answer'] or result['message'] or '답변을 받지 못했습니다.')
        self.status.setText('인게임 답변 완료' if result['generated'] else '인게임 자료 확인 필요')

    def finish_champ_poll(self):
        job = self.poll_job
        self.poll_job = None
        if job is not None:
            job.deleteLater()

    def on_champ_select(self, payload):
        session, catalog = payload
        if session is None:
            self.before_game.show_disconnected()
            self.champ_session_active = False
            return
        view = describe_session(session, catalog)
        self.before_game.show_session(view)
        self.champ_session_active = True
        self.update_personal_matchup()

    def update_personal_matchup(self):
        if not self.riot_context:
            return
        view = self.before_game.view
        champion = self.before_game.champion.text().strip()
        if not champion:
            return
        from game_phases.before_game.desktop import opponent_for_lane
        opponent = self.before_game.opponent.text().strip() or opponent_for_lane(view)
        lane = (view.get('mine') or {}).get('position')
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
        if not os.environ.get('GEMINI_API_KEY'):
            self.before_game.answer.setPlainText('AI 답변에 필요한 GEMINI_API_KEY를 .env에 설정해 주세요.')
            return
        model = self.model.text().strip() or DEFAULT_MODEL
        puuid = self.riot_context['player'].puuid if self.riot_context else None
        self.before_game.answer.setPlainText('확정된 픽과 공식 자료를 확인하고 있습니다…')
        self.start_job(
            lambda: answer_before_game(
                self.db_path, self.personal_path, puuid, request['view'], request['question'],
                generate=lambda prompt: generate(prompt, model=model, retries=0),
                champion=request['champion'], opponent=request['opponent'],
                trade_preference=request['trade_preference'], lane_aggression=request['lane_aggression']),
            self.show_before_game_answer,
        )

    def show_before_game_answer(self, result):
        self.before_game.answer.setPlainText(result['answer'] or result['message'] or '답변을 받지 못했습니다.')
        self.status.setText('픽창 답변 완료' if result['generated'] else '픽창 자료 확인 필요')

    def make_chat(self):
        layout = self.page('AI에게 질문', '롤 전적 분석, 챔피언 추천, 연습 방법과 패치에 대해 질문하세요.')
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
        layout = self.page('설정 및 데이터', 'API 연결 상태와 공식 게임 자료 업데이트를 관리합니다.')
        layout.addWidget(label('AI가 참고할 자료', 'heading'))
        layout.addWidget(self.mode)
        layout.addWidget(label('AI는 일반 지식과 연결된 전적을 활용하고, 선택한 자료도 보조로 참고합니다. 예시 자료는 과거 버전의 소량 데이터입니다. 실제 사용 시 공식 자료를 업데이트하세요.', 'muted'))
        self.connection = label('', 'badge')
        layout.addWidget(self.connection)
        self.model = QLineEdit(os.environ.get('GEMINI_MODEL') or DEFAULT_MODEL)
        self.model.setPlaceholderText('Google AI Studio에서 사용 가능한 Gemini 모델 ID')
        layout.addWidget(self.model)
        self.sync = QPushButton('공식 게임 자료 수집 / 업데이트')
        self.sync.setObjectName('primary')
        self.sync.clicked.connect(self.sync_data)
        layout.addWidget(self.sync)
        layout.addWidget(label('Data Dragon과 최근 패치 노트 3개를 로컬 DB에 저장합니다. 라이엇 키는 필요하지 않습니다. 자동 예약 업데이트는 아닙니다.', 'muted'))
        portal = QPushButton('라이엇 개발자 포털 열기')
        portal.clicked.connect(lambda: open_link(QUrl('https://developer.riotgames.com/')))
        layout.addWidget(portal)
        layout.addWidget(label('Riot API 키와 Gemini API 키는 .env에서 관리합니다. 실제 키는 채팅이나 GitHub에 올리지 마세요.\n\n라이엇 신청 기록: docs/riot-application.md', 'muted'))
        layout.addStretch()
        layout.addWidget(label(LEGAL, 'muted'))

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
        try:
            self.documents = get_documents(db_path=self.db_path)
        except Exception:
            self.documents = []
            self.status.setText('DB를 읽지 못했습니다. 파일 상태를 확인하세요.')
        self.connection.setText('Gemini 키: %s  ·  Riot 키: %s' %
                                ('설정됨' if os.environ.get('GEMINI_API_KEY') else '미설정',
                                 '설정됨' if os.environ.get('RIOT_API_KEY') else '미설정'))

    def start_job(self, function, callback, on_error=None):
        job = Job(function, self)
        self.jobs.append(job)
        self.send.setEnabled(False)
        self.sync.setEnabled(False)
        self.mode.setEnabled(False)
        self.out_game.set_busy(True)
        self.before_game.send.setEnabled(False)
        self.before_game.refresh.setEnabled(False)
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
        self.before_game.send.setEnabled(True)
        self.before_game.refresh.setEnabled(True)
        self.in_game.set_busy(False)
        if not self.jobs and self.pending_riot_player is not None:
            player = self.pending_riot_player
            self.pending_riot_player = None
            QTimer.singleShot(0, lambda: self.load_riot_profile(player))

    def failed(self, message):
        self.status.setText(message)
        self.reply.setPlainText(message)
        self.before_game.answer.setPlainText(message)
        self.out_game.show_error(message)

    def ask_out_game(self, question):
        if self.jobs:
            return
        if not os.environ.get('GEMINI_API_KEY'):
            self.out_game.show_error('AI 답변에 필요한 GEMINI_API_KEY를 .env에 설정한 뒤 앱을 다시 실행하세요.')
            return
        model = self.model.text().strip() or DEFAULT_MODEL
        path, profile = self.db_path, self.riot_context
        self.status.setText('AI 답변을 준비하고 있습니다.')
        self.start_job(
            lambda: ask_general(path, question, profile=profile,
                                generate=lambda prompt: generate(prompt, model=model, retries=0)),
            self.show_out_game_answer,
        )

    def show_out_game_answer(self, result):
        self.out_game.show_answer(result)
        self.status.setText('완료 · ' + ('Gemini 답변' if result['generated'] else '공식 자료 검색'))

    def riot_profile(self, player=None):
        player = player or get_current_summoner()
        matches, details = get_recent_matches_with_details(player.puuid, 20)
        save_recent_matchups(self.personal_path, player.puuid, details)
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
        self.start_job(lambda: self.riot_profile(player), self.show_riot_profile)

    def show_riot_profile(self, payload):
        self.riot_context = payload
        self.out_game.show_profile(payload)
        self.match_cache.update({d.get('metadata', {}).get('matchId'): d
                                 for d in payload.get('details', []) if d.get('metadata', {}).get('matchId')})
        self.update_personal_matchup()
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
        model = self.model.text().strip() or DEFAULT_MODEL
        if not os.environ.get('GEMINI_API_KEY'):
            self.reply.setPlainText('AI 답변에 필요한 Gemini API 키가 없습니다. .env 파일에 GEMINI_API_KEY를 설정한 뒤 앱을 다시 실행하세요.')
            return
        path, profile = self.db_path, self.riot_context
        generator = lambda prompt: generate(prompt, model=model, retries=0)
        self.reply.setPlainText('AI 답변을 준비하고 있습니다…\n응답은 최대 약 60초 걸릴 수 있습니다.')
        self.status.setText('연결된 전적과 질문을 바탕으로 답변 중' if profile else '질문을 바탕으로 답변 중')
        self.start_job(lambda: ask_general(path, question, generate=generator, profile=profile), self.show_answer)

    def show_answer(self, result):
        esc = html.escape
        if result['answer']:
            body = '<h2>AI 답변</h2><p style="white-space:pre-wrap">%s</p>' % esc(result['answer'])
        elif result['status'] == 'insufficient_evidence':
            body = '<h2>참고 자료가 부족합니다</h2><p>%s</p>' % esc(result['message'] or '질문에 맞는 자료를 확인하지 못했습니다.')
        elif result['message']:
            body = '<h2>안내</h2><p>%s</p>' % esc(result['message'])
        else:
            body = '<h2>관련 근거를 찾았어요</h2><p>아래는 검색한 자료입니다. AI가 생성한 답변이 아닙니다.</p>'
        self.reply.setHtml(body)
        self.status.setText('완료 · 이번 대화는 저장하지 않습니다. · ' + ('Gemini 답변' if result['generated'] else '자료 검색 / 상태 안내'))

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
            self.status.setText('진행 중인 작업이 끝난 뒤 종료할 수 있습니다.')
            event.ignore()
            return
        # 폴링 스레드가 끝난 뒤 다시 닫는다. 실행 중인 QThread를 지우면 앱이 비정상 종료된다.
        self.closing = True
        self.champ_timer.stop()
        if self.poll_job is not None and self.poll_job.isRunning():
            self.poll_job.finished.connect(self.close)
            event.ignore()
            return
        event.accept()


def main():
    parser = argparse.ArgumentParser(description='RiftFlow desktop MVP')
    parser.add_argument('--data-dir', type=Path, default=Path('data'))
    parser.add_argument('--env', type=Path, default=Path('.env'))
    parser.add_argument('--screenshot', type=Path, help='오프라인 화면 캡처 후 종료')
    args = parser.parse_args()
    load_env(args.env)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = Window(args.data_dir)
    window.show()
    if args.screenshot:
        def capture():
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(args.screenshot))
            app.quit()
        QTimer.singleShot(500, capture)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
