"""Live scoreboard view model and evidence-grounded in-game coaching."""
import json
import sqlite3
from functools import partial

from knowledge.documents import get_documents
from knowledge.in_game import champion_profiles, team_composition
from rag.gemini import GeminiError
from rag.knowledge_source import DocumentSource
from rag.retrieve import search

from .service import get_in_game_context

POSITIONS = ('TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY', 'NONE')
POSITION_NAMES = {'TOP': '탑', 'JUNGLE': '정글', 'MIDDLE': '미드', 'BOTTOM': '원딜',
                  'UTILITY': '서폿', 'NONE': '미정'}
ITEM_QUESTION_WORDS = ('아이템', '템', '빌드', '살까', '사야', '뭐사', '구매', '코어')
GOLD_NOTE = '보유 아이템 가격 합계로 낸 추정치. 아직 쓰지 않은 골드는 빠져 있어 실제보다 적거나 같다.'
RECOMMEND_QUESTION = '지금 상황에서 다음에 살 아이템을 추천해줘'

__all__ = ['get_in_game_context', 'describe_scoreboard', 'answer_in_game', 'is_item_question',
           'RECOMMEND_QUESTION']


def clock(seconds):
    if seconds is None:
        return None
    seconds = max(0, int(seconds))
    return '%02d:%02d' % (seconds // 60, seconds % 60)


def _same_player(name, active):
    """활성 플레이어 이름은 '이름' 또는 '이름#태그'로 오고, 스코어보드는 어느 한쪽일 수 있다."""
    if not name or not active:
        return False
    a, b = name.casefold(), active.casefold()
    return a == b or a.split('#')[0] == b.split('#')[0]


def _entry(player, catalog, minutes, is_me):
    items = []
    for item in sorted(player.items or [], key=lambda i: i.get('slot', 99)):
        try:
            item_id = int(item.get('itemID'))
        except (TypeError, ValueError):
            continue
        known = catalog.get(item_id)
        items.append({'id': item_id, 'slot': item.get('slot'),
                      'name': known['name'] if known else (item.get('displayName') or '확인 안 된 아이템')})
    position = (player.position or 'NONE').upper()
    return {'name': player.summoner_name or '플레이어', 'champion': player.champion_name or '알 수 없음',
            'team': player.team, 'position': position,
            'position_name': POSITION_NAMES.get(position, position),
            'level': player.level, 'kills': player.kills, 'deaths': player.deaths,
            'assists': player.assists, 'kda': '%d/%d/%d' % (player.kills, player.deaths, player.assists),
            'cs': int(player.cs or 0),
            'cs_per_min': round((player.cs or 0) / minutes, 1) if minutes >= 1 else None,
            'items': items, 'estimated_gold': int(player.estimated_gold or 0),
            'is_dead': player.is_dead, 'respawn_timer': round(player.respawn_timer or 0),
            'is_me': is_me}


def _position_order(entry):
    return POSITIONS.index(entry['position']) if entry['position'] in POSITIONS else len(POSITIONS)


def describe_scoreboard(context, catalog):
    """스코어보드를 화면과 프롬프트가 함께 쓰는 형태로 정리한다. 게임 중이 아니면 in_game=False.

    '나'를 못 찾으면 ORDER를 아군으로 두고 perspective_known=False로 표시한다.
    """
    scoreboard = (context or {}).get('scoreboard')
    if not scoreboard:
        return {'in_game': False}
    elapsed = getattr(context.get('state'), 'elapsed_seconds', None)
    minutes = (elapsed or 0) / 60
    active = context.get('active_player_name')
    me_raw = next((p for p in scoreboard if _same_player(p.summoner_name, active)), None)
    my_team = me_raw.team if me_raw else 'ORDER'
    entries = [_entry(p, catalog, minutes, p is me_raw) for p in scoreboard]
    allies = sorted((e for e in entries if e['team'] == my_team), key=_position_order)
    enemies = sorted((e for e in entries if e['team'] != my_team), key=_position_order)
    gold = context.get('team_gold')
    team_gold = None
    if gold is not None:
        ally_gold = gold.order if my_team == 'ORDER' else gold.chaos
        enemy_gold = gold.chaos if my_team == 'ORDER' else gold.order
        team_gold = {'ally': int(ally_gold), 'enemy': int(enemy_gold),
                     'diff': int(ally_gold - enemy_gold), 'note': GOLD_NOTE}
    me = next((e for e in entries if e['is_me']), None)
    return {'in_game': True, 'elapsed_seconds': elapsed, 'clock': clock(elapsed),
            'me': me, 'perspective_known': me is not None, 'my_team': my_team,
            'allies': allies, 'enemies': enemies, 'team_gold': team_gold}


def is_item_question(question):
    text = (question or '').replace(' ', '')
    return any(word in text for word in ITEM_QUESTION_WORDS)


def prompt_player(entry):
    """프롬프트에는 아이템 이름만 넣는다 (숫자 ID 비노출)."""
    data = {key: entry[key] for key in ('champion', 'position_name', 'level', 'kda', 'cs',
                                        'cs_per_min', 'estimated_gold', 'is_dead', 'respawn_timer')}
    data['items'] = [item['name'] for item in entry['items']]
    return data


def _item_hints(me, composition, profiles):
    """아이템 문서 검색어 보강. 상대 조합과 내 챔피언 지표에서 공식 설명에 쓰이는 단어를 고른다.

    검색 순위만 돕는다. 어떤 아이템을 고를지는 공식 설명을 본 모델이 정한다.
    """
    hints = []
    ratings = composition.get('damage_rating_counts') or {}
    if ratings.get('AP', 0) >= 2:
        hints.append('마법 저항력')
    if ratings.get('AD', 0) >= 2:
        hints.append('방어력')
    if (composition.get('tag_counts') or {}).get('Tank', 0) >= 2:
        hints.append('관통력 최대 체력')
    mine = profiles.get(str(me.get('champion', '')).casefold()) if me else None
    if mine and mine.get('damage_rating') == 'AP':
        hints.append('주문력')
    elif mine and mine.get('damage_rating') == 'AD':
        hints.append('공격력')
    return ' '.join(hints)


def answer_in_game(db_path, view, question, *, generate):
    """확인된 스코어보드와 공식 아이템·챔피언 문서만으로 답한다. 시야·쿨타임은 다루지 않는다."""
    from .prompt import SYSTEM

    if not view or not view.get('in_game'):
        return {'answer': None, 'message': '게임 중이 아닙니다. 게임에 접속하면 실시간 스코어보드로 답합니다.',
                'generated': False}
    me = view.get('me')
    enemies = view.get('enemies') or []
    profiles = champion_profiles(db_path)
    composition = team_composition([e['champion'] for e in enemies], profiles)
    wants_items = is_item_question(question)
    items, champions = [], []
    try:
        source = DocumentSource(partial(get_documents, db_path=db_path), kinds=('item', 'champion'))
        chunks = source.chunks(None)
        owned = {item['name'] for item in (me or {}).get('items', [])}
        query = ' '.join([question, _item_hints(me, composition, profiles)])
        for row in search([c for c in chunks if c['kind'] == 'item'], query, top_k=8 if wants_items else 4):
            chunk = row['chunk']
            if chunk['subject_name'] in owned:
                continue
            items.append({'name': chunk['subject_name'], 'version': chunk['version'],
                          'price': (chunk.get('fields') or {}).get('gold_total'),
                          'text': chunk['text'][:700]})
        wanted = {str(c).casefold() for c in [(me or {}).get('champion')] + [e['champion'] for e in enemies] if c}
        seen = set()
        for chunk in chunks:
            if chunk['kind'] != 'champion' or chunk['doc_id'] in seen:
                continue
            if {chunk['subject_name'].casefold(), chunk['entity_id'].casefold()} & wanted:
                seen.add(chunk['doc_id'])
                champions.append({'name': chunk['subject_name'], 'version': chunk['version'],
                                  'text': chunk['text'][:600]})
    except (sqlite3.Error, OSError, ValueError):
        items, champions = [], []
    if wants_items and not items:
        return {'answer': None, 'generated': False,
                'message': '추천 근거로 쓸 공식 아이템 자료가 없습니다. 설정 및 데이터에서 공식 자료를 먼저 업데이트해 주세요.'}
    payload = {'question': question, 'clock': view.get('clock'),
               'perspective_known': view.get('perspective_known'),
               'me': prompt_player(me) if me else None,
               'allies': [prompt_player(e) for e in view.get('allies') or [] if not e['is_me']],
               'enemies': [prompt_player(e) for e in enemies],
               'team_gold_estimate': view.get('team_gold'),
               'enemy_composition': composition,
               'official_items': items, 'official_champions': champions[:6]}
    prompt = {'system': SYSTEM, 'user': json.dumps(payload, ensure_ascii=False)}
    try:
        reply = generate(prompt)
        return {'answer': reply['text'], 'message': None, 'generated': True}
    except GeminiError as error:
        return {'answer': None, 'message': error.message, 'generated': False}
