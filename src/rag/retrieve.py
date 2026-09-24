"""질문에 맞는 근거 청크를 찾는다.

형태소 분석기를 쓰지 않는다. 의존성을 늘리지 않기 위해서다.
대신 조사를 떼어내는 정도로만 질의어를 다듬고, 상황어 사전으로 situation_tags 에 연결한다.

흔한 단어는 역빈도로 가치를 낮춘다. 그래야 '상대' 같은 단어가 아무 문서나 끌어오지 않는다.

한계를 분명히 해 둔다.
- 상황어 사전과 situation_tags 는 RiftFlow 가 직접 적은 것이고 검증된 게임 지식이 아니다.
- 동의어가 사전에 없으면 걸리지 않는다. 사전을 늘려야 한다.
- 롤과 무관한 질문이라도 '회복', '대검' 처럼 우리 문서에 있는 단어를 쓰면 결과가 나온다.
  이것은 검색으로 풀 수 없고 주제 판정(안전장치)이 해야 한다.
"""
import math

# 조사만 떼어낸다. 짧은 접미사부터 지우면 '에서' 가 '에' 로 잘리므로 긴 것부터 본다.
PARTICLES = ('으로는', '에서는', '에게는', '으로', '에서', '에게', '이랑', '까지', '부터',
             '보다', '한테', '이나', '라도', '는데', '은', '는', '이', '가', '을', '를',
             '에', '의', '도', '만', '와', '과', '로')

# 질문에 나오는 표현을 situation_tags 값으로 잇는다.
# tests/fixtures/rag/tools/build_ddragon_fixtures.py 의 SITUATION_OVERLAY 와 짝을 이룬다.
SITUATION_KEYWORDS = {
    '상대CC많음': ['단일 대상 궁극기', '단일대상', '궁극기가 많', 'cc', '씨씨', '군중 제어',
                '군중제어', '잡히면', '묶이', '기절', '에어본'],
    '단일대상궁': ['단일 대상 궁극기', '단일대상', '지목', '논타겟이 아닌'],
    # '상대가 AD' 와 'AD 챔피언' 은 다른 요구다.
    # 앞은 방어 아이템을 찾는 말이고 뒤는 그 챔피언 자체를 찾는 말이다.
    # 구분하지 않으면 'AD 챔피언 추천' 에 판금 장화가 1위로 나온다. 실제로 그랬다.
    '상대AP위주': ['상대 ap', '상대가 ap', '상대에 ap', '마법 피해', '마법피해',
               '마법사가 많', 'ap가 많', 'ap 많'],
    '상대AD위주': ['상대 ad', '상대가 ad', '상대에 ad', '물리 피해', '물리피해',
               '평타', 'ad가 많', 'ad 많'],
    'AD챔피언': ['ad 챔피언', 'ad챔피언', 'ad챔', '공격력 챔피언', '물리 딜러', '물리딜러'],
    'AP챔피언': ['ap 챔피언', 'ap챔피언', 'ap챔', '주문력 챔피언', '마법 딜러', '마법딜러'],
    '브루저': ['브루저', '탱커형 딜러', '싸움꾼'],
    '탱커': ['탱커', '몸빵', '앞라인'],
    '원거리딜러': ['원딜', '원거리 딜러', '마크스맨'],
    '마법사': ['메이지', '마법사'],
    '암살': ['암살자', '암살'],
    '상대회복많음': ['회복', '흡혈', '힐', '치유', '피를 계속', '체력을 계속'],
    '치명타빌드': ['치명타', '크리', '크리티컬'],
    '지속교전': ['계속 붙어', '오래 싸', '지속적으로 싸', '장기전', '붙어서 싸'],
    '순간폭딜': ['한 번에', '순간 딜', '버스트', '치고 빠', '암살'],
    '생존': ['죽지 않', '살아남', '생존', '녹아'],
}

# 픽창에서 받은 성향 답변을 상황 태그로 옮긴다.
PLAYSTYLE_TAGS = {
    'trade_preference': {'지속': '지속교전', '순간': '순간폭딜'},
    'lane_aggression': {'높음': '라인전'},
}

# 챔피언의 Data Dragon 분류를 상황 태그로 옮긴다.
CHAMPION_TAGS = {
    'Fighter': '브루저', 'Tank': '탱커', 'Marksman': '원거리딜러',
    'Mage': '마법사', 'Support': '서포터', 'Assassin': '암살',
}

# 질문이 무엇을 묻는지. 해당 종류를 위로 올린다.
KIND_KEYWORDS = {
    'rune': ['룬', '특성', '키스톤', '핵심 룬'],
    'item': ['아이템', '템', '빌드', '올릴', '사요', '구매', '가격', '얼마', '조합',
             '코어', '살까', '사야', '가야', '갈까'],
    'patch': ['패치', '이번 패치', '바뀐', '변경', '너프', '버프', '상향', '하향'],
    'champion': ['스킬', '패시브', '궁', '챔피언'],
}
# 종류를 나타내는 말의 낱말. 본문에 있어도 내용이 맞았다는 근거가 아니다 (score_chunk).
INTENT_WORDS = {word for words in KIND_KEYWORDS.values() for phrase in words for word in phrase.split()}

# 점수 가중치. 이름이 걸리는 쪽을 가장 크게 본다.
WEIGHT_NAME = 5
WEIGHT_TAG = 4
WEIGHT_PLAYSTYLE = 4
WEIGHT_CHAMPION_TAG = 3
WEIGHT_TERM = 2
WEIGHT_CHAMPION = 3
WEIGHT_KIND = 2
WEIGHT_PATCH_INTENT = 5
MIN_SCORE = 2

# 질문에 가장 잘 맞는 이름의 이 비율 이상 맞아야 이름 점수를 준다.
# '무한의 대검 언제 사?' 에서 무한의 대검은 100% 맞는데 처형인의 대검, B.F. 대검도
# '대검' 하나로 50% 가 되어 근거에 섞였다. 더 잘 맞는 이름이 있으면 반쯤 맞는 이름은 뺀다.
# 두 이름을 함께 물으면(66%, 71%) 둘 다 남고, '대검 종류' 처럼 모두 비슷하면(50%) 모두 남는다.
NAME_RELATIVE_FLOOR = 0.8


def strip_particle(word):
    for particle in PARTICLES:
        if len(word) > len(particle) + 1 and word.endswith(particle):
            return word[:-len(particle)]
    return word


# 질문을 이어 주는 말. 검색어로 쓰면 이름에 엉뚱하게 걸린다.
# 자료가 챔피언 173명으로 늘자 '이번' 이 챔피언 '아이번' 에 걸렸다.
STOPWORDS = {'이번', '요즘', '지금', '어떤', '어떻게', '언제', '뭐가', '무엇', '무슨', '이거',
             '저거', '그거', '추천해줘', '추천해', '알려줘', '알려', '해줘', '주세요', '좋아',
             '좋은', '좋나요', '하나요', '할까요', '인가요', '뭔가요', '바뀌었어', '바뀌었나요'}


def terms_of(question):
    """질문을 검색어 목록으로 만든다. 한 글자짜리와 이어 주는 말은 버린다.

    같은 낱말은 한 번만 넣는다. '무한의 대검이랑 처형인의 대검' 처럼 같은 말이 두 번 나오면
    본문에 그 말이 있는 문서가 두 번 점수를 받아, 샤코가 두 아이템보다 위로 올라왔다.
    """
    words = []
    for raw in question.replace('?', ' ').replace(',', ' ').split():
        word = strip_particle(raw.strip('.!~')).lower()
        if len(word) >= 2 and word not in STOPWORDS and word not in words:
            words.append(word)
    return words


def tags_of(question):
    """질문에서 상황 태그를 뽑는다."""
    lowered = question.lower()
    return [tag for tag, keywords in SITUATION_KEYWORDS.items()
            if any(keyword in lowered for keyword in keywords)]


def document_frequency(chunks, terms):
    """각 검색어가 몇 개 청크에 나오는지 센다."""
    counts = dict.fromkeys(terms, 0)
    for chunk in chunks:
        body = chunk['text'].lower()
        for term in terms:
            if term in body:
                counts[term] += 1
    return counts


def inverse_frequency(counts, total):
    """흔한 단어의 가치를 낮춘다.

    '상대' 나 '피해' 처럼 거의 모든 문서에 나오는 단어는 0 에 가까워진다.
    이 단어들 때문에 '포킹 조합 상대로' 같은 질문이 패치 노트를 끌어왔다.

    값을 0~1 로 맞춘다. 그러지 않으면 단어 하나가 이름 일치보다 큰 점수를 받는다.
    아이템 설명에는 아이템 이름이 들어 있지 않아서, 이름 일치가 밀리면 정답이 내려간다.
    """
    ceiling = math.log(total + 1) or 1.0
    return {term: math.log((total + 1) / (count + 1)) / ceiling
            for term, count in counts.items()}


def tag_frequency(chunks, tags):
    """각 상황 태그가 몇 개 청크에 붙어 있는지 센다."""
    counts = dict.fromkeys(tags, 0)
    for chunk in chunks:
        for tag in tags:
            if tag in chunk['situation_tags']:
                counts[tag] += 1
    return counts


def analysis_tags(analysis, champion_tags):
    """픽창 성향 답변과 챔피언 분류를 상황 태그로 바꾼다."""
    playstyle, from_champion = [], []
    for field, mapping in PLAYSTYLE_TAGS.items():
        value = ((analysis or {}).get('playstyle') or {}).get(field)
        if value in mapping:
            playstyle.append(mapping[value])
    for tag in champion_tags or []:
        if tag in CHAMPION_TAGS:
            from_champion.append(CHAMPION_TAGS[tag])
    return playstyle, from_champion


def kind_intent(question):
    """질문이 룬을 묻는지 아이템을 묻는지 본다."""
    lowered = question.lower()
    return {kind for kind, words in KIND_KEYWORDS.items()
            if any(word in lowered for word in words)}


def name_coverage(name, terms):
    """이름이 질문과 얼마나 겹치는지 0~1 로 잰다.

    이름을 부분 문자열로만 맞추면 '무한의 대검' 질문에 '처형인의 대검' 이 같은 점수를 받는다.
    둘 다 '대검' 을 가지고 있기 때문이다.

    두 가지를 보고 큰 쪽을 쓴다.
      이름 쪽 비율: 이름 글자 중 몇 글자가 질문에 나왔나. 긴 이름의 일부만 맞으면 낮다.
      질문 쪽 비율: 질문 낱말 중 몇 개가 이름에 들어갔나. 짧게 줄여 부르는 경우를 살린다.

    '시미터' 처럼 이름을 줄여 부르면 이름 쪽 비율은 낮지만 질문 쪽 비율이 높다.
    """
    if not name or not terms:
        return 0.0

    matched_chars = 0
    matched_terms = 0
    for term in set(terms):
        if term in name:
            matched_chars += len(term)
            matched_terms += 1
        elif name in term:
            matched_chars += len(name)
            matched_terms += 1

    if not matched_terms:
        return 0.0
    by_name = min(matched_chars / len(name), 1.0)
    by_question = matched_terms / len(set(terms))
    return max(by_name, by_question)


def score_chunk(chunk, terms, tags, champion, weights, playstyle, champion_tags, kinds,
                tag_weights, coverage=None):
    """청크 하나의 점수. coverage 를 주면 이름 겹침 비율로 그 값을 쓴다 (search 가 기준 미달이면 0 을 넘긴다)."""
    score = 0.0
    reasons = []

    name = chunk['subject_name'].lower()
    if coverage is None:
        coverage = name_coverage(name, terms)
    if coverage:
        score += WEIGHT_NAME * coverage
        reasons.append('이름:%s(%d%%)' % (chunk['subject_name'], coverage * 100))

    matched = [tag for tag in tags if tag in chunk['situation_tags']]
    if matched:
        # 태그도 흔할수록 가치를 낮춘다. 챔피언 173명이 모두 가진 태그는 변별력이 없다.
        score += WEIGHT_TAG * sum(tag_weights.get(tag, 1.0) for tag in matched)
        reasons.append('상황:' + ','.join(matched))

    from_playstyle = [tag for tag in playstyle
                      if tag in chunk['situation_tags'] and tag not in matched]
    if from_playstyle:
        score += WEIGHT_PLAYSTYLE * len(from_playstyle)
        reasons.append('성향:' + ','.join(from_playstyle))

    from_champion = [tag for tag in champion_tags if tag in chunk['situation_tags']]
    if from_champion:
        score += WEIGHT_CHAMPION_TAG * len(from_champion)
        reasons.append('챔피언분류:' + ','.join(from_champion))

    body = chunk['text'].lower()
    hits = [term for term in terms if term in body]
    if hits:
        score += WEIGHT_TERM * sum(weights.get(term, 0) for term in hits)
        rare = sorted(hits, key=lambda t: -weights.get(t, 0))[:3]
        reasons.append('본문:' + ','.join(rare))

    picked_champion = bool(champion and champion.lower() in (chunk['entity_id'].lower(), name))
    if picked_champion:
        score += WEIGHT_CHAMPION
        reasons.append('챔피언:' + champion)

    # 다른 근거가 하나도 없으면 종류만으로 올리지 않는다.
    # 그러지 않으면 '뭐 사요?' 같은 말 한마디에 모든 아이템이 통과한다.
    # '챔피언', '변경' 처럼 무엇을 묻는지 나타내는 말(KIND_KEYWORDS)이 본문에 있는 것은 근거로 치지 않는다.
    # '미드 챔피언 추천해줘' 에 스몰더('녹서스 변경 부근' 의 국경이라는 뜻의 변경)와
    # 뽀삐('용맹한 챔피언이 넘쳐나지만')가 이 한 단어로 종류 점수까지 받아 근거로 들어왔다.
    content_hits = [term for term in hits if term not in INTENT_WORDS]
    evidence = coverage or matched or from_playstyle or from_champion or content_hits or picked_champion
    if evidence and chunk['kind'] in kinds:
        # 무엇이 바뀌었는지 묻는 질문에는 패치 노트만 답할 수 있다.
        # 챔피언과 아이템 문서는 지금 상태만 담고 있어 변경 전후를 모른다.
        score += WEIGHT_PATCH_INTENT if chunk['kind'] == 'patch' else WEIGHT_KIND
        reasons.append('종류:' + chunk['kind'])

    return score, reasons


def search(chunks, question, analysis=None, top_k=5, min_score=MIN_SCORE, max_per_doc=2):
    """점수가 높은 청크를 top_k 개까지 돌려준다.

    결과가 비면 근거가 없다는 뜻이다. 호출한 쪽에서 근거 부족으로 처리해야 한다.

    max_per_doc 은 한 문서가 상위권을 독차지하는 것을 막는다.
    챔피언 문서는 스킬 수만큼 청크가 나오므로 제한이 없으면 top_k 를 전부 가져간다.
    """
    terms = terms_of(question)
    tags = tags_of(question)
    champion = (analysis or {}).get('champion')
    weights = inverse_frequency(document_frequency(chunks, terms), len(chunks))
    tag_weights = inverse_frequency(tag_frequency(chunks, tags), len(chunks))
    kinds = kind_intent(question)

    champion_ddragon_tags = []
    if champion:
        for chunk in chunks:
            if chunk['kind'] == 'champion' and chunk['entity_id'].lower() == champion.lower():
                champion_ddragon_tags = chunk['fields'].get('ddragon_tags') or []
                break
    playstyle, from_champion = analysis_tags(analysis, champion_ddragon_tags)

    # 이름 겹침 비율은 이름마다 한 번만 계산하고, 가장 잘 맞는 이름을 기준으로 거른다.
    coverage_by_name = {}
    for chunk in chunks:
        name = chunk['subject_name'].lower()
        if name not in coverage_by_name:
            coverage_by_name[name] = name_coverage(name, terms)
    best = max(coverage_by_name.values(), default=0.0)
    floor = best * NAME_RELATIVE_FLOOR

    scored = []
    for chunk in chunks:
        coverage = coverage_by_name[chunk['subject_name'].lower()]
        score, reasons = score_chunk(chunk, terms, tags, champion, weights,
                                     playstyle, from_champion, kinds, tag_weights,
                                     coverage=coverage if coverage >= floor else 0.0)
        # out_game의 패치·메타·챔피언 질문에는 최신 패치 노트를 최소 근거로 포함한다.
        # 아이템·룬만 묻는 질문에 이 점수를 주면 이름이 정확히 맞는 정적 자료보다
        # 관계없는 패치 노트가 먼저 나오므로 강제 점수를 적용하지 않는다.
        question_types = set((analysis or {}).get('question_types') or [])
        needs_patch = not question_types or bool(question_types & {'patch', 'meta', 'champion'})
        if ((analysis or {}).get('phase') == 'out_game' and chunk['kind'] == 'patch'
                and needs_patch):
            score = max(score, WEIGHT_PATCH_INTENT)
            if '공간:out_game' not in reasons:
                reasons.append('공간:out_game')
        if score >= min_score:
            scored.append({'score': round(score, 3), 'reasons': reasons, 'chunk': chunk})

    scored.sort(key=lambda row: (-row['score'], row['chunk']['chunk_id']))

    picked, per_doc = [], {}
    for row in scored:
        doc_id = row['chunk']['doc_id']
        if per_doc.get(doc_id, 0) >= max_per_doc:
            continue
        per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
        picked.append(row)
        if len(picked) >= top_k:
            break
    return picked


def sources_of(results):
    """답변에 붙일 출처 목록. 문서 단위로 중복을 없앤다."""
    sources, seen = [], set()
    for row in results:
        chunk = row['chunk']
        if chunk['doc_id'] in seen:
            continue
        seen.add(chunk['doc_id'])
        sources.append({
            'doc_id': chunk['doc_id'],
            'title': chunk['title'],
            'source_url': chunk['source_url'],
            'version': chunk['version'],
        })
    return sources
