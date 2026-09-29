"""Champion-select view model and evidence-grounded pre-game coaching."""
import json
import sqlite3
from pathlib import Path

from knowledge.before_game import champion_catalog, personal_context, rune_catalog, named_rune_page, canonical_champion
from knowledge.documents import get_documents, item_map_for
from knowledge.in_game import current_names
from rag.gemini import GeminiError
from rag.knowledge_source import DocumentSource
from rag.retrieve import search

from riot import get_champ_select_session


# LCU gameMode 코드 → 화면 이름. 모르는 코드는 코드 그대로 보여 준다.
MODE_NAMES = {'CLASSIC': '소환사의 협곡', 'ARAM': '칼바람 나락', 'URF': 'U.R.F.', 'CHERRY': '아레나',
              'ONEFORALL': '단일 챔피언', 'NEXUSBLITZ': '넥서스 돌격', 'ULTBOOK': '궁극기 주문서',
              'PRACTICETOOL': '연습 모드', 'TUTORIAL': '튜토리얼'}


def get_before_game_context():
    return get_champ_select_session()


def describe_session(session, catalog):
    """픽창을 화면용으로 정리한다.

    selected: 확정했거나 올려놓은 챔피언이 있음. locked: 확정함. hovering: 올려놓기만 함.
    상대의 올려놓기는 라이엇이 보여 주지 않으므로 상대는 확정한 챔피언만 나온다.
    """
    locked_cells = getattr(session, 'locked_cell_ids', None)

    def entry(member):
        shown = member.champion_id or getattr(member, 'champion_pick_intent', 0)
        locked = bool(member.champion_id) and (locked_cells is None or member.cell_id in locked_cells)
        champion = catalog.get(shown, {})
        return {'champion': champion.get('name') or ('선택 전' if not shown else f'확인 안 된 ID {shown}'),
                'id': champion.get('id'), 'position': member.assigned_position or '미정',
                'locked': locked, 'selected': bool(shown), 'hovering': bool(shown) and not locked}
    mine = next((m for m in session.my_team if m.cell_id == session.local_player_cell_id), None)
    game_mode = getattr(session, 'game_mode', None)
    return {'game_mode': game_mode, 'mode_name': MODE_NAMES.get(game_mode, game_mode) if game_mode else None,
            'mine': entry(mine) if mine else None,
            'allies': [entry(m) for m in session.my_team],
            'enemies': [entry(m) for m in session.their_team],
            'ally_bans': [catalog.get(i, {}).get('name', str(i)) for i in session.my_bans],
            'enemy_bans': [catalog.get(i, {}).get('name', str(i)) for i in session.their_bans]}


def opponent_for_lane(view):
    mine = view.get('mine') or {}
    lane = mine.get('position')
    if lane in (None, '미정'):
        return None
    opponents = [p for p in view['enemies'] if p['position'].casefold() == lane.casefold() and p['locked']]
    return opponents[0]['champion'] if len(opponents) == 1 else None


def answer_before_game(db_path, personal_db_path, puuid, view, question, *, generate,
                       champion=None, opponent=None, user_requests=None, observations=None):
    # observations를 주면 개인 기록 파일 대신 그 값을 쓴다 (서버: 앱이 계산해 보낸 개인 상성 기록).
    """Ground verified game facts in DB and personal observations; never invent matchup rates."""
    champion = (champion or (view.get('mine') or {}).get('champion') or '').strip()
    opponent = (opponent or opponent_for_lane(view) or '').strip()
    if champion in ('선택 전', ''):
        return {'answer': None, 'message': '내 챔피언을 선택하거나 입력해 주세요.', 'generated': False}
    try:
        source = DocumentSource(lambda patch=None, kind=None: get_documents(patch, kind, db_path=db_path))
        chunks = source.chunks(None)
        evidence = search(chunks, f'{champion} {opponent} {question}', top_k=5)
        # Name matches stay available even when lexical search misses the champion.
        ids = {row['chunk']['doc_id'] for row in evidence}
        for name in (champion, opponent):
            exact = next((c for c in chunks if c['kind'] == 'champion' and
                          name.casefold() in (c['subject_name'].casefold(), c['entity_id'].casefold())), None)
            if exact and exact['doc_id'] not in ids:
                evidence.append({'chunk': exact, 'score': 0, 'reasons': ['정확한 챔피언']})
                ids.add(exact['doc_id'])
    except (sqlite3.Error, OSError, ValueError):
        evidence = []
    if not evidence:
        return {'answer': None, 'message': '공식 챔피언·룬 자료가 없습니다. 설정 및 데이터에서 공식 자료를 먼저 업데이트해 주세요.', 'generated': False}
    if observations is None and puuid:
        observations = personal_context(personal_db_path, puuid, canonical_champion(db_path, champion),
                                        canonical_champion(db_path, opponent),
                                        (view.get('mine') or {}).get('position'))
    observations = dict(observations) if observations else None
    if observations and observations.get('latest_rune_page'):
        observations['latest_rune_page'] = named_rune_page(observations['latest_rune_page'], rune_catalog(db_path))
    references = [{'name': row['chunk']['title'], 'kind': row['chunk']['kind'],
                   'version': row['chunk']['version'], 'text': row['chunk']['text'][:1200]}
                  for row in evidence[:7]]
    from .prompt import SYSTEM
    payload = {'question': question, 'champion': champion, 'opponent': opponent or None,
               # 성향은 선택 칸 대신 사용자가 채팅으로 말한 내용에서 읽는다.
               'earlier_messages': [m for m in (user_requests or []) if m != question][-5:],
               'champion_select': view, 'personal_observations': observations,
               'current_patch_names': current_names(db_path, item_map_for(view.get('game_mode'))),
               'official_references': references}
    prompt = {'system': SYSTEM, 'user': json.dumps(payload, ensure_ascii=False)}
    try:
        reply = generate(prompt)
        return {'answer': reply['text'], 'message': None, 'generated': True}
    except GeminiError as error:
        return {'answer': None, 'message': error.message, 'generated': False}
