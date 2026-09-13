"""Gemini 를 부르기 전에 질문을 거른다.

챗봇 규약: 사용자가 다른 질문을 던져 토큰을 낭비시킬 수 있으므로 안전장치를 둔다.
검색과 생성으로 넘기기 전에 판정해야 토큰을 아낄 수 있다.

세 가지를 구분한다. 셋을 뭉뚱그리면 사용자에게 틀린 안내를 하게 된다.

  off_topic     롤 질문이 아니다. 날씨, 음식, 다른 분야.
  out_of_scope  롤 질문이지만 RiftFlow 범위 밖이다. 칼바람나락, 아레나, 전략적 팀 전투.
  allow         소환사의 협곡 질문이다. 검색으로 넘긴다.

'근거 부족'은 여기서 판정하지 않는다. 검색해 보고 결과가 없을 때 나오는 별개의 상태다.
"""

# 롤이지만 소환사의 협곡이 아닌 모드. 협곡 자료로 답하면 틀린 값을 준다.
# 같은 이름의 아이템이 모드별로 골드와 능력치가 다르기 때문이다.
OTHER_MODES = {
    '칼바람나락': ['칼바람', '아람', 'aram', '무작위 총력전', '하울링 애비스'],
    '아레나': ['아레나', 'arena', '2대2'],
    '전략적 팀 전투': ['전략적 팀 전투', 'tft', '롤체', '롤토체스'],
    '기타 모드': ['우르프', 'urf', '돌격 넥서스', '넥서스 블리츠'],
}

# 여러 글자라 부분 일치로 찾아도 오인할 일이 적은 말들.
DOMAIN_TERMS = [
    '챔피언', '아이템', '템트리', '빌드', '스킬', '패시브', '궁극기', '쿨타임', '재사용 대기',
    '라인전', '딜교', '한타', '포킹', '스플릿', '로밍', '갱킹', '카운터정글', '정글링',
    '미니언', '시야', '와드', '부쉬', '드래곤', '바론', '전령', '타워', '포탑', '억제기',
    '소환사', '협곡', '솔랭', '자유랭크', '랭크', '티어', '픽창', '밴픽',
    '패치', '너프', '버프', '상향', '하향', '메타', '숙련도', '전적',
    '군중 제어', '군중제어', '주문력', '마법 저항', '생명력 흡수',
    '치명타', '강인함', '중첩', '소환사 주문', '점멸', '텔레포트',
]

# 아래는 일부러 넣지 않는다. 롤 밖에서도 흔히 쓰는 말이라 오인이 생긴다.
#   이동 속도  -> '이동 속도 빠른 자전거'
#   방어력     -> '방어력 높은 자동차'
#   체력, 회복, 피해, 공격력 -> '체력 기르는 운동', '피해 보상'
# 이런 말만 있는 질문은 롤이라는 근거로 보지 않는다.

# 한두 글자라 다른 뜻으로 쓰일 수 있다. 낱말이 정확히 같을 때만 인정한다.
SHORT_TERMS = {'탑', '미드', '바텀', '봇', '정글', '원딜', '서폿', '서포터', '룬', '궁',
               '큐', '평타', 'cs', 'ad', 'ap', 'mr', 'kda', 'lp',
               '롤', '킬', '데스', '어시', '스택'}
# '롤' 을 부분 일치로 찾으면 '크롤러' 가 걸린다. 낱말이 정확히 같을 때만 본다.

MESSAGES = {
    'off_topic': '롤에 대한 질문만 답할 수 있습니다.',
    'out_of_scope': 'RiftFlow 는 소환사의 협곡만 다룹니다. %s 자료는 가지고 있지 않습니다.',
}


def normalize(question):
    return question.lower().replace(' ', '')


def tokens_of(question):
    cleaned = question.lower()
    for mark in '?!.,~':
        cleaned = cleaned.replace(mark, ' ')
    return {word.strip('은는이가을를에서의로도만') or word for word in cleaned.split()}


def find_other_mode(question):
    """협곡이 아닌 모드를 가리키는지 본다."""
    packed = normalize(question)
    for mode, keywords in OTHER_MODES.items():
        for keyword in keywords:
            if keyword.replace(' ', '') in packed:
                return mode
    return None


def entity_names(chunks):
    """자료에 실제로 있는 이름들. 두 글자짜리는 넣지 않는다."""
    return {chunk['subject_name'].lower() for chunk in chunks or []
            if len(chunk['subject_name']) > 2}


def looks_like_lol(question, names):
    """롤 질문이라고 볼 근거를 찾는다.

    없는 것을 찾는 방식(금지어 목록)은 끝이 없다.
    그래서 반대로 롤이라는 증거가 있을 때만 통과시킨다.
    '회복 잘 되는 영양제' 처럼 우리 자료에 있는 단어를 써도
    롤 용어가 하나도 없으면 통과하지 못한다.
    """
    packed = normalize(question)
    for term in DOMAIN_TERMS:
        if term.replace(' ', '') in packed:
            return '롤 용어: ' + term

    for token in tokens_of(question):
        if token in SHORT_TERMS:
            return '롤 용어: ' + token

    # 아이템이나 챔피언 이름이 통째로 나오는 경우.
    # '대검' 처럼 이름의 일부만 겹치는 것은 인정하지 않는다.
    for name in names:
        if name.replace(' ', '') in packed:
            return '자료에 있는 이름: ' + name

    return None


def check(question, chunks=None):
    """질문을 판정한다. Gemini 를 부르기 전에 실행한다."""
    if not question or not question.strip():
        return {'decision': 'off_topic', 'reason': '빈 질문',
                'message': MESSAGES['off_topic']}

    # 모드 판정을 먼저 한다. 칼바람 질문에도 롤 용어가 들어 있기 때문이다.
    mode = find_other_mode(question)
    if mode:
        return {'decision': 'out_of_scope', 'reason': '다른 모드: ' + mode,
                'message': MESSAGES['out_of_scope'] % mode}

    evidence = looks_like_lol(question, entity_names(chunks))
    if not evidence:
        return {'decision': 'off_topic', 'reason': '롤이라는 근거 없음',
                'message': MESSAGES['off_topic']}

    return {'decision': 'allow', 'reason': evidence, 'message': None}
