"""실행: python -m rag ask "질문"

기본은 Gemini 를 부르지 않는다. 프롬프트까지만 만들고 멈춘다.
실제로 부르려면 --call 을 준다. GEMINI_API_KEY 가 필요하다.

대화는 기본으로 data/conversations.db 에 남긴다. 챗봇 규약이 '데이터는 전부 저장' 이기 때문이다.
남기지 않으려면 --no-save 를 준다. 저장된 통계는 python -m rag history 로 본다.
"""
import argparse
import sys
from pathlib import Path

from . import conversation as conv
from .config import load_env
from .knowledge_source import DEFAULT_FIXTURE, DocumentSource, fixture_get_documents
from .pipeline import answer

LABELS = {
    'off_topic': '차단 (롤 질문 아님)',
    'out_of_scope': '범위 밖 (협곡 아님)',
    'insufficient_evidence': '근거 부족',
    'model_error': '모델 호출 실패',
    'ready': '근거 확보',
}


USAGE_LABELS = [('prompt_tokens', '입력'), ('output_tokens', '출력'),
                ('thinking_tokens', '생각'), ('total_tokens', '합계')]


def tokens_text(value):
    """모르는 값을 0 으로 보여 주지 않는다. 저장값과 같게 null 로 적는다."""
    return 'null' if value is None else '%d' % value


def format_usage(usage):
    return ' / '.join('%s %s' % (label, tokens_text(usage.get(key)))
                      for key, label in USAGE_LABELS)


def show_history(path):
    """저장된 대화의 상태별 건수와 토큰 사용량을 보여 준다."""
    if not path.exists():
        print('저장된 대화가 없습니다: %s' % path)
        return 0
    db = conv.connect(path)
    try:
        rows = conv.stats(db)
    finally:
        db.close()
    print('대화 기록: %s' % path)
    for row in rows:
        line = '  %-20s %3d건  토큰 %s' % (LABELS.get(row['status'], row['status']),
                                          row['count'], tokens_text(row['tokens']))
        if row['tokens'] is not None and row['tokens_unknown']:
            line += ' (사용량이 null 인 %d건 제외)' % row['tokens_unknown']
        print(line)
    return 0


def main():
    parser = argparse.ArgumentParser(description='RiftFlow RAG: 안전장치와 검색 확인 도구')
    parser.add_argument('command', choices=['ask', 'stats', 'history'])
    parser.add_argument('question', nargs='?', default='')
    parser.add_argument('--documents', type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument('--champion', default=None, help='픽창에서 감지한 챔피언')
    parser.add_argument('--trade', default=None, choices=['지속', '순간'],
                        help='딜교환 성향')
    parser.add_argument('--top', type=int, default=5)
    parser.add_argument('--patch', default=None, help='패치 번호. 예 26.18')
    parser.add_argument('--call', action='store_true',
                        help='실제로 Gemini 를 부른다. GEMINI_API_KEY 필요')
    parser.add_argument('--save', type=Path, default=conv.DB_PATH,
                        help='대화를 남길 DB 경로. 기본값 data/conversations.db')
    parser.add_argument('--no-save', action='store_true',
                        help='이번 질문은 대화 기록에 남기지 않는다')
    parser.add_argument('--show-prompt', action='store_true')
    parser.add_argument('--env', type=Path, default=Path('.env'),
                        help='API 키가 든 .env 경로')
    parser.add_argument('--model', default=None,
                        help='쓸 모델 이름. 기본값은 gemini.py 의 DEFAULT_MODEL')
    args = parser.parse_args()

    if args.command == 'history':
        return show_history(args.save)

    if not args.documents.exists():
        print('문서 파일이 없습니다: %s' % args.documents, file=sys.stderr)
        return 1

    # 실제 입구와 같은 길로 문서를 받는다. knowledge.get_documents 대신 fixture 대역을 쓴다.
    source = DocumentSource(fixture_get_documents(args.documents))
    chunks = source.chunks(args.patch)
    if not chunks:
        print('패치 %s 의 근거 자료가 없습니다: %s' % (args.patch, args.documents))

    if args.command == 'stats':
        if not chunks:
            return 0
        counts = {}
        for chunk in chunks:
            counts[chunk['kind']] = counts.get(chunk['kind'], 0) + 1
        print('청크 %d개' % len(chunks))
        for kind, count in sorted(counts.items()):
            print('  %-9s %d' % (kind, count))
        longest = max(chunks, key=lambda c: len(c['text']))
        print('가장 긴 청크: %d자 (%s)' % (len(longest['text']), longest['chunk_id']))
        return 0

    if not args.question:
        print('질문을 입력하세요.', file=sys.stderr)
        return 1

    analysis = {}
    if args.champion:
        analysis['champion'] = args.champion
    if args.trade:
        analysis['playstyle'] = {'trade_preference': args.trade}

    generate = None
    if args.call:
        loaded = load_env(args.env)
        if loaded:
            print('%s 에서 읽음: %s' % (args.env, ', '.join(loaded)))
        from .gemini import DEFAULT_MODEL, generate as call_gemini
        model = args.model or DEFAULT_MODEL
        print('모델: %s' % model)

        def generate(prompt):
            return call_gemini(prompt, model=model)

    store = None
    if not args.no_save:
        store = {'db': conv.connect(args.save),
                 'conversation_id': conv.new_conversation_id()}

    outcome = answer(chunks, args.question, analysis or None, patch=args.patch,
                     top_k=args.top, generate=generate, store=store,
                     name_chunks=source.name_chunks(args.patch))

    if store is not None:
        store['db'].close()
        print('대화 기록에 남김: %s' % args.save)

    print('판정: %s' % LABELS[outcome['status']])
    print('이유: %s' % outcome['reason'])
    if outcome['error']:
        print('오류: %s' % outcome['error'])

    if outcome['answer']:
        print('\n답변\n%s' % outcome['answer'])
        if outcome['usage']:
            print('\n토큰: %s' % format_usage(outcome['usage']))
    elif outcome['message']:
        print('\n사용자에게: %s' % outcome['message'])
        # 모델 호출이 실패한 경우는 부르려고 시도한 것이다. '호출 안 함' 이라고 적으면 틀린 안내다.
        if outcome['status'] != 'model_error':
            print('Gemini 호출 안 함 (토큰 안 씀)')
        return 0
    elif outcome['prompt']:
        print('\n프롬프트 준비됨: %d자 / 추정 %d토큰 (--call 로 실제 호출)'
              % (outcome['prompt']['chars'], outcome['prompt']['estimated_tokens']))

    if args.show_prompt and outcome['prompt']:
        print('\n----- system -----\n%s' % outcome['prompt']['system'])
        print('\n----- user -----\n%s' % outcome['prompt']['user'])

    for row in outcome['evidence']:
        chunk = row['chunk']
        print('\n[%.2f점] %s  (%s)' % (row['score'], chunk['subject_name'], chunk['chunk_id']))
        print('  맞은 이유: %s' % ' | '.join(row['reasons']))
        print('  %s' % chunk['text'].replace('\n', ' ')[:200])

    print('\n출처')
    for source in outcome['sources']:
        print('  - %s (%s) %s' % (source['title'], source['version'], source['source_url']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
