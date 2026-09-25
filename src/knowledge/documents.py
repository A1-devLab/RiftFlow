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
                      "purchasable": gold.get("purchasable"), "stats": entity.get('stats', {})}
            if gold.get("total") is not None:
                lines.append("가격: %s골드" % gold["total"])
        elif kind == "champion":
            fields = {"ddragon_tags": entity.get("tags", []), "resource": entity.get("partype"),
                      "info": entity.get("info", {}), "stats": entity.get("stats", {})}
            if fields['stats']:
                lines.append('기본 능력치: ' + json.dumps(fields['stats'], ensure_ascii=False))
        elif kind == "rune":
            fields = {"key": entity.get('key'), "short_description": plain(entity.get('shortDesc'))}
    return {"doc_id": "%s:%s:%s" % (kind, version, row["entity_id"]),
            "kind": kind, "entity_id": row["entity_id"], "version": version,
            "subject_name": row["name"], "title": row["name"],
            "text": "\n".join(lines), "source_url": row["source_url"],
            "content_hash": row["content_hash"], "updated_at": row["updated_at"],
            "data_type": kind, "patch_version": version,
            "collected_at": row.get('collected_at'), "sample_match_count": row.get('sample_match_count'),
            "source": row.get('source', 'Riot Games'),
            "fields": fields, "situation_tags": []}


def get_documents(patch=None, kind=None, *, db_path="data/riftflow.db"):
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
            if entity.get("maps") and not entity["maps"].get("11", False):
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
