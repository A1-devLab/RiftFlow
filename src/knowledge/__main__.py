"""실행: python -m knowledge update"""
import argparse
import sys
from pathlib import Path
from .collector import DB_PATH, connect, update

def main():
    parser = argparse.ArgumentParser(description='RiftFlow: 라이엇 데이터 저장·업데이트 맛보기')
    parser.add_argument('--db', type=Path, default=DB_PATH, help='DB 경로 (기본: data/riftflow.db)')
    sub = parser.add_subparsers(dest='command', required=True)
    up = sub.add_parser('update', help='최신 게임 데이터와 최근 패치 저장')
    up.add_argument('--patches', type=int, choices=range(1, 13), default=3, metavar='1~12')
    sub.add_parser('status', help='저장된 데이터 수 확인')
    search = sub.add_parser('search', help='이름 또는 패치 본문 검색')
    search.add_argument('keyword')
    search.add_argument('--kind', choices=['champion', 'item', 'rune', 'patch'])
    args = parser.parse_args()
    db = connect(args.db)
    try:
        if args.command == 'update':
            update(db, args.patches)
            print(f'DB: {args.db.resolve()}')
        elif args.command == 'status':
            rows = db.execute('SELECT kind, version, COUNT(*) FROM records GROUP BY kind, version').fetchall()
            for kind, version, count in rows:
                print(f'{kind:10} | {version:10} | {count}개')
            if not rows:
                print('저장된 정보가 없습니다. update를 실행하세요.')
        else:
            rows = db.execute('''SELECT kind, version, name, content, source_url FROM records
                WHERE (instr(name, ?) > 0 OR instr(content, ?) > 0)
                AND (? IS NULL OR kind=?) ORDER BY updated_at DESC LIMIT 10''',
                (args.keyword, args.keyword, args.kind, args.kind)).fetchall()
            for kind, version, name, content, url in rows:
                start = max(0, content.find(args.keyword) - 80)
                print(f'\n[{kind} / {version}] {name}\n{content[start:start + 600]}\n출처: {url}')
            if not rows:
                print('검색 결과가 없습니다.')
    except Exception as error:
        print(f'실패: {error}\n기존 데이터는 유지됩니다. 인터넷 연결을 확인한 뒤 다시 실행하세요.', file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
