"""Official Data Dragon lookups the in-game screen needs (item names, champion roles).

인게임 화면은 몇 초마다 갱신되므로 DB를 매번 다시 읽지 않도록 파일 변경 시각 기준으로
캐싱한다. 여기서는 공식 자료에 실제로 있는 값(아이템 이름·가격, 챔피언 태그·역할 지표)만
꺼내고, 상성이나 승률처럼 DB에 없는 값은 만들지 않는다.
"""
from pathlib import Path

from .documents import get_documents

_cache = {}


def _cached(kind, db_path, builder):
    """같은 DB 파일이 그대로면 이전 결과를 재사용한다 (폴링 중 반복 조회 방지)."""
    path = Path(db_path)
    try:
        stamp = path.stat().st_mtime_ns, path.stat().st_size
    except OSError:
        stamp = None
    key = (kind, str(path.resolve() if path.exists() else path))
    hit = _cache.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    value = builder(db_path)
    _cache[key] = (stamp, value)
    return value


def _build_item_catalog(db_path):
    catalog = {}
    for doc in get_documents(kind='item', db_path=db_path):
        try:
            item_id = int(doc['entity_id'])
        except (TypeError, ValueError, KeyError):
            continue
        fields = doc.get('fields') or {}
        catalog[item_id] = {'name': doc.get('subject_name') or doc.get('title') or str(item_id),
                            'gold_total': fields.get('gold_total'),
                            'version': doc.get('version'),
                            'text': doc.get('text', '')}
    return catalog


def item_catalog(db_path):
    """{아이템 ID: {name, gold_total, version, text}}. 수집한 자료가 없으면 빈 dict."""
    return _cached('item', db_path, _build_item_catalog)


def item_names(items, catalog):
    """Live Client가 준 아이템 목록을 공식 이름으로 바꾼다. 모르는 ID는 이름을 지어내지 않는다."""
    names = []
    for item in items or []:
        item_id = item.get('itemID') if isinstance(item, dict) else item
        try:
            item_id = int(item_id)
        except (TypeError, ValueError):
            continue
        known = catalog.get(item_id)
        names.append(known['name'] if known else '확인 안 된 아이템 %d' % item_id)
    return names


def _damage_rating(fields):
    """Data Dragon의 attack/magic 지표(0~10)로 대략의 피해 유형을 추정한다.

    실제 딜 비율이 아니라 라이엇이 챔피언 소개용으로 매긴 지표다. 값이 없거나
    차이가 작으면 단정하지 않는다.
    """
    if fields.get('damage_type'):
        return fields['damage_type']
    info = fields.get('info') or {}
    attack, magic = info.get('attack'), info.get('magic')
    if not isinstance(attack, (int, float)) or not isinstance(magic, (int, float)):
        return None
    if abs(attack - magic) < 2:
        return '혼합'
    return 'AD' if attack > magic else 'AP'


def _build_champion_profiles(db_path):
    profiles = {}
    for doc in get_documents(kind='champion', db_path=db_path):
        fields = doc.get('fields') or {}
        profile = {'id': doc.get('entity_id'), 'name': doc.get('subject_name') or doc.get('title'),
                   'tags': fields.get('ddragon_tags') or [],
                   'resource': fields.get('resource'),
                   'damage_rating': _damage_rating(fields),
                   'version': doc.get('version')}
        for key in (profile['id'], profile['name']):
            if key:
                profiles[str(key).casefold()] = profile
    return profiles


def champion_profiles(db_path):
    """{챔피언 ID 또는 한국어 이름(소문자): {id, name, tags, resource, damage_rating}}."""
    return _cached('champion', db_path, _build_champion_profiles)


def team_composition(champions, profiles):
    """상대·아군 조합을 공식 태그와 Data Dragon 지표로만 정리한다.

    승률이나 상성은 DB에 없으므로 포함하지 않는다. 확인 안 된 챔피언은
    unknown 목록에 남겨, 프롬프트가 아는 척하지 않게 한다.
    """
    known, unknown, tags, ratings = [], [], {}, {}
    for champion in champions:
        profile = profiles.get(str(champion or '').casefold())
        if profile is None:
            if champion:
                unknown.append(champion)
            continue
        known.append({'champion': profile['name'], 'tags': profile['tags'],
                      'damage_rating': profile['damage_rating']})
        for tag in profile['tags']:
            tags[tag] = tags.get(tag, 0) + 1
        if profile['damage_rating']:
            ratings[profile['damage_rating']] = ratings.get(profile['damage_rating'], 0) + 1
    return {'champions': known, 'unverified_champions': unknown,
            'tag_counts': tags, 'damage_rating_counts': ratings,
            'note': 'Data Dragon 역할 태그와 소개 지표만 집계. 실제 딜 비율·승률 통계가 아님.'}
