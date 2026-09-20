"""Ask the real RiftFlow knowledge database from a terminal."""
import argparse
import os
from functools import partial
from pathlib import Path

from rag.config import load_env
from rag.gemini import DEFAULT_MODEL, generate
from ui.services import ask_database


def main():
    parser = argparse.ArgumentParser(description="RiftFlow 실제 DB에 질문합니다.")
    parser.add_argument("question", help="롤 관련 질문")
    parser.add_argument("--db", type=Path, default=Path("data/riftflow.db"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--model", default=None)
    parser.add_argument("--version", default=None, help="자료 버전. 예: 26.18")
    parser.add_argument("--local", action="store_true",
                        help="Gemini를 호출하지 않고 검색 근거만 확인")
    args = parser.parse_args()

    load_env(args.env)
    if not args.db.exists():
        parser.error("DB가 없습니다: %s" % args.db)

    call_model = None
    if not args.local:
        model = args.model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
        if not os.environ.get("GEMINI_API_KEY"):
            parser.error(".env에 GEMINI_API_KEY를 설정하세요.")
        call_model = partial(generate, model=model, retries=0)
        print("Gemini 모델: %s" % model)

    result = ask_database(args.db, args.question, args.version, generate=call_model)
    print("상태: %s" % result["status"])
    if result["error"]:
        print("오류: %s" % result["error"])
    if result["answer"]:
        print("\n답변\n%s" % result["answer"])
    elif result["message"]:
        print("\n안내\n%s" % result["message"])

    print("\n검색 근거: %d개" % len(result["evidence"]))
    for row in result["evidence"]:
        chunk = row["chunk"]
        print("- %s (버전 %s, %.2f점)" %
              (chunk["subject_name"], chunk["version"], row["score"]))
    print("\n출처")
    for source in result["sources"]:
        print("- %s" % source["source_url"])
    if result["usage"]:
        print("\n토큰 사용량: %s" % result["usage"].get("total_tokens"))
    return 2 if result["status"] == "model_error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
