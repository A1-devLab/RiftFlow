"""근거 자료 fixture 생성. 표준 라이브러리만 사용하며 API 키가 필요 없다.

RiftFlow 의 대상 범위는 소환사의 협곡(맵 11)이다.
같은 이름의 아이템이 모드별로 다른 ID, 다른 골드, 다른 능력치를 가지므로
협곡에서 쓸 수 있는 것만 담는다. 칼바람나락과 아레나는 범위 밖이다.

version 필드는 src/knowledge/ 의 records 테이블과 같은 규칙을 쓴다.
kind 에 따라 담기는 값이 다르다.
  kind 가 item, rune, champion 이면  Data Dragon 데이터 버전. 예 16.18.1
  kind 가 patch 이면                  패치 노트의 패치 번호.   예 26.18
둘은 번호 체계가 다르며 한쪽에서 다른 쪽을 계산할 수 없다.
16.18.1 을 잘라 16.18 을 만들면 존재하지 않는 값이 된다.
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

DDRAGON = "https://ddragon.leagueoflegends.com"
PATCH_LIST = "https://www.leagueoflegends.com/ko-kr/news/tags/patch-notes/"
LOCALE = "ko_KR"
TARGET_MAP = "11"  # 소환사의 협곡. 모드별 변형 아이템을 걸러내는 안전망이다.

# 패치 노트 본문은 저작물이므로 전문을 저장소에 두지 않는다.
# 청킹과 인용을 시험할 만큼만 발췌하고 전체 길이를 따로 기록한다.
# 글 앞부분은 이벤트 소개라 근거로 쓸 값이 없다.
# 챔피언 밸런스 구간부터 잘라야 수치 변경이 들어온다.
EXCERPT_CHARS = 2500
EXCERPT_ANCHOR = "\n챔피언\n"

# 소환사의 협곡에서 살 수 있는 아이템을 전부 담는다.
# 이 값보다 싼 것은 소모품과 시작 아이템이라 추천 근거로 쓰지 않는다.
MIN_ITEM_GOLD = 500

# 아이템 ID 가 4자리를 넘으면 모드 전용 사본이다.
# 예를 들어 322065 는 2065(슈렐리아의 군가)의 사본이고, 663193 은 협곡에 없는 아이템이다.
# 이들도 maps["11"] 이 참이라 맵 검사만으로는 걸러지지 않는다.
# 경기 기록(MATCH-V5)과 인게임 API 가 보고하는 ID 는 4자리라서 그쪽에 맞춘다.
MAX_ITEM_ID_DIGITS = 4

# 챔피언 상세 파일은 한 명당 한 번 받아야 한다. 173명이면 약 17초 걸린다.
# 목록 파일에는 spells 와 passive 가 없어 룬과 스킬 근거를 만들 수 없다.
CHAMPION_LIMIT = None  # None 이면 전부

# 아래는 Data Dragon 데이터가 아니라 RiftFlow 자체 주석이다. README 에 그렇게 밝힌다.
SITUATION_OVERLAY = {
    "item:3139": ["상대CC많음", "단일대상궁", "생존"],
    "item:3102": ["상대AP위주", "스킬샷차단", "생존"],
    "item:3065": ["상대AP위주", "자체회복보유", "탱커"],
    "item:3047": ["상대AD위주", "기본공격위주상대"],
    "item:3111": ["상대CC많음", "이동방해"],
    "item:3033": ["상대회복많음", "치유감소"],
    "item:3123": ["상대회복많음", "치유감소"],
    "item:3157": ["순간폭딜차단", "생존", "마법사"],
    "item:3031": ["치명타빌드", "지속딜", "장기전"],
    "item:3116": ["둔화", "마법사", "추격"],
    # 핵심 룬은 딜교환 방식으로 갈린다. 픽창에서 성향을 물어 여기에 잇는다.
    "rune:8010": ["지속교전", "장기전", "브루저"],       # 정복자
    "rune:8005": ["지속교전", "라인전", "원거리딜러"],     # 집중 공격
    "rune:8008": ["지속교전", "치명타빌드", "원거리딜러"],  # 치명적 속도
    "rune:8437": ["지속교전", "생존", "탱커"],           # 착취의 손아귀
    "rune:8112": ["순간폭딜", "치고빠지기", "라인전"],     # 감전
    "rune:8128": ["순간폭딜", "성장형", "암살"],          # 어둠의 수확
    "rune:9923": ["순간폭딜", "치고빠지기", "원거리딜러"],  # 칼날비
    "rune:8439": ["생존", "탱커", "상대순간폭딜"],        # 여진
    "rune:8465": ["생존", "아군보호", "서포터"],          # 수호자
    "rune:8021": ["기동", "치고빠지기"],                 # 기민한 발놀림
    "rune:8229": ["순간폭딜", "마법사", "라인전"],        # 신비로운 유성
    "rune:8214": ["지속교전", "마법사"],                 # 콩콩이 소환
    "rune:8230": ["기동", "추격"],                      # 폭풍전사의 포효
    "rune:8992": ["지속딜", "마법사", "장기전"],          # 죽음불꽃 손길
}

# 챔피언의 Data Dragon 분류를 상황 태그로 옮긴다. 판단이 아니라 데이터에서 온다.
ROLE_TO_SITUATION = {
    "Fighter": "브루저", "Tank": "탱커", "Marksman": "원거리딜러",
    "Mage": "마법사", "Support": "서포터", "Assassin": "암살",
}

TAG_TO_SITUATION = {
    "CriticalStrike": "치명타빌드", "SpellBlock": "상대AP위주", "Armor": "상대AD위주",
    "Health": "생존", "LifeSteal": "지속생존", "SpellVamp": "지속생존",
    "Boots": "이동", "Jungle": "정글", "Lane": "라인전", "Vision": "시야",
}


def fetch(url):
    request = Request(url, headers={"User-Agent": "RiftFlow-Fixture-Builder/0.1"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def fetch_json(url):
    return json.loads(fetch(url))


def strip_html(raw):
    """Data Dragon 설명의 마크업을 걷어내고 읽을 수 있는 평문으로 만든다."""
    if not raw:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", raw)
    text = re.sub(r"</(mainText|stats|li|ul|p)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def damage_type(info):
    """공격력 중심인지 주문력 중심인지 가른다. 알 수 없으면 None 이다.

    Data Dragon 의 info.attack 과 info.magic 을 비교한 값이라 우리 판단이 아니다.
    포지션(탑, 정글 등)은 Data Dragon 이 제공하지 않아 넣을 수 없다.

    아크샨, 렐, 세라핀, 벡스는 info 가 난이도까지 전부 0 이다.
    난이도 0 인 챔피언은 없으므로 이것은 점수가 아니라 값이 비어 있는 것이다.
    0 과 0 을 비교해 '혼합' 으로 적으면 틀린 근거가 된다. (누락된 값은 0 과 구분한다)
    """
    attack, magic = info.get("attack"), info.get("magic")
    if not any(info.get(key) for key in ("attack", "defense", "magic", "difficulty")):
        return None
    if attack is None or magic is None:
        return None
    if attack > magic:
        return "AD"
    if magic > attack:
        return "AP"
    return "혼합"


def champion_situation_tags(champion):
    tags = []
    for role in champion.get("tags") or []:
        mapped = ROLE_TO_SITUATION.get(role)
        if mapped:
            tags.append(mapped)
    kind = damage_type(champion.get("info") or {})
    if kind is not None:
        tags.append({"AD": "AD챔피언", "AP": "AP챔피언"}.get(kind, "혼합딜챔피언"))
    return tags


def situation_tags(kind, entity_id, ddragon_tags):
    tags = list(SITUATION_OVERLAY.get(kind + ":" + entity_id, []))
    for tag in ddragon_tags or []:
        mapped = TAG_TO_SITUATION.get(tag)
        if mapped and mapped not in tags:
            tags.append(mapped)
    return tags


def content_hash(raw_content):
    """src/knowledge/ 의 save() 와 같은 방식으로 원본 내용의 해시를 만든다.

    해시 대상은 가공한 text 가 아니라 원본 content 다.
    게임 데이터는 json.dumps(entity, ensure_ascii=False, sort_keys=True),
    패치 노트는 본문 전문이다. 그래야 DB 의 content_hash 와 같은 값이 나온다.
    """
    return hashlib.sha256(raw_content.encode("utf-8")).hexdigest()


def raw_of(entity):
    """records 테이블에 저장되는 형태 그대로 직렬화한다."""
    return json.dumps(entity, ensure_ascii=False, sort_keys=True)


def document(kind, entity_id, name, title, url, text, fields, tags, version, raw_content, now):
    prefix = "patchnote" if kind == "patch" else "ddragon"
    return {
        "doc_id": ":".join([prefix, kind, entity_id, version]),
        "kind": kind,
        "entity_id": entity_id,
        "version": version,
        "subject_name": name,
        "title": title,
        "source_url": url,
        "text": text,
        "fields": fields,
        "situation_tags": tags,
        "content_hash": content_hash(raw_content),
        "updated_at": now,
    }


class Page(HTMLParser):
    """공식 페이지의 링크와 본문을 읽는 간단한 HTML 파서."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.links, self.text, self.main, self.heading = [], [], [], []
        self.skip = 0
        self.in_main = False
        self.in_heading = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "main":
            self.in_main = True
        if tag == "h1":
            self.in_heading = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        if tag == "main":
            self.in_main = False
        if tag == "h1":
            self.in_heading = False

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.text.append(data.strip())
            if self.in_main:
                self.main.append(data.strip())
            if self.in_heading:
                self.heading.append(data.strip())


def ddragon_documents(version, now):
    base = DDRAGON + "/cdn/" + version + "/data/" + LOCALE + "/"
    items = fetch_json(base + "item.json")["data"]
    runes = fetch_json(base + "runesReforged.json")
    docs, skipped = [], []

    for entity_id, data in sorted(items.items()):
        if not data.get("maps", {}).get(TARGET_MAP):
            continue
        if len(entity_id) > MAX_ITEM_ID_DIGITS:
            skipped.append("item:" + entity_id + " (모드 전용 사본)")
            continue
        gold = data.get("gold") or {}
        if not gold.get("purchasable") or gold.get("total", 0) < MIN_ITEM_GOLD:
            continue
        plain = (data.get("plaintext") or "").strip()
        body = strip_html(data.get("description"))
        docs.append(document(
            "item", entity_id, data["name"], data["name"] + " - 아이템 정보",
            base + "item.json", (plain + "\n" + body).strip() if plain else body,
            {
                "gold_total": data["gold"]["total"],
                "gold_base": data["gold"]["base"],
                "purchasable": data["gold"]["purchasable"],
                "stats": data.get("stats") or {},
                "builds_from": data.get("from") or [],
                "builds_into": data.get("into") or [],
                "depth": data.get("depth"),
                "ddragon_tags": data.get("tags") or [],
            },
            situation_tags("item", entity_id, data.get("tags")),
            version, raw_of(data), now))

    for tree in runes:
        for slot_index, slot in enumerate(tree["slots"]):
            for rune in slot["runes"]:
                entity_id = str(rune["id"])
                slot_name = "핵심" if slot_index == 0 else "%d번 슬롯" % slot_index
                docs.append(document(
                    "rune", entity_id, rune["name"],
                    rune["name"] + " - " + tree["name"] + " " + slot_name,
                    base + "runesReforged.json",
                    strip_html(rune.get("longDesc")) or strip_html(rune.get("shortDesc")),
                    {"tree_id": tree["id"], "tree_name": tree["name"],
                     "slot": slot_name, "rune_key": rune["key"]},
                    situation_tags("rune", entity_id, None), version,
                    raw_of(rune), now))

    # 챔피언은 목록 파일이 아니라 상세 파일에서 읽는다.
    # champion.json 에는 spells 와 passive 가 없어서 룬 추천 근거를 만들 수 없다.
    listing = sorted(fetch_json(base + "champion.json")["data"])
    if CHAMPION_LIMIT:
        listing = listing[:CHAMPION_LIMIT]
    for entity_id in listing:
        url = base + "champion/" + entity_id + ".json"
        champion = fetch_json(url)["data"][entity_id]
        lines = ["패시브 " + champion["passive"]["name"] + ": "
                 + strip_html(champion["passive"]["description"])]
        for key, spell in zip("QWER", champion["spells"]):
            lines.append(key + " " + spell["name"] + ": " + strip_html(spell["description"]))
        # allytips 와 enemytips 는 라이엇이 직접 쓴 플레이 조언이다.
        # 코치 역할에 바로 쓸 수 있는 근거라 함께 담는다.
        for tip in champion.get("allytips") or []:
            lines.append("운영 조언: " + strip_html(tip))
        for tip in champion.get("enemytips") or []:
            lines.append("상대할 때: " + strip_html(tip))
        docs.append(document(
            "champion", entity_id, champion["name"], champion["name"] + " - 스킬과 운영", url,
            "\n".join(lines),
            {
                "champion_key": champion["key"],
                "resource": champion["partype"],
                "ddragon_tags": champion["tags"],
                "damage_type": damage_type(champion.get("info") or {}),
                "info": champion.get("info") or {},
                "base_stats": champion["stats"],
                "spell_ids": [spell["id"] for spell in champion["spells"]],
                "passive_name": champion["passive"]["name"],
            },
            champion_situation_tags(champion), version, raw_of(champion), now))

    return docs, skipped


def patch_documents(now, limit=1):
    """공식 한국어 패치 노트. 패치 번호는 제목에서 읽는다. Data Dragon 버전과 무관하다."""
    listing = Page(fetch(PATCH_LIST))
    urls = []
    for href in listing.links:
        url = urljoin(PATCH_LIST, href).split("?")[0].rstrip("/") + "/"
        if (urlsplit(url).hostname == "www.leagueoflegends.com"
                and "/ko-kr/news/game-updates/" in url and "patch" in url
                and url not in urls):
            urls.append(url)
    if not urls:
        raise ValueError("패치 링크를 찾지 못했습니다. 공식 사이트 구조를 확인하세요.")

    docs = []
    for url in urls[:limit]:
        page = Page(fetch(url))
        title = " ".join(page.heading)
        body = "\n".join(page.main or page.text)
        if not title or len(body) < 200:
            raise ValueError("패치 본문을 읽지 못했습니다: " + url)
        match = re.search(r"\b(\d{1,2}\.\d{1,2})\b", title)
        patch = match.group(1) if match else "unknown"
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        start = body.find(EXCERPT_ANCHOR)
        start = start + 1 if start >= 0 else 0
        excerpt = body[start:start + EXCERPT_CHARS]
        docs.append(document(
            "patch", slug, title, title, url, excerpt,
            {
                "article_url": url,
                "text_is_excerpt": True,
                "excerpt_start_char": start,
                "excerpt_chars": len(excerpt),
                "full_text_chars": len(body),
                "note": "저작물이므로 발췌만 저장한다. 전문은 knowledge DB 에서 읽는다.",
            },
            [], patch, body, now))
    return docs


def main():
    target = sys.argv[1]
    now = datetime.now(timezone.utc).isoformat()
    version = fetch_json(DDRAGON + "/api/versions.json")[0]
    docs, skipped = ddragon_documents(version, now)
    patches = patch_documents(now)
    docs.extend(patches)

    payload = {
        "_note": (
            "Data Dragon 과 공식 패치 노트의 실제 데이터입니다. 개인정보 없음, API 키 불필요. "
            "situation_tags 는 Data Dragon 데이터가 아니라 RiftFlow 자체 주석입니다. "
            "kind='patch' 문서의 text 는 발췌입니다. "
            "version, content_hash, updated_at 규칙은 src/knowledge/ 의 records 테이블과 같습니다. "
            "형식은 knowledge 담당자와 합의 전 초안입니다."
        ),
        "source": "Riot Games Data Dragon / 공식 한국어 패치 노트",
        "scope": "소환사의 협곡 (맵 11)",
        "ddragon_version": version,
        "patch": patches[0]["version"] if patches else None,
        "version_note": "문서의 version 은 kind 가 patch 면 패치 번호, 그 외에는 Data Dragon 버전입니다.",
        "locale": LOCALE,
        "generated_at": now,
        "document_count": len(docs),
        "documents": docs,
    }
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print("ddragon_version=" + version + "  patch=" + str(payload["patch"])
          + "  docs=" + str(len(docs)) + " -> " + target)
    if skipped:
        print("건너뜀: " + ", ".join(skipped))


if __name__ == "__main__":
    main()
