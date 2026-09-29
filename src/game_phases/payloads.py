"""앱이 서버로 보내는 AI 요청 데이터를 정리한다. 앱(보내기 전)과 서버(받은 뒤)가 같은 규칙을 쓴다.

- 소환사 이름·계정 ID처럼 AI에 필요 없는 개인 정보는 뺀다.
- 목록 개수와 글자 수를 제한해 서버가 엉뚱하게 큰 요청을 처리하지 않게 한다.
"""

PICK_ENTRY_KEYS = ('champion', 'id', 'position', 'locked', 'selected', 'hovering')
LIVE_ENTRY_KEYS = ('champion', 'team', 'position', 'position_name', 'level', 'kills', 'deaths', 'assists', 'kda',
                   'cs', 'cs_per_min', 'estimated_gold', 'is_dead', 'respawn_timer', 'is_me')
MESSAGE_LIMIT = 1000


def text(value, limit=60):
    return None if value is None else str(value)[:limit]


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _entries(items, keys, limit=5, extra=None):
    result = []
    for item in (items or [])[:limit] if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        entry = {}
        for key in keys:
            value = item.get(key)
            entry[key] = value if isinstance(value, (bool, int, float)) or value is None else text(value)
        if extra:
            entry.update(extra(item))
        result.append(entry)
    return result


def pick_view(view):
    """픽창 요약. 소환사 이름과 PUUID는 원래 들어 있지 않고, 챔피언·포지션·확정 여부만 남긴다."""
    view = view if isinstance(view, dict) else {}
    mine = _entries([view.get('mine')], PICK_ENTRY_KEYS, 1)
    return {'game_mode': text(view.get('game_mode'), 20), 'mode_name': text(view.get('mode_name'), 30),
            'mine': mine[0] if mine else None,
            'allies': _entries(view.get('allies'), PICK_ENTRY_KEYS),
            'enemies': _entries(view.get('enemies'), PICK_ENTRY_KEYS),
            'ally_bans': [text(b) for b in (view.get('ally_bans') or [])[:10]],
            'enemy_bans': [text(b) for b in (view.get('enemy_bans') or [])[:10]]}


def _items(entry):
    items = []
    for item in (entry.get('items') or [])[:7]:
        if isinstance(item, dict) and isinstance(item.get('id'), int):
            items.append({'id': item['id'], 'slot': _number(item.get('slot')), 'name': text(item.get('name'))})
    return {'items': items}


def live_view(view):
    """인게임 스코어보드 요약. 10명의 소환사 이름은 뺀다."""
    view = view if isinstance(view, dict) else {}
    if not view.get('in_game'):
        return {'in_game': False}
    me = _entries([view.get('me')], LIVE_ENTRY_KEYS, 1, _items)
    gold = view.get('team_gold') if isinstance(view.get('team_gold'), dict) else None
    return {'in_game': True, 'clock': text(view.get('clock'), 8), 'elapsed_seconds': _number(view.get('elapsed_seconds')),
            'game_mode': text(view.get('game_mode'), 20), 'map_number': _number(view.get('map_number')),
            'mode_name': text(view.get('mode_name'), 30),
            'perspective_known': bool(view.get('perspective_known')), 'my_team': text(view.get('my_team'), 8),
            'me': me[0] if me else None,
            'allies': _entries(view.get('allies'), LIVE_ENTRY_KEYS, 5, _items),
            'enemies': _entries(view.get('enemies'), LIVE_ENTRY_KEYS, 5, _items),
            'team_gold': ({key: _number(gold.get(key)) for key in ('ally', 'enemy', 'diff')} | {'note': text(gold.get('note'), 200)}
                          if gold else None)}


def user_requests(messages):
    return [text(m, MESSAGE_LIMIT) for m in (messages or [])[-5:] if isinstance(m, str) and m.strip()]


def _page(page):
    styles = []
    for style in (page or [])[:2] if isinstance(page, list) else []:
        if isinstance(style, dict) and isinstance(style.get('style'), int):
            styles.append({'style': style['style'],
                           'perks': [p for p in (style.get('perks') or [])[:6] if isinstance(p, int)]})
    return styles


def recent_pages(pages):
    """이 챔피언으로 최근 쓴 룬 페이지와 승패 (최대 5개)."""
    return [{'won': bool(p.get('won')), 'opponent': text(p.get('opponent')), 'page': _page(p.get('page'))}
            for p in (pages or [])[:5] if isinstance(p, dict)]


def observations(record):
    """개인 상성 기록 요약 (knowledge.before_game.personal_context 결과)."""
    if not isinstance(record, dict):
        return None
    result = {key: _number(record.get(key)) or 0
              for key in ('champion_games', 'champion_wins', 'matchup_games', 'matchup_wins')}
    result['latest_rune_page'] = _page(record.get('latest_rune_page')) or None
    result['scope'] = text(record.get('scope'), 200)
    return result


def general_context(context):
    """AI에게 질문 화면의 전적 요약 (ui.services.profile_context 결과)."""
    if not isinstance(context, dict):
        return None
    rank = context.get('rank') if isinstance(context.get('rank'), dict) else None
    matches = []
    for match in (context.get('recent_matches') or [])[:20]:
        if isinstance(match, dict):
            matches.append({key: (match.get(key) if isinstance(match.get(key), (bool, int, float)) else text(match.get(key)))
                            for key in ('played_at_epoch', 'game_duration_seconds', 'game_mode', 'champion_name',
                                        'win', 'kills', 'deaths', 'assists', 'cs')})
    return {'rank': ({key: (rank.get(key) if isinstance(rank.get(key), int) else text(rank.get(key), 20))
                      for key in ('tier', 'division', 'league_points', 'wins', 'losses')} if rank else None),
            'recent_matches': matches}
