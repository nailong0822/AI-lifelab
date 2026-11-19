"""Fit web answers without silently replacing the primary source with a weaker one."""
import copy
import re
from .providers import ProviderError, estimate_tokens
from .store import encode
from .web_relevance import excerpt


def citation_numbers_supported(claim,quote,title):
    numbers=lambda text:set(re.findall(r'\d+(?:\.\d+)?',text.replace(',','')))
    # A document year may be explicit in its title but absent from a table-row quote.
    # Compare whole numbers: "3" must not be accepted just because a quote says "30".
    return numbers(claim).issubset(numbers(quote+' '+title))


def original_quote(quote, passage):
    """Recover literal page whitespace while keeping the same words and punctuation."""
    for block in passage.split('\n…\n'):
        if quote in block:
            return quote
        compact = re.sub(r'\s+', '', quote)
        if len(compact)<8:
            continue
        offsets = [i for i,char in enumerate(block) if not char.isspace()]
        start = ''.join(block[i] for i in offsets).find(compact)
        if start >= 0:
            literal = block[offsets[start]:offsets[start+len(compact)-1]+1]
            if len(literal)<=700:
                return literal
    return None


def fit_web_context(context, instruction, schema, remaining_tokens, context_limit=18000):
    payload=copy.deepcopy(context)
    sources=payload['web']['sources']
    original_ids=[s['id'] for s in sources]
    primary=original_ids[0] if original_ids else None
    inventory=payload['web'].get('source_inventory',[])
    for item in inventory:
        item['passage_supplied']=item['id'] in original_ids
    # Bound the first answer as well as repairs; do not spend the entire turn on its input.
    ceiling=min(context_limit,remaining_tokens-1800)
    changes=[]
    def estimate():
        return estimate_tokens(instruction+encode(payload)+encode(schema))+300
    def compact(value,limit=250):
        if isinstance(value,str): return value[:limit]
        if isinstance(value,list): return [compact(v,limit) for v in value[:8]]
        if isinstance(value,dict): return {k:compact(v,limit) for k,v in value.items()}
        return value
    while payload.get('recent') and estimate()>ceiling:
        payload['recent']=payload['recent'][1:]
        if 'older_chat' not in changes: changes.append('older_chat')
    for field in ('summary','evidence'):
        if payload.get(field) and estimate()>ceiling:
            payload[field]=[] if isinstance(payload[field],list) else ''
            changes.append(field)
    if estimate()>ceiling:
        payload['profile']=compact(payload.get('profile',{}))
        payload['memories']=compact(payload.get('memories',[]))
        stage=payload.get('stage') or {}
        associated=payload.get('associated_task_id')
        payload['stage']={k:compact(v) for k,v in stage.items() if k!='tasks'}
        payload['stage']['tasks']=[t if t.get('id')==associated else {
            k:compact(v,120) for k,v in t.items() if k in ('id','title','completion_criteria','depends_on')
        } for t in stage.get('tasks',[])]
        payload['question']=str(payload.get('question',''))[:600]
        changes.append('background_compacted')
    # Fair reduction: every supplied source retains a passage before any low-priority
    # source is removed. The model-selected primary source is never removed.
    for limit in (1200,800,500,350):
        if estimate()<=ceiling: break
        for source in sources:
            if len(source['excerpt'])>limit:
                source['excerpt']=excerpt(source['excerpt'],[payload.get('message','')],limit)
                source['excerpt_is_partial']=True
        changes.append('passages_'+str(limit))
    if estimate()>ceiling:
        for item in inventory: item['title']=item.get('title','')[:65]
        changes.append('inventory_titles_compacted')
    while len(sources)>1 and estimate()>ceiling:
        removed=sources.pop()
        for item in inventory:
            if item['id']==removed['id']: item['passage_supplied']=False
        changes.append('lower_priority_passage_omitted')
    if estimate()>ceiling:
        raise ProviderError('本轮预算不足以保留关键网页证据，已停止回答；请发送新消息继续核实，原搜索记录已保存')
    supplied={s['id'] for s in sources}
    for item in inventory:
        item['passage_supplied']=item['id'] in supplied
    report={'primary_source_id':primary,'source_ids':[s['id'] for s in sources],
        'omitted_passage_ids':[i for i in original_ids if i not in supplied],
        'estimated_input_tokens':estimate(),'compactions':changes}
    return payload,report
