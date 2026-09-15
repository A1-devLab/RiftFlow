"""Translate the collector's SQLite records into RAG documents.

Versions are exact source versions. No patch/Data Dragon conversion is guessed.
Each call opens its own connection, suitable for background GUI workers.
"""
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
    # Packaged examples use the same normalized format as the team's RAG fixture.
    if isinstance(content, dict) and content.get("doc_id") and "text" in content:
        return dict(content)
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
                      "purchasable": gold.get("purchasable")}
            if gold.get("total") is not None:
                lines.append("가격: %s골드" % gold["total"])
        elif kind == "champion":
            fields = {"ddragon_tags": entity.get("tags", []), "resource": entity.get("partype")}
    return {"doc_id": "%s:%s:%s" % (kind, version, row["entity_id"]),
            "kind": kind, "entity_id": row["entity_id"], "version": version,
            "subject_name": row["name"], "title": row["name"],
            "text": "\n".join(lines), "source_url": row["source_url"],
            "content_hash": row["content_hash"], "updated_at": row["updated_at"],
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
            # Exclude explicitly non-Summoner's Rift items. No ID-length heuristic.
            if entity.get("maps") and not entity["maps"].get("11", False):
                continue
        result.append(as_document(row))
    return result
