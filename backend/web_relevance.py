"""Question-grounded signals shared by candidate scheduling and passage selection."""
import re
import unicodedata


def normalize(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value)).casefold())


def terms(value):
    tokens = set()
    for word in re.findall(r'[a-z0-9]+(?:[.+-][a-z0-9]+)*|[\u3400-\u9fff]+', str(value).casefold()):
        if len(word) == 1 or word.isascii():
            tokens.add(word)
        else:
            tokens.update(word[i:i+2] for i in range(len(word)-1))
    return tokens


def grounded_constraints(constraints, question, background):
    verified = [item for item in constraints if item.quote in (
        question if item.origin == 'message' else background)]
    explicit = {item.kind for item in verified if item.origin == 'message'}
    return [item for item in verified if item.origin == 'message' or item.kind not in explicit]


def term_match(value, text):
    value = unicodedata.normalize('NFKC', value).casefold().strip()
    if not value:
        return False
    if value.isascii():
        return bool(re.search(r'(?<![a-z0-9])' + re.escape(value) + r'(?![a-z0-9])',
                              unicodedata.normalize('NFKC', text).casefold()))
    return normalize(value) in normalize(text)


def relevance(source, question, args):
    title = source['title']
    snippet = source.get('snippet', '')[:500]
    matched, unknown = [], []
    title_hits = 0
    for item in args.constraints:
        values = [item.quote, *item.aliases]
        # The provider date is only a hint for publication-time requests.
        heading = title if item.kind != 'publication_time' else str(source.get('published_at') or '')
        in_title = any(term_match(v, heading) for v in values)
        found = in_title or any(term_match(v, snippet) for v in values)
        (matched if found else unknown).append(item.quote)
        title_hits += int(in_title)
    years = set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', question))
    title_years = set(re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)', title))
    for first,last in re.findall(r'((?:19|20)\d{2})\s*年?\s*(?:[-–—~～至到]|to)\s*((?:19|20)\d{2})',title,re.I):
        title_years.update(str(y) for y in range(int(first),int(last)+1))
    # A title year is a ranking hint, never proof of the effective period.
    year_hint = 0
    if years and title_years and not any(c.kind == 'publication_time' for c in args.constraints):
        year_hint = 1 if years & title_years else -1
    # A document explicitly scoped to a different year cannot establish a
    # requested year's terms. A plain date in a URL or publication stamp cannot veto it.
    scoped_years = set(re.findall(r'((?:19|20)\d{2})\s*年(?:度|版|入学|招生|本科|实施方案|申请|接收)', title))
    effective_years = {year for c in args.constraints if c.kind == 'effective_time'
                       for year in re.findall(r'(?:19|20)\d{2}', c.quote)}
    different_period = bool(effective_years and scoped_years and effective_years.isdisjoint(title_years))
    overlap = len(terms(question) & terms(title))
    direct = (len(matched)>=2 and not unknown and title_hits==len(matched) and year_hint>=0
              and not source.get('parent_url') and any(c.kind in ('entity','action','version') for c in args.constraints))
    return {'matched': matched, 'unknown': unknown, 'direct':direct,
            'different_period': different_period,'title_hits': title_hits, 'year_hint': year_hint, 'overlap': overlap}


def excerpt(text, queries, limit=3600):
    """Select contiguous windows; prioritize the matching rows over page chrome."""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    keywords = terms(' '.join(queries))
    # Work with offsets so each returned block is a literal slice of the original,
    # including line breaks and table formatting. Split long single-line pages too.
    width = max(32,min(320,limit//4))
    spans = [(m.start()+i, min(m.start()+i+width,m.end()))
             for m in re.finditer(r'[^\n]*\n|[^\n]+$',text)
             for i in range(0,m.end()-m.start(),width)]
    lines = [text[a:b] for a,b in spans]
    scores = [len(keywords & terms(line)) / (1 + line.count('](')) for line in lines]
    heads = []
    for j,line in enumerate(lines):
        heads.append(heads[-1] if j and '|' in lines[j-1] and '|' in line else j)
    chosen = set()
    used = 0
    for i in sorted(range(len(lines)), key=lambda j:-scores[j]):
        if chosen and not scores[i]:
            break
        window = set(range(max(0,i-1), min(len(lines),i+3)))
        if '|' in lines[i]:
            head = heads[i]
            window.update(range(head,min(i+1,head+2)))
        extra = window-chosen
        cost = sum(len(lines[j])+3 for j in extra)
        if cost and used+cost <= limit:
            chosen.update(extra)
            used += cost
        if used >= limit-64:
            break
    if not chosen:
        return text[:limit]
    blocks = []
    previous = -2
    for j in sorted(chosen):
        if j != previous+1:
            blocks.append([spans[j][0],spans[j][1]])
        else:
            blocks[-1][1] = spans[j][1]
        previous = j
    return '\n…\n'.join(text[a:b] for a,b in blocks)
