"""Application services shared by the desktop UI and integration tests."""
import json
import sqlite3
from functools import partial
from importlib.resources import files
from pathlib import Path

from knowledge.collector import connect, save, update
from knowledge.documents import get_documents
from rag.knowledge_source import DocumentSource
from rag.pipeline import answer


def create_demo(path):
    documents = json.loads(files("ui").joinpath("demo_documents.json").read_text(encoding="utf-8"))
    db = connect(path)
    try:
        with db:
            for doc in documents:
                save(db, doc["kind"], doc["version"], doc["entity_id"], doc["title"],
                     json.dumps(doc, ensure_ascii=False), doc["source_url"])
    finally:
        db.close()


def sync_database(path):
    db = connect(path)
    try:
        return update(db, 3)
    finally:
        db.close()


def ask_database(path, question, version=None, *, generate=None, analysis=None,
                 prompt_builder=None):
    # Fresh source per question: same-version hotfix updates must invalidate retrieval.
    source = DocumentSource(partial(get_documents, db_path=path))
    chunks = source.chunks(version)
    options = {}
    if prompt_builder is not None:
        options["prompt_builder"] = prompt_builder
    result = answer(chunks, question, analysis=analysis, patch=version, generate=generate,
                    name_chunks=source.name_chunks(version), **options)
    result["generated"] = result["answer"] is not None
    return result
