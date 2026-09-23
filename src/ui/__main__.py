"""Run the desktop MVP: python -m ui."""
import argparse
import html
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from knowledge.documents import get_documents
from rag.config import load_env
from rag.gemini import DEFAULT_MODEL, generate
from game_phases.out_game.prompt import build as build_out_game_prompt
from game_phases.out_game.service import classify as classify_out_game, search_text as out_game_search_text
from riot import get_current_summoner, get_recent_matches, get_solo_rank
from .pages.out_game import OutGamePage
from .services import ask_database, create_demo, sync_database

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
    def __init__(self, data_dir):
        super().__init__()
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.demo_path = self.data_dir / 'demo.db'
        self.live_path = self.data_dir / 'riftflow.db'
        create_demo(self.demo_path)
        self.jobs = []
        self.setWindowTitle('RiftFlow · Desktop MVP')
        self.resize(1360, 850)
        self.setMinimumSize(960, 690)
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        side = QFrame()
        side.setObjectName('sidebar')
        side.setFixedWidth(216)
        nav = QVBoxLayout(side)
        nav.setContentsMargins(22, 30, 22, 20)
        nav.addWidget(label('RiftFlow', 'brand'))
        nav.addWidget(label('선택의 이유를 배우다', 'muted'))
        nav.addSpacing(32)
        self.stack = QStackedWidget()
        self.nav_buttons = []
        for i, name in enumerate(('전적', '게임 자료', '코치에게 질문', '설정 및 데이터')):
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
        top = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(['예시 자료 · 오프라인', '수집한 자료 · 로컬 DB'])
        self.mode.currentIndexChanged.connect(self.reload)
        top.addWidget(self.mode)
        self.badge = label('예시 데이터', 'badge')
        self.badge.setWordWrap(False)
        top.addStretch()
        top.addWidget(self.badge)
        body.addLayout(top)
        body.addSpacing(12)
        body.addWidget(self.stack, 1)
        self.status = label('키 없이 예시 자료를 둘러볼 수 있습니다.', 'muted')
        body.addWidget(self.status)
        row.addLayout(body, 1)
        self.setCentralWidget(root)
        self.make_home()
        self.make_library()
        self.make_chat()
        self.make_settings()
        self.navigate(0)
        self.reload()

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
        self.stack.addWidget(self.out_game)

    def make_library(self):
        layout = self.page('게임 자료', '박시영의 수집 DB를 읽어 이름, 설명과 출처를 보여줍니다.')
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('이름 또는 내용 검색')
        self.search.textChanged.connect(self.filter_library)
        self.kind = QComboBox()
        for name, value in [('전체', None), ('아이템', 'item'), ('챔피언', 'champion'), ('룬', 'rune'), ('패치', 'patch')]:
            self.kind.addItem(name, value)
        self.kind.currentIndexChanged.connect(self.filter_library)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.kind)
        layout.addLayout(filters)
        split = QSplitter()
        self.listing = QListWidget()
        self.listing.currentRowChanged.connect(self.show_document)
        self.detail = browser()
        split.addWidget(self.listing)
        split.addWidget(self.detail)
        split.setSizes([300, 560])
        layout.addWidget(split, 1)

    def make_chat(self):
        layout = self.page('코치에게 질문', '자료 검색은 무료·로컬입니다. Gemini 사용을 켜면 질문과 검색 근거가 Google로 전송됩니다.')
        self.version = QComboBox()
        layout.addWidget(self.version)
        self.reply = browser()
        self.reply.setPlainText('예: 무한의 대검 가격과 조합 재료를 알려줘\n\n키가 없어도 관련 근거를 확인할 수 있습니다.\n현재 예시 자료는 과거 고정 버전이며 최신 게임 정보가 아닙니다.')
        layout.addWidget(self.reply, 1)
        self.ai = QCheckBox('Gemini 답변 사용 (API 키·모델 설정 필요, 사용량에 따라 과금)')
        layout.addWidget(self.ai)
        form = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setPlaceholderText('아이템·룬·챔피언에 대해 질문하세요')
        self.question.setMaxLength(1000)
        self.question.returnPressed.connect(self.ask)
        self.send = QPushButton('근거 찾기')
        self.send.setObjectName('primary')
        self.send.clicked.connect(self.ask)
        self.ai.toggled.connect(lambda on: self.send.setText('답변 요청' if on else '근거 찾기'))
        form.addWidget(self.question, 1)
        form.addWidget(self.send)
        layout.addLayout(form)

    def make_settings(self):
        layout = self.page('설정 및 데이터', 'API 연결 상태와 공식 게임 자료 업데이트를 관리합니다.')
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
        if not hasattr(self, 'listing'):
            return
        try:
            self.documents = get_documents(db_path=self.db_path)
        except Exception:
            self.documents = []
            self.status.setText('DB를 읽지 못했습니다. 파일 상태를 확인하세요.')
        demo = self.mode.currentIndex() == 0
        self.badge.setText('예시 데이터 · 최신 아님' if demo else '수집한 자료')
        self.version.clear()
        self.version.addItem('최신 수집 자료 · 패치 미지정 (출처별 버전 확인)', None)
        for version in sorted({d['version'] for d in self.documents}):
            self.version.addItem('출처 버전 ' + version, version)
        self.connection.setText('Gemini 키: %s  ·  Riot 키: %s' %
                                ('설정됨' if os.environ.get('GEMINI_API_KEY') else '미설정',
                                 '설정됨' if os.environ.get('RIOT_API_KEY') else '미설정'))
        self.filter_library()

    def filter_library(self, *_):
        if not hasattr(self, 'documents'):
            return
        query = self.search.text().strip().casefold()
        kind = self.kind.currentData()
        self.filtered = [d for d in self.documents if (kind is None or d['kind'] == kind)
                         and query in (d['title'] + ' ' + d['text']).casefold()]
        self.listing.clear()
        self.detail.clear()
        for doc in self.filtered:
            self.listing.addItem('%s\n%s · %s' % (doc['title'], doc['kind'], doc['version']))
        if self.filtered:
            self.listing.setCurrentRow(0)
        else:
            self.detail.setPlainText('표시할 자료가 없습니다. 검색 조건을 바꾸거나 공식 자료를 수집하세요.')

    def show_document(self, index):
        if index < 0 or index >= len(self.filtered):
            return
        doc = self.filtered[index]
        esc = html.escape
        self.detail.setHtml('<h2>%s</h2><p>출처 버전 %s</p><p style="white-space:pre-wrap">%s</p><p><a href="%s">공식 출처 열기</a></p>' %
                            (esc(doc['title']), esc(doc['version']), esc(doc['text']), esc(doc['source_url'], quote=True)))

    def start_job(self, function, callback):
        job = Job(function, self)
        self.jobs.append(job)
        self.send.setEnabled(False)
        self.sync.setEnabled(False)
        self.mode.setEnabled(False)
        self.out_game.set_busy(True)
        job.result.connect(callback)
        job.failed.connect(self.failed)
        job.finished.connect(lambda: self.job_done(job))
        job.start()

    def job_done(self, job):
        self.jobs.remove(job)
        job.deleteLater()
        self.send.setEnabled(True)
        self.sync.setEnabled(True)
        self.mode.setEnabled(True)
        self.out_game.set_busy(False)

    def failed(self, message):
        self.status.setText(message)
        self.reply.setPlainText(message)
        self.out_game.show_error(message)

    def ask_out_game(self, question):
        if self.jobs:
            return
        types = classify_out_game(question)
        analysis = {'phase': 'out_game', 'question_types': types}
        model = self.model.text().strip() or DEFAULT_MODEL
        generator = None
        if os.environ.get('GEMINI_API_KEY'):
            generator = lambda prompt: generate(prompt, model=model, retries=0)
        self.status.setText('게임 밖 코치 질문에 맞는 공식 자료를 찾고 있습니다.')
        self.start_job(
            lambda: ask_database(
                self.db_path,
                question,
                generate=generator,
                analysis=analysis,
                prompt_builder=build_out_game_prompt,
                retrieval_question=out_game_search_text(question, types),
            ),
            self.show_out_game_answer,
        )

    def show_out_game_answer(self, result):
        self.out_game.show_answer(result)
        self.status.setText('완료 · ' + ('Gemini 답변' if result['generated'] else '공식 자료 검색'))

    @staticmethod
    def riot_profile():
        player = get_current_summoner()
        return {
            'player': player,
            'rank': get_solo_rank(player.puuid),
            'matches': get_recent_matches(player.puuid, 20),
        }

    def load_riot_profile(self):
        if self.jobs:
            return
        self.status.setText('롤 클라이언트와 최근 전적을 확인하고 있습니다.')
        self.start_job(self.riot_profile, self.show_riot_profile)

    def show_riot_profile(self, payload):
        self.out_game.show_profile(payload)
        self.status.setText('로그인한 플레이어와 최근 전적을 불러왔습니다.')

    def ask(self):
        if self.jobs:
            return
        question = self.question.text().strip()
        if not question:
            return
        use_ai = self.ai.isChecked()
        model = self.model.text().strip()
        if use_ai and (not os.environ.get('GEMINI_API_KEY') or not model):
            self.reply.setPlainText('Gemini 키 또는 모델 ID가 없습니다. 설정 및 데이터 화면과 .env 설정을 확인하세요. 근거 검색만 하려면 Gemini 사용을 끄세요.')
            return
        path, version = self.db_path, self.version.currentData()
        generator = (lambda prompt: generate(prompt, model=model, retries=0)) if use_ai else None
        self.reply.setPlainText('질문에 맞는 근거를 찾고 있습니다…' + ('\nGemini 응답은 최대 약 60초 걸릴 수 있습니다.' if use_ai else ''))
        self.status.setText('예시 자료로 처리 중' if self.mode.currentIndex() == 0 else '수집한 DB로 처리 중')
        self.start_job(lambda: ask_database(path, question, version, generate=generator), self.show_answer)

    def show_answer(self, result):
        esc = html.escape
        if result['answer']:
            body = '<h2>코치의 답변</h2><p style="white-space:pre-wrap">%s</p>' % esc(result['answer'])
        elif result['message']:
            body = '<h2>안내</h2><p>%s</p>' % esc(result['message'])
        else:
            body = '<h2>관련 근거를 찾았어요</h2><p>아래는 검색한 자료입니다. AI가 생성한 답변이 아닙니다.</p>'
        for i, evidence in enumerate(result['evidence'], 1):
            doc = evidence['chunk']
            body += '<h3>근거 %d · %s</h3><p>버전 %s</p><p>%s</p><p><a href="%s">출처 확인</a></p>' % (
                i, esc(doc['title']), esc(doc['version']), esc(doc['text'][:1100]), esc(doc['source_url'], quote=True))
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
        else:
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
