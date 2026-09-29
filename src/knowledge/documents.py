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


def sr_store_item(entity_id, entity):
    """소환사의 협곡 상점에서 실제로 살 수 있는 아이템인지 (store_item의 협곡판).

    Data Dragon item.json에는 협곡 상점 아이템 말고도 아레나·특수 모드 복사본(6자리 ID, 예: 223089),
    상점에 없는 아이템(inStore: false), 특정 챔피언·오른 전용 아이템이 함께 들어 있다(16.19.1 기준 870개).
    협곡 맵 표시만 보면 모드 복사본(예: 663056)이 섞여, AI가 이번 패치 협곡에서 살 수 없는 아이템을 추천했다.
    """
    return store_item(entity_id, entity, "11")


def read_rows(db_path):
    path = Path(db_path).resolve()
    if not path.exists():
        return []
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM records ORDER BY kind, name")]


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
            if fields['stats']:
                lines.append('기본 능력치: ' + json.dumps(fields['stats'], ensure_ascii=False))
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
            "fields": fields, "situation_tags": []}


def get_documents(patch=None, kind=None, *, db_path="data/riftflow.db", item_map="11"):
    """item_map: 아이템을 어느 맵 상점 기준으로 거를지 (11 협곡, 12 칼바람, 30 아레나)."""
    if kind is not None and kind not in KINDS:
        raise ValueError("지원하지 않는 자료 종류입니다.")
    rows = read_rows(db_path)
    selected = [row for row in rows if kind is None or row["kind"] == kind]
    if patch is not None:
        selected = [row for row in selected if row["version"] == patch]
    else:
        latest = {}
        for row in selected:
            key = row["kind"]
            if key not in latest or version_key(row["version"]) > version_key(latest[key]):
                latest[key] = row["version"]
        selected = [row for row in selected if row["version"] == latest[row["kind"]]]
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
