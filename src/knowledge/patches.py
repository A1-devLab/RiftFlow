"""Conservative extraction of Riot patch sections; raw evidence is always kept."""
import re
from html.parser import HTMLParser


class PatchParser(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.events = []
        self.capture = None
        self.skip = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style'):
            self.skip += 1
        if self.skip:
            return
        classes = attrs.get('class', '').split()
        if self.capture is None and (tag in ('h2', 'h3', 'h4', 'li') or
                                     (tag == 'p' and 'summary' in classes)):
            self.capture = [tag, attrs, []]
        elif tag == 'br' and self.capture:
            self.capture[2].append(' ')

    def handle_data(self, text):
        if self.capture and not self.skip:
            self.capture[2].append(text)

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if not self.skip and self.capture and tag == self.capture[0]:
            kind, attrs, parts = self.capture
            self.events.append((kind, attrs, re.sub(r'\s+', ' ', ''.join(parts)).strip()))
            self.capture = None


def direction(stat, before, after):
    """Only compare unambiguous scalar/rank lists and known stat semantics."""
    if any(k in stat for k in ('받는', '감소량', '피해 감소', '잃은', '잃는')):
        return 'unknown'
    lower = ('재사용 대기시간', '마나 소모량', '기력 소모량', 'cooldown', 'mana cost', '총 가격', 'total cost')
    higher = ('피해량', '공격력', '주문력', '방어력', '마법 저항력', '체력', '회복량',
              '공격 속도', '이동 속도', 'damage', 'armor', 'health', 'attack speed')
    polarity = -1 if any(k in stat.lower() for k in lower) else (
        1 if any(k in stat.lower() for k in higher) else 0)
    pattern = r'\s*[-+]?\d+(?:\.\d+)?(?:\s*/\s*[-+]?\d+(?:\.\d+)?)*\s*(?:%|초|골드|seconds?)?\s*'
    if not polarity:
        return 'unknown'
    simple = bool(re.fullmatch(pattern, before) and re.fullmatch(pattern, after))
    number = r'[-+]?\d+(?:\.\d+)?'
    skeleton = lambda value: re.sub(number, '#', re.sub(r'\s+', '', value))
    # Identical formula wording: compare corresponding coefficients, not prose.
    if not simple and skeleton(before) != skeleton(after):
        return 'unknown'
    if simple and re.sub(r'[\d\s./+\-]', '', before) != re.sub(r'[\d\s./+\-]', '', after):
        return 'unknown'
    if re.findall(r'\d+(?:\.\d+)?%?당', before) != re.findall(r'\d+(?:\.\d+)?%?당', after):
        return 'unknown'
    a = [float(x) for x in re.findall(number, before)]
    b = [float(x) for x in re.findall(number, after)]
    if simple and len(a) == 1:
        a *= len(b)
    if simple and len(b) == 1:
        b *= len(a)
    if len(a) != len(b):
        return 'unknown'
    signs = {(y > x) - (y < x) for x, y in zip(a, b)} - {0}
    if not signs:
        return 'unchanged'
    if len(signs) > 1:
        return 'adjusted'
    return 'buff' if signs.pop() * polarity > 0 else 'nerf'


def parse_patch(html):
    """Extract only main champion/item/rune sections, excluding other modes."""
    section = None
    entity = None
    ability = ''
    result = []
    sections = {'patch-champions': 'champion', 'patch-items': 'item', 'patch-runes': 'rune'}
    names = {'챔피언': 'champion', '아이템': 'item', '룬': 'rune',
             'champions': 'champion', 'items': 'item', 'runes': 'rune'}
    for tag, attrs, text in PatchParser(html).events:
        if tag == 'h2':
            section = sections.get(attrs.get('id')) or names.get(text.lower())
            entity, ability = None, ''
        elif tag == 'h3':
            entity, ability = None, ''
            if section and 'change-title' in attrs.get('class', '').split():
                entity = {'entity_kind': section, 'entity_name': text,
                          'section_id': attrs.get('id', text), 'summary': '', 'changes': []}
                result.append(entity)
        elif entity is not None:
            if tag == 'h4':
                ability = text
            elif tag == 'p':
                entity['summary'] = text
            elif tag == 'li':
                parts = re.split(r'⇒|→|\s+->\s+', text, maxsplit=1)
                stat, before, after = text, None, None
                if len(parts) == 2 and re.search(r'[:：]', parts[0]):
                    stat, before = re.split(r'[:：]', parts[0], maxsplit=1)
                    before, after = before.strip(), parts[1].strip()
                entity['changes'].append({'ability': ability, 'stat': stat.strip(),
                    'before': before, 'after': after, 'raw_text': text,
                    'direction': direction(stat, before, after) if before and after else 'unknown',
                    'parse_status': 'parsed' if before is not None else 'unparsed'})
    for entity in result:
        directions = {c['direction'] for c in entity['changes']} - {'unchanged'}
        entity['change_type'] = (next(iter(directions)) if len(directions) == 1
                                 else 'adjusted' if directions else 'unknown')
        # Explicit editorial summaries take precedence over numerical heuristics.
        summary = entity['summary']
        buff = bool(re.search(r'상향|강화|\bbuff', summary, re.I))
        nerf = bool(re.search(r'하향|약화|\bnerf', summary, re.I))
        if buff or nerf:
            entity['change_type'] = 'adjusted' if buff and nerf else 'buff' if buff else 'nerf'
            entity['classification_basis'] = 'official_summary'
        else:
            entity['classification_basis'] = 'numeric_heuristic'
    return result
