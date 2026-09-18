"""Shared terminal helpers for all game phases."""
import os
from functools import partial
from pathlib import Path

from rag.config import load_env
from rag.gemini import generate
from ui.services import ask_database


def ask(question, *, analysis=None, prompt_builder=None, retrieval_question=None,
        db_path=Path("data/riftflow.db")):
    load_env(".env")
    model = os.environ.get("GEMINI_MODEL")
    if not os.environ.get("GEMINI_API_KEY") or not model:
        raise RuntimeError(".env에 GEMINI_API_KEY와 GEMINI_MODEL을 설정하세요.")
    return ask_database(
        db_path,
        question,
        analysis=analysis,
        prompt_builder=prompt_builder,
        retrieval_question=retrieval_question,
        generate=partial(generate, model=model, retries=0),
    )


def show(result):
    if result["answer"]:
        print("\n답변\n%s" % result["answer"])
    else:
        print("\n안내\n%s" % (result["error"] or result["message"] or "답변이 없습니다."))
    print("\n근거")
    for source in result["sources"]:
        print("- %s (%s)" % (source["title"], source["source_url"]))
    if result["usage"]:
        print("\nGemini 토큰 사용량: %s" % result["usage"].get("total_tokens"))
