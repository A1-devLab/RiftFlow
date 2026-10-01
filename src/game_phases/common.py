"""Shared terminal helpers for all game phases."""
import os
from functools import partial
from pathlib import Path

from rag.config import load_env
from rag import llm
from ui.services import ask_database


def gemini_generator():
    """터미널 흐름용 AI 호출 함수 (LLM_PROVIDER로 Gemini/HASA 선택). 키가 없으면 바로 알린다."""
    load_env(".env")
    if not llm.has_key():
        raise RuntimeError(".env에 %s를 설정하세요." % llm.key_env())
    return partial(llm.generate, model=llm.default_model(), retries=0)


def ask(question, *, analysis=None, prompt_builder=None, retrieval_question=None,
        db_path=Path("data/riftflow.db")):
    return ask_database(
        db_path,
        question,
        analysis=analysis,
        prompt_builder=prompt_builder,
        retrieval_question=retrieval_question,
        generate=gemini_generator(),
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
