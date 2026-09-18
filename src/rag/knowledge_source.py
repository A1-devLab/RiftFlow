"""근거 자료를 knowledge 모듈에서 받아 온다.

docs/interfaces.md 의 knowledge.get_documents(패치, 챔피언 또는 아이템) 을 쓴다.
rag 는 자료를 모으지 않는다. 받은 문서를 청크로 자르고 순위를 매기는 일만 한다.

합의 전 가정 (knowledge 담당과 정해야 함)
- '챔피언 또는 아이템' 을 종류로 읽는다 (가정 B).
  get_documents(patch, 'item') 은 그 패치의 아이템 문서 전체를 돌려준다고 본다.
  그래야 이름이 없는 상황 질문에도 답할 수 있고, 질문에서 찾을 이름 목록도 얻을 수 있다.
- 종류는 item, champion 에 더해 rune, patch 도 받는다. rune 과 patch 는 초안에 없는 종류다.
- 돌려받는 문서 형식은 tests/fixtures/rag/documents_ddragon.json 의 문서 형식이라고 본다.

knowledge.get_documents 가 아직 없어서 fixture 를 읽는 대역(fixture_get_documents)을 함께 둔다.
"""
import json
from pathlib import Path

from .store import build_index

# item, champion 은 초안에 있는 종류, rune, patch 는 초안에 없어 합의가 필요한 종류다.
KINDS = ('item', 'champion', 'rune', 'patch')

DEFAULT_FIXTURE = Path(__file__).resolve().parents[2] / 'tests' / 'fixtures' / 'rag' / 'documents_ddragon.json'


class KnowledgeUnavailable(Exception):
    """knowledge.get_documents 를 쓸 수 없다."""


def knowledge_get_documents():
    """knowledge 모듈의 get_documents 를 찾는다. 아직 구현되지 않았으면 KnowledgeUnavailable."""
    try:
        from knowledge import get_documents
    except ImportError as error:
        raise KnowledgeUnavailable('knowledge.get_documents 가 아직 없습니다: %s' % error)
    return get_documents


class DocumentSource:
    """get_documents 로 받은 문서를 패치별로 한 번만 받아 청크로 만들어 둔다.

    가정 B 에서는 부를 때마다 종류 전체가 온다. 같은 패치 동안에는 다시 받을 이유가 없다.
    받다가 실패하면 저장하지 않으므로 다음 질문에서 다시 시도한다.
    """

    def __init__(self, get_documents, kinds=KINDS):
        self.get_documents = get_documents
        self.kinds = tuple(kinds)
        self._chunks = {}

    def chunks(self, patch):
        if patch not in self._chunks:
            documents = []
            for kind in self.kinds:
                documents.extend(self.get_documents(patch, kind) or [])
            self._chunks[patch] = build_index(documents)
        return self._chunks[patch]

    def name_chunks(self, patch):
        """안전장치가 '자료에 있는 이름' 을 찾을 때 쓸 문서.

        요청한 패치의 자료가 있으면 그것을 쓰고, 비어 있으면 최신 자료(patch=None)를 쓴다.
        이름 목록은 '롤 질문인가' 를 가를 때만 쓰고, 챔피언과 아이템 이름은 패치마다 거의 바뀌지 않는다.
        그러지 않으면 자료가 없는 패치의 롤 질문이 '근거 부족' 이 아니라 '롤 질문 아님' 으로 막힌다.

        합의 전 가정: get_documents(None, 종류) 는 최신 자료를 돌려준다.
        최신 자료도 받지 못하면 빈 목록을 돌려준다. 이름 없이도 롤 용어로는 판정할 수 있다.
        """
        found = self.chunks(patch)
        if found or patch is None:
            return found
        try:
            return self.chunks(None)
        except Exception:                           # noqa: BLE001
            return []


def fixture_get_documents(path=DEFAULT_FIXTURE):
    """knowledge.get_documents 대역. 합의된 형식이 아니라 rag 가 만든 초안 fixture 를 읽는다.

    패치를 주지 않으면(None) fixture 의 문서를 그대로 쓴다.
    fixture 와 다른 패치를 주면 그 패치의 자료가 없는 것으로 보고 빈 목록을 돌려준다.
    """
    with open(path, encoding='utf-8') as handle:
        payload = json.load(handle)

    def get_documents(patch, kind):
        if patch is not None and patch != payload.get('patch'):
            return []
        return [document for document in payload['documents'] if document['kind'] == kind]

    return get_documents
