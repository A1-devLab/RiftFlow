"""Post-game result view, personal baseline and evidence-grounded review."""
import json
import sqlite3
import time

from knowledge.before_game import canonical_champion
from knowledge.documents import get_documents
from rag.gemini import GeminiError
from riot import get_post_game_summary

from .prompt import DEFAULT_REQUEST, SYSTEM


def _clock(seconds):
    seconds = max(0, int(seconds or 0))
    return '%02d:%02d' % (seconds // 60, seconds % 60)


def _kda_ratio(kills, deaths, assists):
    return round((kills + assists) / max(1, deaths), 2)


def describe_summary(summary, champion=None):
    """결과 화면 요약을 화면과 프롬프트가 함께 쓰는 형태로 만든다."""
    if summary is None:
        return None
    minutes = summary.game_duration_seconds / 60 if summary.game_duration_seconds else 0
    return {'result': summary.result, 'result_name': '승리' if summary.result == 'WIN' else '패배',
            'champion': champion or summary.champion_name,
            'duration_seconds': summary.game_duration_seconds,
            'clock': _clock(summary.game_duration_seconds),
            'kills': summary.kills, 'deaths': summary.deaths, 'assists': summary.assists,
            'kda': '%d/%d/%d' % (summary.kills, summary.deaths, summary.assists),
            'kda_ratio': _kda_ratio(summary.kills, summary.deaths, summary.assists),
            'cs': summary.cs, 'cs_per_min': round(summary.cs_per_min, 1),
            'kill_participation_pct': round(summary.kill_participation_pct),
            'damage_dealt': summary.damage_dealt, 'damage_taken': summary.damage_taken,
            'damage_per_min': round(summary.damage_dealt / minutes) if minutes else None,
            'vision_score': summary.vision_score,
            'vision_per_min': round(summary.vision_score / minutes, 2) if minutes else None}


def _average(matches):
    if not matches:
        return None
    count = len(matches)
    minutes = [m.game_duration_seconds / 60 for m in matches if m.game_duration_seconds]
    cs_rates = [(m.cs or 0) / (m.game_duration_seconds / 60) for m in matches
                if m.cs is not None and m.game_duration_seconds]
    damage_rates = [m.damage_to_champions / (m.game_duration_seconds / 60) for m in matches
                    if m.damage_to_champions is not None and m.game_duration_seconds]
    return {'games': count, 'wins': sum(1 for m in matches if m.win),
            'kills': round(sum(m.kills for m in matches) / count, 1),
            'deaths': round(sum(m.deaths for m in matches) / count, 1),
            'assists': round(sum(m.assists for m in matches) / count, 1),
            'kda_ratio': round(sum(_kda_ratio(m.kills, m.deaths, m.assists) for m in matches) / count, 2),
            'cs_per_min': round(sum(cs_rates) / len(cs_rates), 1) if cs_rates else None,
            'damage_per_min': round(sum(damage_rates) / len(damage_rates)) if damage_rates else None,
            'avg_minutes': round(sum(minutes) / len(minutes), 1) if minutes else None}


def baseline_from_matches(matches, champion=None):
    """앱이 마지막으로 불러온 최근 협곡 경기의 평균. 방금 끝난 경기는 포함되지 않는다.

    전체 이용자 통계가 아니라 이 계정의 기록이며, 표본 수를 함께 돌려준다.
    """
    classic = [m for m in matches or [] if m.game_mode == 'CLASSIC']
    same = [m for m in classic if champion and m.champion_name.casefold() == str(champion).casefold()]
    overall, by_champion = _average(classic), _average(same)
    if overall is None:
        return None
    return {'overall': overall, 'champion': by_champion, 'champion_name': champion if by_champion else None,
            'scope': '이 계정에서 앱이 마지막으로 불러온 소환사의 협곡 경기. 방금 끝난 경기는 포함되지 않음.'}


def wait_for_summary(should_stop, timeout=30.0, interval=1.0, fetch=get_post_game_summary, sleep=time.sleep):
    """결과 화면이 열릴 때까지 기다린다. 앱을 닫으면(should_stop) 바로 멈춘다."""
    deadline = time.monotonic() + timeout
    while not should_stop():
        summary = fetch()
        if summary is not None:
            return summary
        if time.monotonic() >= deadline:
            return None
        sleep(interval)
    return None


def _champion_reference(db_path, champion):
    if not champion:
        return None
    try:
        documents = get_documents(kind='champion', db_path=db_path)
    except (sqlite3.Error, OSError, ValueError):
        return None
    key = str(champion).casefold()
    doc = next((d for d in documents if key in (str(d.get('entity_id', '')).casefold(),
                                                 str(d.get('subject_name', '')).casefold())), None)
    if doc is None:
        return None
    return {'name': doc.get('subject_name'), 'version': doc.get('version'), 'text': doc.get('text', '')[:1200]}


def _live_snapshot(view):
    """게임 중 마지막으로 본 스코어보드 중 분석에 쓸 부분만 남긴다."""
    if not view or not view.get('in_game'):
        return None
    from game_phases.in_game.desktop import prompt_player
    me = view.get('me')
    return {'clock': view.get('clock'), 'me': prompt_player(me) if me else None,
            'enemies': [prompt_player(e) for e in view.get('enemies') or []],
            'team_gold_estimate': view.get('team_gold'),
            'note': '게임 종료 직전 마지막 갱신 시점의 값. 최종 결과와 약간 다를 수 있음.'}


def analyze_after_game(db_path, summary, *, generate, champion=None, matches=None,
                       live_view=None, question=None):
    """결과 화면 수치와 개인 평균만으로 잘한 점·아쉬운 점·개선점을 설명한다."""
    if summary is None:
        return {'answer': None, 'generated': False,
                'message': '결과 화면 데이터가 없습니다. 게임이 끝난 직후 결과 화면에서 다시 확인해 주세요.'}
    champion = champion or summary.champion_name
    payload = {'request': (question or '').strip() or DEFAULT_REQUEST,
               'game_result': describe_summary(summary, champion),
               'last_live_scoreboard': _live_snapshot(live_view),
               'personal_baseline': baseline_from_matches(matches, canonical_champion(db_path, champion)),
               'official_champion': _champion_reference(db_path, champion)}
    prompt = {'system': SYSTEM, 'user': json.dumps(payload, ensure_ascii=False)}
    try:
        reply = generate(prompt)
        return {'answer': reply['text'], 'message': None, 'generated': True}
    except GeminiError as error:
        return {'answer': None, 'message': error.message, 'generated': False}
