"""Completed match statistics, with a team comparison and per-player details."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter, QFontMetrics
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHeaderView, QLabel, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QAbstractItemView, QStackedWidget, QWidget, QHBoxLayout, QPushButton, QScrollArea,
)

GROUPS = {
    '전투': [('kills', '킬'), ('deaths', '데스'), ('assists', '어시스트'),
        ('champLevel', '챔피언 레벨'), ('largestKillingSpree', '최대 연속 킬'),
        ('largestMultiKill', '최대 멀티 킬'), ('doubleKills', '더블 킬'),
        ('tripleKills', '트리플 킬'), ('quadraKills', '쿼드라 킬'), ('pentaKills', '펜타 킬'),
        ('totalTimeSpentDead', '총 사망 시간 (초)'), ('timeCCingOthers', '적 CC 시간 (초)')],
    '피해량': [('totalDamageDealtToChampions', '챔피언에게 가한 총 피해'),
        ('physicalDamageDealtToChampions', '챔피언에게 가한 물리 피해'),
        ('magicDamageDealtToChampions', '챔피언에게 가한 마법 피해'),
        ('trueDamageDealtToChampions', '챔피언에게 가한 고정 피해'),
        ('totalDamageDealt', '전체 대상에게 가한 총 피해'),
        ('physicalDamageDealt', '전체 물리 피해'), ('magicDamageDealt', '전체 마법 피해'),
        ('trueDamageDealt', '전체 고정 피해'), ('totalDamageTaken', '받은 총 피해'),
        ('physicalDamageTaken', '받은 물리 피해'), ('magicDamageTaken', '받은 마법 피해'),
        ('trueDamageTaken', '받은 고정 피해'), ('damageSelfMitigated', '경감한 피해')],
    '회복·보호막': [('totalHeal', '총 회복량 (자신 포함)'),
        ('totalHealsOnTeammates', '아군 회복량'), ('totalUnitsHealed', '회복한 유닛 수'),
        ('totalDamageShieldedOnTeammates', '아군에게 제공한 보호막으로 막은 피해')],
    '시야': [('visionScore', '시야 점수'), ('wardsPlaced', '와드 설치'),
        ('wardsKilled', '와드 제거'), ('visionWardsBoughtInGame', '제어 와드 구매'),
        ('detectorWardsPlaced', '제어 와드 설치'), ('sightWardsBoughtInGame', '투명 와드 구매')],
    '골드·파밍': [('goldEarned', '획득 골드'), ('goldSpent', '사용 골드'),
        ('totalMinionsKilled', '미니언 처치'), ('neutralMinionsKilled', '정글 몬스터 처치'),
        ('totalAllyJungleMinionsKilled', '아군 정글 몬스터 처치'),
        ('totalEnemyJungleMinionsKilled', '적 정글 몬스터 처치'), ('itemsPurchased', '아이템 구매 횟수'),
        ('consumablesPurchased', '소모품 구매 횟수')],
    '오브젝트': [('damageDealtToObjectives', '오브젝트 피해'),
        ('damageDealtToTurrets', '포탑 피해'), ('turretKills', '포탑 파괴'),
        ('turretTakedowns', '포탑 파괴 관여'), ('inhibitorKills', '억제기 파괴'),
        ('inhibitorTakedowns', '억제기 파괴 관여'), ('dragonKills', '드래곤 처치'),
        ('baronKills', '바론 처치'), ('objectivesStolen', '오브젝트 스틸'),
        ('objectivesStolenAssists', '오브젝트 스틸 어시스트')],
}


def value(raw):
    if raw is None:
        return '—'
    if isinstance(raw, bool):
        return '예' if raw else '아니오'
    if isinstance(raw, float):
        return f'{raw:,.2f}'
    if isinstance(raw, int):
        return f'{raw:,}'
    return str(raw)


def table(headers, rows):
    widget = QTableWidget(len(rows), len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
    widget.setAlternatingRowColors(True)
    widget.verticalHeader().hide()
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            widget.setItem(r, c, QTableWidgetItem(str(text)))
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    return widget


class StatBars(QWidget):
    """One bar per statistic, with exact values alongside scaled bars."""
    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.rows = [(str(label), number) for label, number in rows]
        self.setMinimumHeight(max(150, len(self.rows) * 44 + 34))
        self.setMinimumWidth(570)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor('#152034'))
        left = 240
        track_width = max(100, self.width() - left - 132)
        max_value = max((float(raw) for _, raw in self.rows
                         if isinstance(raw, (float, int)) and not isinstance(raw, bool) and raw >= 0), default=0)
        metrics = QFontMetrics(self.font())
        for i, (label, raw) in enumerate(self.rows):
            y = 22 + i * 44
            painter.setPen(QColor('#cfddf1'))
            painter.drawText(14, y + 19, metrics.elidedText(label, Qt.ElideRight, 210))
            painter.fillRect(QRectF(left, y + 4, track_width, 16), QColor('#273850'))
            if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 0 and max_value:
                painter.fillRect(QRectF(left, y + 4, max(2, track_width * raw / max_value), 16), QColor('#64a5ff'))
            painter.setPen(QColor('#ffffff'))
            painter.drawText(left + track_width + 12, y + 19, value(raw))
        painter.end()


class MatchDetailDialog(QDialog):
    def __init__(self, detail, puuid, parent=None):
        super().__init__(parent)
        self.setWindowTitle('경기 상세 통계')
        self.resize(1080, 760)
        self.setStyleSheet('''
            QDialog, QTabWidget::pane, QStackedWidget, QScrollArea { background: #101722; color: #e8edf4; }
            QLabel, QTabBar { color: #e8edf4; }
            QComboBox, QPushButton { background: #223247; color: #e8edf4; border: 1px solid #41536c; border-radius: 6px; padding: 7px; }
            QPushButton:disabled { background: #325c8d; color: #ffffff; }
            QTabBar::tab { background: #1b293b; color: #c6d3e6; padding: 8px 12px; margin-right: 2px; }
            QTabBar::tab:selected { background: #325c8d; color: #ffffff; }
            QTableWidget { background: #172334; alternate-background-color: #202e41; color: #e8edf4; gridline-color: #34445a; }
            QHeaderView::section { background: #223247; color: #e8edf4; padding: 8px; }
        ''')
        self.info = detail['info']
        self.players = sorted(self.info['participants'], key=lambda p: p.get('teamId', 0))
        layout = QVBoxLayout(self)
        seconds = self.info.get('gameDuration', 0)
        layout.addWidget(QLabel(f"{self.info.get('gameMode', '')} · {seconds // 60:02d}:{seconds % 60:02d} · {detail.get('metadata', {}).get('matchId', '')}"))
        layout.addWidget(QLabel('플레이어를 선택하면 개별 통계가 표시됩니다. — 는 API에서 제공하지 않은 항목입니다.'))
        self.player = QComboBox()
        selected = 0
        for i, p in enumerate(self.players):
            name = p.get('riotIdGameName') or p.get('summonerName') or '플레이어'
            self.player.addItem(f"{'블루' if p.get('teamId') == 100 else '레드'} · {p.get('championName', '')} · {name}" + (' (나)' if p.get('puuid') == puuid else ''))
            if p.get('puuid') == puuid:
                selected = i
        self.player.setCurrentIndex(selected)
        layout.addWidget(self.player)
        switch = QHBoxLayout()
        self.chart_button = QPushButton('그래프로 보기')
        self.number_button = QPushButton('수치로 보기')
        switch.addWidget(self.chart_button)
        switch.addWidget(self.number_button)
        switch.addStretch()
        layout.addLayout(switch)
        self.chart_button.clicked.connect(lambda: self.set_view(1))
        self.number_button.clicked.connect(lambda: self.set_view(0))
        self.view_mode = 0
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.player.currentIndexChanged.connect(self.render)
        self.render(selected)

    def set_view(self, mode):
        self.view_mode = mode
        for stack in self.stacks:
            stack.setCurrentIndex(mode)
        self.chart_button.setEnabled(mode != 1)
        self.number_button.setEnabled(mode != 0)

    def add_stat_tab(self, title, headers, rows, graph_rows):
        stack = QStackedWidget()
        stack.addWidget(table(headers, rows))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(StatBars(graph_rows))
        stack.addWidget(scroll)
        stack.setCurrentIndex(self.view_mode)
        self.tabs.addTab(stack, title)
        self.stacks.append(stack)

    def render(self, index):
        while self.tabs.count():
            widget = self.tabs.widget(0)
            self.tabs.removeTab(0)
            widget.deleteLater()
        self.stacks = []
        p = self.players[index]
        rows = []
        for other in self.players:
            rows.append([
                '블루' if other.get('teamId') == 100 else '레드',
                other.get('championName', ''), '승리' if other.get('win') else '패배',
                ' / '.join(value(other.get(k)) for k in ('kills', 'deaths', 'assists')),
                *[value(other.get(k)) for k in ('totalDamageDealtToChampions', 'totalDamageTaken', 'totalHeal', 'visionScore', 'goldEarned')],
            ])
        self.add_stat_tab('전체 비교', ['팀', '챔피언', '결과', 'K / D / A', '챔피언 딜량', '받은 피해', '총 회복량', '시야 점수', '획득 골드'], rows,
                          [(f"{other.get('championName', '플레이어')} · {'블루' if other.get('teamId') == 100 else '레드'}", other.get('totalDamageDealtToChampions')) for other in self.players])
        for title, fields in GROUPS.items():
            self.add_stat_tab(title, ['통계', '값'], [(label, value(p.get(key))) for key, label in fields], [(label, p.get(key)) for key, label in fields])
        known = {key for fields in GROUPS.values() for key, _ in fields}
        extras = [(key, value(raw)) for key, raw in sorted(p.items())
                  if key not in known and isinstance(raw, (int, float, bool))]
        extras += [('challenges.' + key, value(raw)) for key, raw in sorted((p.get('challenges') or {}).items())
                   if isinstance(raw, (int, float, bool))]
        self.add_stat_tab('추가 통계', ['추가 통계 (API 항목명)', '값'], extras, [(key, raw) for key, raw in sorted(p.items()) if key not in known and isinstance(raw, (int, float))] + [('challenges.' + key, raw) for key, raw in sorted((p.get('challenges') or {}).items()) if isinstance(raw, (int, float))])
        self.set_view(self.view_mode)
