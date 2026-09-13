"""실행: python -m rag ask "질문"

기본은 Gemini 를 부르지 않는다. 프롬프트까지만 만들고 멈춘다.
실제로 부르려면 --call 을 준다. GEMINI_API_KEY 가 필요하다.
"""
import argparse
import sys
from pathlib import Path

from . import conversation as conv
from .config import load_env
from .pipeline import answer
from .store import build_index, load_documents

DEFAULT_FIXTURE = Path('tests/fixtures/knowledge/documents_ddragon.json')

LABELS = {
    'off_topic': '차단 (롤 질문 아님)',
    'out_of_scope': '범위 밖 (협곡 아님)',
    'insufficient_evidence': '근거 부족',
    'model_error': '모델 호출 실패',
    'ready': '근거 확보',
}


def main():
    parser = argparse.ArgumentParser(description='RiftFlow RAG: 안전장치와 검색 확인 도구')
    parser.add_argument('command', choices=['ask', 'stats'])
    parser.add_argument('question', nargs='?', default='')
    parser.add_argument('--documents', type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument('--champion', default=None, help='픽창에서 감지한 챔피언')
    parser.add_argument('--trade', default=None, choices=['지속', '순간'],
                        help='딜교환 성향')
    parser.add_argument('--top', type=int, default=5)
    parser.add_argument('--patch', default=None, help='패치 번호. 예 26.18')
    parser.add_argument('--call', action='store_true',
                        help='실제로 Gemini 를 부른다. GEMINI_API_KEY 필요')
    parser.add_argument('--save', type=Path, default=None,
                        help='대화를 남길 DB 경로. 예 data/conversations.db')
    parser.add_argument('--show-prompt', action='store_true')
    parser.add_argument('--env', type=Path, default=Path('.env'),
                        help='API 키가 든 .env 경로')
    parser.add_argument('--model', default=None,
                        help='쓸 모델 이름. 기본값은 gemini.py 의 DEFAULT_MODEL')
    args = parser.parse_args()

    if not args.documents.exists():
        print('문서 파일이 없습니다: %s' % args.documents, file=sys.stderr)
        return 1

    chunks = build_index(load_documents(args.documents))

    if args.command == 'stats':
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
    if args.save:
        store = {'db': conv.connect(args.save),
                 'conversation_id': conv.new_conversation_id()}

    outcome = answer(chunks, args.question, analysis or None, patch=args.patch,
                     top_k=args.top, generate=generate, store=store)

    print('판정: %s' % LABELS[outcome['status']])
    print('이유: %s' % outcome['reason'])
    if outcome['error']:
        print('오류: %s' % outcome['error'])

    if outcome['answer']:
        print('\n답변\n%s' % outcome['answer'])
        if outcome['usage']:
            print('\n토큰: %s' % outcome['usage'])
    elif outcome['message']:
        print('\n사용자에게: %s' % outcome['message'])
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
