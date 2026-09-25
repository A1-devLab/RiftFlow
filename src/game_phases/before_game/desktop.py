"""Champion-select view model and evidence-grounded pre-game coaching."""
import json
import sqlite3
from pathlib import Path

from knowledge.before_game import champion_catalog, personal_context, rune_catalog, named_rune_page, canonical_champion
from knowledge.documents import get_documents
from rag.gemini import GeminiError
from rag.knowledge_source import DocumentSource
from rag.retrieve import search

from riot import get_champ_select_session


def get_before_game_context():
    return get_champ_select_session()


def describe_session(session, catalog):
    def entry(member):
        champion = catalog.get(member.champion_id, {})
        return {'champion': champion.get('name') or ('선택 전' if not member.champion_id else f'확인 안 된 ID {member.champion_id}'),
                'id': champion.get('id'), 'position': member.assigned_position or '미정',
                'locked': bool(member.champion_id)}
    mine = next((m for m in session.my_team if m.cell_id == session.local_player_cell_id), None)
    return {'mine': entry(mine) if mine else None,
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
                       champion=None, opponent=None, trade_preference=None, lane_aggression=None):
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
    observations = personal_context(personal_db_path, puuid, canonical_champion(db_path, champion),
                                    canonical_champion(db_path, opponent),
                                    (view.get('mine') or {}).get('position')) if puuid else None
    if observations and observations.get('latest_rune_page'):
        observations['latest_rune_page'] = named_rune_page(observations['latest_rune_page'], rune_catalog(db_path))
    references = [{'name': row['chunk']['title'], 'kind': row['chunk']['kind'],
                   'version': row['chunk']['version'], 'text': row['chunk']['text'][:1200]}
                  for row in evidence[:7]]
    from .prompt import SYSTEM
    payload = {'question': question, 'champion': champion, 'opponent': opponent or None,
               'playstyle': {'trade_preference': trade_preference, 'lane_aggression': lane_aggression},
               'champion_select': view, 'personal_observations': observations,
               'official_references': references}
    prompt = {'system': SYSTEM, 'user': json.dumps(payload, ensure_ascii=False)}
    try:
        reply = generate(prompt)
        return {'answer': reply['text'], 'message': None, 'generated': True}
    except GeminiError as error:
        return {'answer': None, 'message': error.message, 'generated': False}
