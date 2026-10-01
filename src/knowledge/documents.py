import json
import re
import sqlite3
from contextlib import closing
from html import unescape
from pathlib import Path

KINDS = ("item", "champion", "rune", "patch")


def plain(value):
    return unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).strip()


def version_key(value):
    return tuple(int(n) for n in re.findall(r"\d+", value))


# 게임 모드 → Data Dragon 아이템의 maps 번호. U.R.F.는 협곡 아이템을 쓴다.
MODE_MAPS = {"CLASSIC": "11", "URF": "11", "ARURF": "11", "ARAM": "12", "CHERRY": "30"}


def item_map_for(game_mode=None, map_number=None):
    """게임 중이면 클라이언트가 알려 준 맵 번호를, 픽창이면 모드로 맵을 정한다. 모르면 협곡."""
    if map_number and str(map_number) in ("11", "12", "30"):
        return str(map_number)
    return MODE_MAPS.get(str(game_mode or "").upper(), "11")


def store_item(entity_id, entity, map_id="11"):
    """해당 맵 상점에서 실제로 살 수 있는 아이템인지.

    Data Dragon item.json에는 모드별 상점 아이템이 한데 들어 있고 maps 번호로 구분한다
    (16.19.1 기준 870개: 협곡 11, 칼바람 12, 아레나 30). 상점에 없는 아이템(inStore: false)과
    특정 챔피언·오른 전용 아이템은 어느 맵에서도 뺀다.
    협곡은 maps 표시가 붙은 특수 모드 복사본(예: 663056)이 섞여 있어 4자리 ID만 쓴다.
    """
    if not str(entity_id).isdigit():
        return False
    if map_id == "11" and int(entity_id) >= 10000:
        return False
    maps = entity.get("maps")
    if maps and not maps.get(map_id, False):
        return False
    gold = entity.get("gold") or {}
    if gold and not gold.get("purchasable", True):
        return False
    if entity.get("inStore") is False or entity.get("requiredChampion") or entity.get("requiredAlly"):
        return False
    return True


_cache = {}


def cached(kind, db_path, builder):
    """DB 파일(변경 시각·크기)이 그대로면 이전 결과를 재사용한다. 폴링·질문마다 같은 DB를 다시 읽지 않게 한다.

    자료를 업데이트하면 파일이 바뀌므로 자동으로 새로 만든다. (before_game·in_game에 같은 함수가 두 벌 있던 것을 합침)
    """
    path = Path(db_path)
    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        stamp = None
    key = (kind, str(path.resolve() if path.exists() else path))
    hit = _cache.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    value = builder(db_path)
    _cache[key] = (stamp, value)
    return value


def has_records(db_path):
    """수집한 자료가 하나라도 있는지. 시작할 때 전체 문서를 읽지 않고 한 줄만 확인한다."""
    try:
        with closing(sqlite3.connect(str(db_path))) as db:
            return db.execute("SELECT 1 FROM records LIMIT 1").fetchone() is not None
    except sqlite3.Error:
        return False


def latest_versions(db, kinds=None):
    """{종류: 최신 버전}. 버전은 숫자 기준으로 비교한다 (글자로 비교하면 '16.9.1'이 '16.19.1'보다 크다)."""
    latest = {}
    for kind, version in db.execute("SELECT DISTINCT kind, version FROM records"):
        if (kinds is None or kind in kinds) and (kind not in latest or version_key(version) > version_key(latest[kind])):
            latest[kind] = version
    return latest


def read_rows(db_path, kind=None, patch=None):
    """필요한 종류의 행만 읽는다. patch가 없으면 종류마다 최신 버전, 있으면 그 버전만.

    예전에는 테이블 전체(수집한 모든 버전)를 읽고 파이썬에서 걸러, 자료를 업데이트할수록 질문마다 느려졌다.
    patch를 Data Dragon 버전으로 추측해 바꾸지 않는다 (게임 패치 26.19 ≠ 자료 버전 16.19.1, 의도된 규칙).
    """
    path = Path(db_path).resolve()
    if not path.exists():
        return []
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        versions = latest_versions(db, None if kind is None else {kind})
        if patch is not None:
            versions = {row_kind: patch for row_kind in versions}
        rows = []
        for row_kind, version in sorted(versions.items()):
            rows += [dict(row) for row in db.execute(
                "SELECT * FROM records WHERE kind=? AND version=? ORDER BY name", (row_kind, version))]
        return rows


CHAMPION_SITUATION = {'Fighter': '브루저', 'Tank': '탱커', 'Marksman': '원거리딜러', 'Mage': '마법사',
                      'Assassin': '암살'}


def situation_tags(kind, fields, text):
    """검색이 쓰는 상황 태그를 공식 자료의 능력치·분류·설명에서만 만든다 (지어낸 게임 지식 아님).

    예전에는 항상 빈 목록이라 '상대가 AP 위주인데 뭐 사요?'에 정글 펫 아이템이 나왔다 ('상대'라는 단어만 맞아서).
    """
    tags = []
    if kind == 'item':
        stats = fields.get('stats') or {}
        if 'FlatSpellBlockMod' in stats:
            tags.append('상대AP위주')
        if 'FlatArmorMod' in stats:
            tags.append('상대AD위주')
        if '고통스러운 상처' in text or '치유 감소' in text or '회복 감소' in text:
            tags.append('상대회복많음')
        if 'FlatCritChanceMod' in stats:
            tags.append('치명타빌드')
    elif kind == 'champion':
        tags = [CHAMPION_SITUATION[tag] for tag in fields.get('ddragon_tags') or [] if tag in CHAMPION_SITUATION]
    return tags


def as_document(row):
    kind, version = row["kind"], row["version"]
    try:
        content = json.loads(row["content"])
    except (ValueError, TypeError):
        content = None
    if isinstance(content, dict) and content.get("doc_id") and "text" in content:
        return dict(content, data_type=kind, patch_version=version,
                    collected_at=row.get('collected_at'),
                    sample_match_count=row.get('sample_match_count'),
                    source=row.get('source', 'Riot Games'))
    entity = content if isinstance(content, dict) else {}
    fields = {}
    lines = [row["name"]]
    if kind == "patch":
        lines.append(row["content"])
    else:
        for key in ("description", "longDesc", "shortDesc", "blurb"):
            if entity.get(key):
                lines.append(plain(entity[key]))
        if kind == "item":
            gold = entity.get("gold") or {}
            fields = {"gold_total": gold.get("total"), "gold_base": gold.get("base"),
                      "builds_from": entity.get("from", []), "builds_into": entity.get("into", []),
                      "purchasable": gold.get("purchasable"), "stats": entity.get('stats', {}),
                      "ddragon_tags": entity.get("tags", [])}
            if gold.get("total") is not None:
                lines.append("가격: %s골드" % gold["total"])
        elif kind == "champion":
            fields = {"ddragon_tags": entity.get("tags", []), "resource": entity.get("partype"),
                      "info": entity.get("info", {}), "stats": entity.get("stats", {})}
            # 예전에는 기본 능력치 JSON(약 450자)을 그대로 넣었다. 모델이 읽기 어렵고 토큰만 썼다.
            info = fields['info'] or {}
            facts = []
            if fields['ddragon_tags']:
                facts.append('역할: ' + ', '.join(fields['ddragon_tags']))
            if fields['resource']:
                facts.append('자원: ' + fields['resource'])
            if info:
                facts.append('소개 지표(0~10): 공격 %s, 방어 %s, 마법 %s, 난이도 %s' % tuple(
                    info.get(k, '?') for k in ('attack', 'defense', 'magic', 'difficulty')))
            if facts:
                lines.append(' · '.join(facts))
        elif kind == "rune":
            fields = {"key": entity.get('key'), "short_description": plain(entity.get('shortDesc')),
                      "tree_id": entity.get('tree_id'), "tree_key": entity.get('tree_key'),
                      "tree_name": entity.get('tree_name'), "slot_index": entity.get('slot_index')}
    return {"doc_id": "%s:%s:%s" % (kind, version, row["entity_id"]),
            "kind": kind, "entity_id": row["entity_id"], "version": version,
            "subject_name": row["name"], "title": row["name"],
            "text": "\n".join(lines), "source_url": row["source_url"],
            "content_hash": row["content_hash"], "updated_at": row["updated_at"],
            "data_type": kind, "patch_version": version,
            "collected_at": row.get('collected_at'), "sample_match_count": row.get('sample_match_count'),
            "source": row.get('source', 'Riot Games'),
            "fields": fields, "situation_tags": situation_tags(kind, fields, "\n".join(lines))}


def get_documents(patch=None, kind=None, *, db_path="data/riftflow.db", item_map="11"):
    """item_map: 아이템을 어느 맵 상점 기준으로 거를지 (11 협곡, 12 칼바람, 30 아레나)."""
    if kind is not None and kind not in KINDS:
        raise ValueError("지원하지 않는 자료 종류입니다.")
    selected = read_rows(db_path, kind, patch)
    result = []
    for row in selected:
        if row["kind"] == "item":
            entity = json.loads(row["content"])
            # 미리 만든 문서 형식(예시 자료)은 원본 속성이 없어 그대로 둔다.
            if not ("doc_id" in entity and "text" in entity) and not store_item(row["entity_id"], entity, item_map):
                continue
        result.append(as_document(row))
    if kind in (None, 'patch'):
        from .out_game import get_patch_changes
        patch_rows = [row['version'] for row in selected if row['kind'] == 'patch']
        structured_patch = patch or max(patch_rows, key=version_key, default=None)
        for change in (get_patch_changes(structured_patch, db_path=db_path) if structured_patch else []):
            label = {'buff': '버프 상향', 'nerf': '너프 하향', 'adjusted': '복합 변경',
                     'unknown': '방향 미확인', 'unchanged': '수치 동일'}[change['change_type']]
            text = '\n'.join([change['entity_name'], label, change['summary']] +
                             [c['ability'] + ' ' + c['raw_text'] for c in change['changes']])
            result.append({'doc_id': f"patch-change:{change['patch_version']}:{change['source_url']}:{change['entity_id']}",
                'kind': 'patch', 'entity_id': change['entity_id'], 'version': change['patch_version'],
                'title': change['entity_name'] + ' 패치 변경', 'subject_name': change['entity_name'],
                'text': text, 'source_url': change['source_url'], 'fields': change,
                'situation_tags': [], 'data_type': 'patch_change',
                'patch_version': change['patch_version'], 'collected_at': change['collected_at'],
                'sample_match_count': change['sample_match_count'], 'source': change['source']})
    return result
