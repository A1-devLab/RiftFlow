"""근거 문서를 읽어 검색 단위인 청크로 자른다.

문서는 knowledge.get_documents 로 받는다 (knowledge_source.py). 여기서는 받은 문서를 자르기만 한다.
load_documents 는 fixture 파일을 통째로 읽는 도구로, 테스트에서만 쓴다.
문서의 필드 이름(kind, entity_id, version, content_hash, updated_at)은 records 테이블과 같게 맞춰 두었다.

패치 노트는 문서 하나가 수천 자라 통째로 프롬프트에 넣을 수 없다.
그래서 문서를 청크로 자르고, 검색과 인용은 청크 단위로 한다.
"""
import json

# 청크 최대 길이. 한국어 기준 대략 400자면 프롬프트에 여러 개를 넣을 수 있다.
MAX_CHARS = 400
# 앞 청크의 마지막 몇 줄을 다음 청크에 겹쳐 넣는다.
# 패치 노트는 "카시오페아" 다음 줄부터 수치가 나오므로 겹치지 않으면 이름과 수치가 분리된다.
OVERLAP_LINES = 2


def load_documents(path):
    """fixture 파일에서 문서 목록을 읽는다."""
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)['documents']


def split_lines(text):
    return [line.strip() for line in text.split('\n') if line.strip()]


def pack(lines, max_chars, overlap_lines):
    """줄 단위로 모아 max_chars 를 넘지 않는 덩어리를 만든다.

    줄 중간에서 자르지 않는다. 수치가 ': 34 + 레벨당 5 ⇒' 처럼 줄로 나뉘어 있어서
    중간에서 자르면 변경 전후가 갈라진다.
    """
    blocks, current, size = [], [], 0
    for line in lines:
        if current and size + len(line) > max_chars:
            blocks.append(current)
            current = current[-overlap_lines:] if overlap_lines else []
            size = sum(len(item) for item in current)
        current.append(line)
        size += len(line)
    if current:
        blocks.append(current)
    return blocks


def chunk_document(document, max_chars=MAX_CHARS, overlap_lines=OVERLAP_LINES):
    """문서 하나를 청크 목록으로 만든다. 종류마다 자르는 방식이 다르다."""
    lines = split_lines(document['text'])

    if document['kind'] == 'champion':
        # 패시브와 Q~R 이 한 줄씩이다. 스킬 하나가 청크 하나가 되는 편이 근거로 쓰기 좋다.
        blocks = [[line] for line in lines]
    elif document['kind'] == 'patch':
        blocks = pack(lines, max_chars, overlap_lines)
    else:
        # 아이템과 룬은 짧아서 대개 한 덩어리로 끝난다.
        blocks = pack(lines, max_chars, 0)

    chunks = []
    for index, block in enumerate(blocks):
        chunks.append({
            'chunk_id': '%s#%d' % (document['doc_id'], index),
            'doc_id': document['doc_id'],
            'kind': document['kind'],
            'entity_id': document['entity_id'],
            'version': document['version'],
            'subject_name': document['subject_name'],
            'title': document['title'],
            'source_url': document['source_url'],
            'situation_tags': document.get('situation_tags') or [],
            'fields': document.get('fields') or {},
            'text': '\n'.join(block),
        })
    return chunks


def build_index(documents, max_chars=MAX_CHARS, overlap_lines=OVERLAP_LINES):
    """문서 목록 전체를 청크 목록으로 편다."""
    chunks = []
    for document in documents:
        chunks.extend(chunk_document(document, max_chars, overlap_lines))
    return chunks
