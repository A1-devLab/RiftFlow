"""검색 단계 검증. 인터넷과 API 키가 필요 없다.

tests/fixtures/rag/questions.json 의 케이스를 돌려
필요한 근거 문서가 검색 결과에 들어오는지 본다.

답변 문장은 검사하지 않는다. 생성 결과는 매번 달라지기 때문이다.
주제 이탈과 범위 밖 차단은 검색이 아니라 안전장치가 할 일이라 여기서 제외한다.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from rag.retrieve import search, sources_of  # noqa: E402
from rag.store import build_index, load_documents  # noqa: E402

FIXTURES = ROOT / 'tests' / 'fixtures'
QUESTIONS = FIXTURES / 'rag' / 'questions.json'

# 안전장치가 담당하므로 검색 단계에서는 검사하지 않는다.
GUARD_CASES = {'off_topic_guard', 'out_of_scope_mode'}


def load_cases():
    with open(QUESTIONS, encoding='utf-8') as handle:
        return json.load(handle)['cases']


class RetrievalTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases()
        cls.index = {}

    def index_for(self, relative):
        if relative not in self.index:
            documents = load_documents(FIXTURES / relative)
            self.index[relative] = build_index(documents)
        return self.index[relative]

    def run_case(self, case):
        return search(self.index_for(case['fixture_documents']),
                      case['input']['question'],
                      case['input'].get('analysis'),
                      top_k=5)

    def test_required_documents_are_retrieved(self):
        for case in self.cases:
            if case['case_id'] in GUARD_CASES or case['expect'].get('insufficient_evidence'):
                continue
            with self.subTest(case=case['case_id']):
                found = [row['chunk']['doc_id'] for row in self.run_case(case)]
                for doc_id in case['expect']['must_cite_doc_ids']:
                    self.assertIn(doc_id, found)
                # 정답이 들어오는지만 보면 엉뚱한 문서가 섞여도 통과한다. 섞이면 안 되는 문서도 검사한다.
                for doc_id in case['expect'].get('must_not_cite_doc_ids', []):
                    self.assertNotIn(doc_id, found)

    def test_no_evidence_returns_nothing(self):
        for case in self.cases:
            if case['case_id'] in GUARD_CASES:
                continue
            if not case['expect'].get('insufficient_evidence'):
                continue
            with self.subTest(case=case['case_id']):
                self.assertEqual(self.run_case(case), [])

    def test_every_result_carries_a_source(self):
        """근거에는 출처가 따라붙어야 한다. 제품의 존재 이유다."""
        for case in self.cases:
            if case['case_id'] in GUARD_CASES:
                continue
            with self.subTest(case=case['case_id']):
                for source in sources_of(self.run_case(case)):
                    self.assertTrue(source['source_url'].startswith('https://'))
                    self.assertTrue(source['doc_id'])
                    self.assertTrue(source['version'])

    def test_chunks_fit_in_a_prompt(self):
        """패치 노트 한 문서는 수천 자다. 청킹이 되어야 프롬프트에 넣을 수 있다."""
        chunks = self.index_for('rag/documents_ddragon.json')
        longest = max(len(chunk['text']) for chunk in chunks)
        self.assertLess(longest, 600)

    def test_patch_note_is_split(self):
        chunks = self.index_for('rag/documents_ddragon.json')
        patch_chunks = [chunk for chunk in chunks if chunk['kind'] == 'patch']
        self.assertGreater(len(patch_chunks), 1)

    def test_only_canonical_item_ids(self):
        """4자리 ID 아이템만 담는다. 6자리 ID 는 다른 모드용 사본으로 보고 뺀다.

        322065 는 2065(슈렐리아의 군가) 앞에 32 를 붙인 것이고 이름도 같다.
        6자리 중에도 maps["11"] 이 참인 것이 있어 맵 검사만으로는 걸러지지 않는다.
        실제 경기 기록에서 협곡 아이템이 4자리로 오는지는 아직 확인하지 않았다.
        """
        chunks = self.index_for('rag/documents_ddragon.json')
        items = [chunk for chunk in chunks if chunk['kind'] == 'item']
        self.assertTrue(items)
        for chunk in items:
            with self.subTest(item=chunk['entity_id']):
                self.assertLessEqual(len(chunk['entity_id']), 4)

    def test_no_duplicate_item_names(self):
        chunks = self.index_for('rag/documents_ddragon.json')
        names = [chunk['subject_name'] for chunk in chunks if chunk['kind'] == 'item']
        self.assertEqual(len(names), len(set(names)))

    def test_missing_champion_info_is_null_not_mixed(self):
        """info 가 전부 0 인 챔피언은 값이 비어 있는 것이다. 0 과 구분한다.

        아크샨, 렐, 세라핀, 벡스는 난이도까지 0 이다. 0 대 0 을 '혼합' 으로 적으면 틀린 근거가 된다.
        """
        chunks = self.index_for('rag/documents_ddragon.json')
        champions = {chunk['entity_id']: chunk for chunk in chunks if chunk['kind'] == 'champion'}
        for entity_id in ['Akshan', 'Rell', 'Seraphine', 'Vex']:
            with self.subTest(champion=entity_id):
                chunk = champions[entity_id]
                self.assertIsNone(chunk['fields']['damage_type'])
                for tag in ('AD챔피언', 'AP챔피언', '혼합딜챔피언'):
                    self.assertNotIn(tag, chunk['situation_tags'])
        self.assertEqual(champions['Garen']['fields']['damage_type'], 'AD')
        self.assertEqual(champions['Ahri']['fields']['damage_type'], 'AP')


class NameMatchTest(unittest.TestCase):
    """비슷한 이름끼리 섞이지 않는지 본다. 이름이 반만 겹치는 아이템이 근거에 섞였던 문제."""

    INFINITY = 'ddragon:item:3031:16.18.1'
    EXECUTIONER = 'ddragon:item:3123:16.18.1'
    BF_SWORD = 'ddragon:item:1038:16.18.1'
    SCIMITAR = 'ddragon:item:3139:16.18.1'

    @classmethod
    def setUpClass(cls):
        cls.chunks = build_index(load_documents(FIXTURES / 'rag' / 'documents_ddragon.json'))

    def found(self, question):
        return [row['chunk']['doc_id'] for row in search(self.chunks, question, top_k=5)]

    def test_better_matching_name_pushes_out_half_matches(self):
        found = self.found('무한의 대검 언제 사?')
        self.assertEqual(found[0], self.INFINITY)
        self.assertNotIn(self.EXECUTIONER, found)
        self.assertNotIn(self.BF_SWORD, found)

    def test_two_named_items_are_both_kept(self):
        found = self.found('무한의 대검이랑 처형인의 대검 비교해줘')
        self.assertEqual(set(found[:2]), {self.INFINITY, self.EXECUTIONER})

    def test_ambiguous_name_keeps_every_candidate(self):
        """'대검' 만 물으면 어느 대검인지 모르므로 후보를 모두 남긴다."""
        found = self.found('대검 종류 알려줘')
        for doc_id in (self.INFINITY, self.EXECUTIONER, self.BF_SWORD):
            self.assertIn(doc_id, found)

    def test_shortened_name_is_still_found(self):
        self.assertEqual(self.found('시미터 어때?')[0], self.SCIMITAR)

    def test_repeated_word_is_counted_once(self):
        from rag.retrieve import terms_of
        self.assertEqual(terms_of('무한의 대검이랑 처형인의 대검 비교해줘').count('대검'), 1)


if __name__ == '__main__':
    unittest.main()
