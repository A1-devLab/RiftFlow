"""Rune tree structure and rune page rules.

LLM이 고른 룬 페이지를 클라이언트가 받아들일 수 있는지 여기서 코드로 검사한다.
모델의 출력은 믿지 않고, 규칙에 맞는 페이지만 화면에 보여 준다.
"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .documents import get_documents, version_key

# 능력치 파편은 Data Dragon에 없어 직접 적는다. 줄마다 고를 수 있는 파편이며 같은 파편이 여러 줄에 나올 수 있다.
# 2024 시즌 변경(방어력·마법 저항력 파편 삭제, 체력·강인함 파편 추가)을 반영했다.
# 라이엇이 파편을 바꾸면 이 표만 고친다. 수치는 바뀌기 쉬워 이름만 적는다.
SHARD_ROWS = (
    ('공격', ((5008, '적응형 능력치'), (5005, '공격 속도'), (5007, '스킬 가속'))),
    ('유연', ((5008, '적응형 능력치'), (5010, '이동 속도'), (5001, '체력 증가'))),
    ('방어', ((5011, '체력'), (5013, '강인함 및 둔화 저항'), (5001, '체력 증가'))),
)
SLOTS = 4   # 0 = 핵심 룬, 1~3 = 일반 슬롯


def rune_trees(db_path):
    """{트리 ID: {id, key, name, version, slots: [[{id, name, description}], ...]}}.

    트리·슬롯 정보가 없는 예전 수집 자료거나 룬이 모자라면 None을 돌려준다.
    그 경우 공식 자료를 다시 업데이트하면 채워진다.
    """
    try:
        documents = get_documents(kind='rune', db_path=db_path)
    except (sqlite3.Error, OSError, ValueError):
        return None
    trees = {}
    for doc in documents:
        fields = doc.get('fields') or {}
        tree_id, slot = fields.get('tree_id'), fields.get('slot_index')
        if not isinstance(tree_id, int) or not isinstance(slot, int) or not 0 <= slot < SLOTS:
            return None
        try:
            rune_id = int(doc['entity_id'])
        except (TypeError, ValueError, KeyError):
            return None
        tree = trees.setdefault(tree_id, {'id': tree_id, 'key': fields.get('tree_key'),
                                          'name': fields.get('tree_name') or str(tree_id),
                                          'version': doc.get('version'), 'slots': [[] for _ in range(SLOTS)]})
        tree['slots'][slot].append({'id': rune_id, 'name': doc.get('subject_name') or doc.get('title'),
                                    'description': ' '.join((fields.get('short_description') or '').split())})
    if len(trees) < 2 or any(not runes for tree in trees.values() for runes in tree['slots']):
        return None
    for tree in trees.values():
        for runes in tree['slots']:
            runes.sort(key=lambda rune: rune['id'])
    return trees


def ensure_rune_trees(db_path, *, fetch=None):
    """룬 트리 구조가 없으면 DB에 있는 룬 버전의 runesReforged.json만 받아 채운다.

    트리 구조를 저장하기 전에 수집한 DB도 전체 업데이트 없이 바로 룬 추천을 쓸 수 있게 한다.
    전체 업데이트와 같은 형식으로 저장하므로 나중에 전체 업데이트를 해도 '동일'로 처리된다.
    받지 못하면(오프라인 등) None.
    """
    trees = rune_trees(db_path)
    if trees is not None:
        return trees
    from .collector import DDRAGON, connect, fetch as download, rune_rows, save
    fetch = fetch or download
    try:
        version = None
        if Path(db_path).exists():
            with closing(sqlite3.connect(db_path)) as db:
                versions = [row[0] for row in db.execute("SELECT DISTINCT version FROM records WHERE kind='rune'")]
            version = max(versions, key=version_key, default=None)
        if version is None:
            version = json.loads(fetch(f'{DDRAGON}/api/versions.json'))[0]
        url = f'{DDRAGON}/cdn/{version}/data/ko_KR/runesReforged.json'
        rows = rune_rows(json.loads(fetch(url)))
        with closing(connect(db_path)) as db, db:
            for rune_id, entity in rows:
                save(db, 'rune', version, rune_id, entity['name'],
                     json.dumps(entity, ensure_ascii=False, sort_keys=True), url)
    except (OSError, ValueError, KeyError, IndexError, TypeError, sqlite3.Error):
        return None
    return rune_trees(db_path)


def _slot_index(trees):
    return {rune['id']: (tree_id, slot) for tree_id, tree in trees.items()
            for slot, runes in enumerate(tree['slots']) for rune in runes}


def _names(trees):
    return {rune['id']: rune['name'] for tree in trees.values() for runes in tree['slots'] for rune in runes}


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _as_id(value, names):
    """정수 ID는 그대로, '8112' 같은 숫자 글자는 정수로, 공식 이름이면 그 ID로 바꾼다. 모르면 원래 값."""
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
        return names.get(text, value)
    return value


def resolve_names(page, trees):
    """모델이 ID 대신 공식 이름을 쓴 경우 ID로 바꾼다. 어떤 룬을 고를지는 바꾸지 않는다.

    Gemini에는 응답 스키마로 정수 ID를 강제했지만, 스키마를 쓰지 못하는 모델(gpt-oss 등)은 같은 룬을 이름으로 쓴다.
    이름은 이번 패치 룬 목록과 정확히 같을 때만 바꾸므로, 목록에 없는 룬은 그대로 남아 validate_page가 거절한다.
    """
    if not isinstance(page, dict):
        return page
    tree_names = {tree['name']: tree_id for tree_id, tree in trees.items()}
    rune_names = {rune['name']: rune['id'] for tree in trees.values() for runes in tree['slots'] for rune in runes}
    page = dict(page)
    for key in ('primary_style', 'secondary_style'):
        page[key] = _as_id(page.get(key), tree_names)
    page['keystone'] = _as_id(page.get('keystone'), rune_names)
    for key in ('primary', 'secondary'):
        if isinstance(page.get(key), list):
            page[key] = [_as_id(value, rune_names) for value in page[key]]
    if isinstance(page.get('shards'), list):
        page['shards'] = [_as_id(value, {name: shard_id for shard_id, name in SHARD_ROWS[index][1]})
                          if index < len(SHARD_ROWS) else value for index, value in enumerate(page['shards'])]
    return page


def validate_page(page, trees):
    """룬 페이지 규칙을 검사한다. (정리된 페이지 또는 None, 오류 목록)을 돌려준다.

    오류 문장은 모델에게 다시 고르게 할 때 그대로 전달하므로 무엇이 틀렸는지 구체적으로 적는다.
    """
    if not isinstance(page, dict):
        return None, ['응답이 JSON 객체가 아닙니다.']
    errors = []
    where = _slot_index(trees)

    def id_list(key, count):
        value = page.get(key)
        if not isinstance(value, list) or len(value) != count or not all(_is_int(v) for v in value):
            errors.append('%s는 정수 ID %d개여야 합니다.' % (key, count))
            return None
        return value

    primary_style, secondary_style, keystone = (page.get(k) for k in ('primary_style', 'secondary_style', 'keystone'))
    if primary_style not in trees:
        errors.append('primary_style %r는 룬 트리 ID가 아닙니다.' % (primary_style,))
    if secondary_style not in trees:
        errors.append('secondary_style %r는 룬 트리 ID가 아닙니다.' % (secondary_style,))
    elif secondary_style == primary_style:
        errors.append('secondary_style은 primary_style과 다른 트리여야 합니다.')
    if where.get(keystone) != (primary_style, 0):
        errors.append('keystone %r는 주 트리의 핵심 룬(0번 슬롯)이 아닙니다.' % (keystone,))

    primary = id_list('primary', 3)
    if primary is not None:
        slots, valid = [], True
        for rune in primary:
            tree, slot = where.get(rune, (None, None))
            if tree != primary_style or slot == 0:
                errors.append('primary의 %d는 주 트리의 1~3번 슬롯 룬이 아닙니다.' % rune)
                valid = False
            slots.append(slot)
        if valid and sorted(slots) != [1, 2, 3]:
            names = _names(trees)
            same = ', '.join('row%d에 %s' % (slot, '·'.join(names.get(r, str(r)) for r in primary if where[r][1] == slot))
                             for slot in sorted(set(slots)) if slots.count(slot) > 1)
            missing = ', '.join('row%d' % slot for slot in (1, 2, 3) if slot not in slots)
            errors.append('primary는 주 트리 row1, row2, row3에서 하나씩 골라야 합니다. 같은 줄에서 두 개 고름(%s), %s에서 고르지 않음.'
                          % (same, missing))

    secondary = id_list('secondary', 2)
    if secondary is not None:
        slots = []
        for rune in secondary:
            tree, slot = where.get(rune, (None, None))
            if tree != secondary_style or slot == 0:
                errors.append('secondary의 %d는 보조 트리의 1~3번 슬롯 룬이 아닙니다.' % rune)
            slots.append(slot)
        if len(slots) == 2 and slots[0] is not None and slots[0] == slots[1]:
            errors.append('secondary 두 개는 보조 트리의 서로 다른 줄(row)에서 골라야 합니다. 둘 다 row%d입니다.' % slots[0])

    shards = id_list('shards', 3)
    if shards is not None:
        for index, (shard, (row_name, options)) in enumerate(zip(shards, SHARD_ROWS)):
            if shard not in {shard_id for shard_id, _ in options}:
                errors.append('shards의 %d번째(%s 줄) %d는 그 줄의 파편이 아닙니다.' % (index + 1, row_name, shard))

    if errors:
        return None, errors
    order = lambda rune: where[rune][1]
    normalized = {'primary_style': primary_style, 'keystone': keystone, 'primary': sorted(primary, key=order),
                  'secondary_style': secondary_style, 'secondary': sorted(secondary, key=order),
                  'shards': list(shards)}
    # 클라이언트 룬 페이지의 selectedPerkIds 순서 (2단계 적용에서 사용)
    normalized['selected_perk_ids'] = ([keystone] + normalized['primary'] + normalized['secondary']
                                       + normalized['shards'])
    return normalized, []


def describe_page(page, trees):
    """검사를 통과한 페이지에 이름을 붙인다. 화면과 설명 문장이 이 이름을 쓴다."""
    names = {rune['id']: rune['name'] for tree in trees.values() for runes in tree['slots'] for rune in runes}
    rune = lambda rune_id: {'id': rune_id, 'name': names.get(rune_id, str(rune_id))}
    shard_names = [dict(options)[shard] for shard, (_row, options) in zip(page['shards'], SHARD_ROWS)]
    return {'primary_style': {'id': page['primary_style'], 'name': trees[page['primary_style']]['name']},
            'keystone': rune(page['keystone']),
            'primary': [rune(r) for r in page['primary']],
            'secondary_style': {'id': page['secondary_style'], 'name': trees[page['secondary_style']]['name']},
            'secondary': [rune(r) for r in page['secondary']],
            'shards': [{'id': shard, 'name': name, 'row': row}
                       for shard, name, (row, _options) in zip(page['shards'], shard_names, SHARD_ROWS)],
            'selected_perk_ids': page['selected_perk_ids']}


def name_recent_page(page, trees):
    """저장된 개인 룬 페이지([{style, perks}])를 트리·룬 이름으로 바꾼다. 모르는 ID는 이름을 지어내지 않는다."""
    names = {rune['id']: rune['name'] for tree in trees.values() for runes in tree['slots'] for rune in runes}
    styles = []
    for style in page or []:
        tree = trees.get(style.get('style'))
        styles.append({'tree': tree['name'] if tree else '확인 안 된 트리',
                       'runes': [names.get(perk, '확인 안 된 룬') for perk in style.get('perks', [])]})
    return styles
