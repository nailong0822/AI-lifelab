"""Bounded public-web tool: Tavily Search/Extract, persistent budgets and evidence."""
import asyncio
import hashlib
import html
import ipaddress
import json
import re
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from langchain_core.tools import StructuredTool
from .providers import ProviderError, estimate_tokens
from .store import encode
from .web_relevance import excerpt, relevance
from .web_models import WebSearchArgs, WebReview, WEB_TOOL_DESCRIPTION, REVIEW_INSTRUCTION


def public_url(value):
    """Only provider-returned public HTTP(S) URLs; never fetch targets ourselves."""
    try:
        parts = urlsplit(str(value).strip())
        host = (parts.hostname or '').lower().rstrip('.').encode('idna').decode()
        if parts.scheme not in ('http', 'https') or parts.username or parts.password or parts.port not in (None, 80, 443):
            return None
        if not host or '.' not in host or host.endswith(('.local', '.localhost', '.internal', '.test')) or host == 'localhost':
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if re.fullmatch(r'[\d.]+', host) or host.startswith('0x'):
                return None
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        if any(re.search(r'^(?:token|access_token|api_key|authorization|secret|signature|password)$', k, re.I) for k, _ in pairs):
            return None
        pairs = [(k,v) for k,v in pairs if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')]
        return urlunsplit((parts.scheme, host, parts.path or '/', urlencode(pairs), ''))
    except (ValueError, UnicodeError):
        return None


def domain_list(values):
    result = []
    for value in values[:5]:
        candidate = str(value).strip().lower()
        url = public_url(candidate if '://' in candidate else 'https://' + candidate)
        if url:
            host = urlsplit(url).hostname
            if host not in result:
                result.append(host)
    return result


def search_text(value):
    text = re.sub(r'[\x00-\x1f]', ' ', str(value))
    text = re.sub(r'\b(?:sk-|tvly-)[A-Za-z0-9_-]+|\b[A-Fa-f0-9]{32,}\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)', '', text)
    text = re.sub(r'(?i)(api[_ -]?key|access[_ -]?secret|password|密码)\s*[:=：]\s*\S+', '', text)
    return re.sub(r'\s+', ' ', text).strip()[:240]


class TavilyProvider:
    def __init__(self, key, client):
        self.key, self.client = key, client

    async def request(self, endpoint, body, timeout):
        try:
            response = await self.client.post('https://api.tavily.com/' + endpoint,
                headers={'Authorization':'Bearer ' + self.key}, json=body,
                timeout=httpx.Timeout(timeout, connect=min(5,timeout)), follow_redirects=False)
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise ProviderError('搜索服务连接超时，本轮资料可能不完整', retryable=True) from error
        if response.status_code in (401,403):
            raise ProviderError('搜索服务鉴权失败，请检查服务端 TAVILY_API_KEY')
        if response.status_code in (429,432,433) or response.status_code >= 500:
            raise ProviderError('搜索服务额度、频率受限或暂时不可用', retryable=True)
        if not response.is_success:
            raise ProviderError('搜索服务请求未成功，HTTP ' + str(response.status_code))
        try:
            if len(response.content) > 2_000_000:
                raise ValueError('oversized')
            result = response.json()
            if not isinstance(result,dict) or not isinstance(result.get('results',[]),list):
                raise ValueError('shape')
            return result
        except (ValueError, TypeError) as error:
            raise ProviderError('搜索服务返回的数据无法读取') from error

    async def search(self, query, args, timeout):
        body = {'query':query, 'max_results':6, 'search_depth':'advanced', 'chunks_per_source':3,
                'include_answer':False, 'include_raw_content':False, 'topic':args.topic, 'include_published_date':True}
        if args.preferred_domains:
            body['include_domains'] = domain_list(args.preferred_domains)
        if args.time_range:
            body['time_range'] = args.time_range
        return await self.request('search',body,timeout)

    async def extract(self, urls, timeout):
        return await self.request('extract', {'urls':urls, 'extract_depth':'advanced', 'format':'markdown',
            'include_images':False, 'include_published_date':True, 'timeout':max(1,min(12,timeout-1))}, timeout)


class WebSearchTool:
    MAX_SEARCHES = 4
    MAX_READS = 4
    PASSAGE_FIELDS = ('id','title','url','published_at','retrieved_at','read_status','kind','parent_url')

    def __init__(self, settings, store, turn_id, provider, invoke_model):
        self.settings, self.store, self.turn_id = settings, store, turn_id
        self.provider, self.invoke_model = provider, invoke_model
        turn = store.get('turns', turn_id)
        self.question = turn['input']['text']
        self.web = turn.get('web') or {}
        self.web.setdefault('sources',[]); self.web.setdefault('queries',[])
        self.web.setdefault('reads',[]); self.web.setdefault('warnings',[])
        self.web.setdefault('seconds_used',0); self.web.setdefault('rounds',0)
        self.web.setdefault('cache_hits',0)
        for record in self.web['queries'] + self.web['reads']:
            if record.get('status')=='started':
                record['status']='interrupted'
                if '上次联网请求被中断，已计入预算且不会重复派发' not in self.web['warnings']:
                    self.web['warnings'].append('上次联网请求被中断，已计入预算且不会重复派发')
        for record in self.web['reads']:
            if record['status'] == 'interrupted':
                for source in self.web['sources']:
                    if source['url'] == record['url']:
                        source['read_status'] = 'interrupted'
        self.save()
        with store.store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS companion_web_cache(key TEXT PRIMARY KEY, expires REAL NOT NULL, data TEXT NOT NULL)')

    def save(self):
        self.store.change('turns',self.turn_id,{'web':self.web})

    def event(self, event_type, title, payload=None):
        turn = self.store.get('turns',self.turn_id)
        self.store.emit(turn['session_id'],event_type,title,self.turn_id,payload)

    def warning(self, text):
        if text not in self.web['warnings']:
            self.web['warnings'].append(text)
        self.save()

    def cache(self, key, value=None):
        key = hashlib.sha256(encode(key).encode()).hexdigest()
        with self.store.store.connection() as db:
            if value is None:
                row = db.execute('SELECT data FROM companion_web_cache WHERE key=? AND expires>?',(key,time.time())).fetchone()
                return json.loads(row[0]) if row else None
            db.execute('DELETE FROM companion_web_cache WHERE expires<?',(time.time(),))
            db.execute('INSERT OR REPLACE INTO companion_web_cache VALUES(?,?,?)',(key,time.time()+max(0,self.settings.web_cache_seconds),encode(value)))
            db.execute('DELETE FROM companion_web_cache WHERE key NOT IN (SELECT key FROM companion_web_cache ORDER BY expires DESC LIMIT 200)')
            db.commit()

    async def call(self, function, cache_key, maximum):
        cached = self.cache(cache_key)
        if cached is not None:
            self.web['cache_hits'] += 1; self.save()
            self.event('web.cache_hit','复用近期已检索的公共资料')
            return cached
        turn = self.store.get('turns',self.turn_id)
        elapsed = turn['active_seconds'] + (time.time()-turn['clock_started'] if turn['clock_started'] else 0)
        remaining = min(self.settings.web_search_seconds-self.web['seconds_used'], turn.get('time_limit',self.settings.companion_seconds)-elapsed-12)
        if remaining < 2:
            raise ProviderError('联网时间预算已到，停止检索并保留已有资料')
        timeout = min(maximum,remaining)
        self.web['seconds_used'] += timeout; self.save()  # Reserve before dispatch; interruption never resets cost.
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(function(timeout),timeout)
        except asyncio.CancelledError:
            raise
        except TimeoutError as error:
            raise ProviderError('联网请求超时，已保留可用资料',retryable=True) from error
        finally:
            # On cancellation keep the full reservation for restart recovery.
            if not asyncio.current_task().cancelling():
                self.web['seconds_used'] -= max(0,timeout-(time.monotonic()-started)); self.save()
        result.setdefault('_retrieved_at',time.time())
        if result.get('results'):
            self.cache(cache_key,result)
        return result

    def add_source(self, item, parent=None):
        url = public_url(item.get('url'))
        if not url or any(s['url']==url for s in self.web['sources']):
            return
        if parent and sum(bool(s['parent_url']) for s in self.web['sources']) >= 8:
            return
        self.web['sources'].append({'id':f"W{len(self.web['sources'])+1:02}", 'url':url,
            'title':str(item.get('title') or urlsplit(url).hostname)[:220], 'host':urlsplit(url).hostname,
            'snippet':str(item.get('content') or '')[:2500], 'content':'', 'published_at':item.get('published_date'),
            'retrieved_at':item.get('_retrieved_at') or time.time(), 'read_status':'not_read', 'kind':'attachment' if '.pdf' in urlsplit(url).path.lower() else 'page',
            'parent_url':parent, 'score':float(item.get('score') or 0) if isinstance(item.get('score'),(int,float)) else 0})

    async def search_round(self, queries, args):
        for raw in queries[:2]:
            query = search_text(raw)
            if len(query)<2 or any(q['query']==query for q in self.web['queries']):
                continue
            if len(self.web['queries'])>=self.MAX_SEARCHES or self.web.get('fatal'):
                break
            record = {'query':query,'status':'started'}; self.web['queries'].append(record); self.save()
            self.event('web.search_started','正在搜索公共资料',{'query':query,'domains':domain_list(args.preferred_domains),'round':self.web['rounds']})
            try:
                body = await self.call(lambda timeout:self.provider.search(query,args,timeout), ['search',query,domain_list(args.preferred_domains),args.topic,args.time_range],8)
                for item in body.get('results',[])[:6]:
                    if isinstance(item,dict): self.add_source({**item,'_retrieved_at':body.get('_retrieved_at')})
                record['status']='completed'; self.save()
                self.event('web.search_completed','搜索结果已去重，准备筛选来源',{'sources':len(self.web['sources'])})
            except ProviderError as error:
                record['status']='failed'; self.web['fatal']=not error.retryable
                self.warning(str(error)); self.event('web.search_failed',str(error))

    def ranked(self, args):
        domains = domain_list(args.preferred_domains)
        selected = self.web.get('selected_ids', [])
        requested = self.web.get('review', {}).get('read_ids', [])
        def rank(source):
            signal = source.get('relevance', {})
            identifier = source['id']
            preferred = any(source['host']==d or source['host'].endswith('.'+d) for d in domains)
            return (identifier in selected, -selected.index(identifier) if identifier in selected else 0,
                    not signal.get('different_period',False),
                    signal.get('direct', False), identifier in requested,
                    -requested.index(identifier) if identifier in requested else 0,
                    signal.get('title_hits',0), signal.get('year_hint',0),
                    len(signal.get('matched', [])), signal.get('overlap',0), preferred, source['score'])
        return sorted(self.web['sources'],key=rank,reverse=True)

    async def read_sources(self, sources):
        known = {r['url'] for r in self.web['reads']}
        chosen = [s for s in sources if s['url'] not in known][:max(0,self.MAX_READS-len(known))]
        if not chosen or self.web.get('fatal'):
            return
        urls = [s['url'] for s in chosen]
        for s in chosen:
            self.web['reads'].append({'url':s['url'],'status':'started'})
        self.save(); self.event('web.read_started','正在读取网页或文件原文',{'urls':urls})
        try:
            body = await self.call(lambda timeout:self.provider.extract(urls,timeout), ['extract',sorted(urls)],14)
            results = {public_url(r.get('url')):r for r in body.get('results',[]) if isinstance(r,dict)}
            for s in chosen:
                result = results.get(s['url']) or {}
                raw = html.unescape(str(result.get('raw_content') or '')).strip()
                content = excerpt(raw, [self.question, s['title']], 24000)
                s.update(content=content,content_is_partial=len(content)<len(raw),read_status='read' if content else 'failed')
                if result.get('published_date'): s['published_at']=str(result['published_date'])[:80]
                if not content: self.warning('部分网页或附件未能读取原文，不能据摘要确认具体条款')
                else:
                    for label,link in re.findall(r'\[([^\]\n]{0,200})\]\(([^\s)]+)',raw):
                        attached = public_url(urljoin(s['url'],link))
                        if attached and urlsplit(attached).path.lower().endswith('.pdf'):
                            self.add_source({'url':attached,'title':(label or '原文附件')+' · '+s['title'],'score':s['score']},s['url'])
                next(r for r in self.web['reads'] if r['url']==s['url'])['status']=s['read_status']
            self.save(); self.event('web.read_completed','原文读取结束，保留成功与失败状态',{'read':sum(s['read_status']=='read' for s in self.web['sources'])})
        except ProviderError as error:
            for s in chosen:
                s['read_status']='failed'
                next(r for r in self.web['reads'] if r['url']==s['url'])['status']='failed'
            self.warning(str(error)); self.event('web.read_failed',str(error))

    def passages(self, sources, args):
        budget = self.settings.web_evidence_tokens
        focus = [self.question, args.purpose, *[c.quote for c in args.constraints]]
        result = []
        for index, source in enumerate(sources):
            text = source['content'] or source['snippet']
            if not text:
                continue
            item = {k:source[k] for k in self.PASSAGE_FIELDS}
            share = (budget - estimate_tokens(encode(result))) // (len(sources)-index)
            allowance = share - estimate_tokens(encode(item)) - 24
            if allowance < 64:
                continue
            passage = excerpt(text, focus, min(len(text), allowance*3))
            if estimate_tokens(passage) > allowance:
                passage = excerpt(text, focus, allowance)
            item.update(excerpt=passage, excerpt_is_partial=bool(source.get('content_is_partial') or len(passage)<len(text)))
            result.append(item)
        return result

    def evidence(self, args=None):
        args = args or WebSearchArgs.model_validate(self.web['tool_call']['args'])
        if 'verified_passages' in self.web:
            return self.web['verified_passages']
        eligible = set(self.web.get('selected_ids', []))
        return self.passages([s for s in self.ranked(args) if s['id'] in eligible], args)

    async def assess(self, args):
        sources = self.web['sources']
        for source in sources:
            source['relevance'] = relevance(source, self.question, args)
        signature = encode([self.web['rounds'], [(s['id'], s['read_status']) for s in sources]])
        if self.web.get('review_signature') == signature:
            return self.web['review']
        # Old selections must never control the order of a newly expanded catalog.
        self.web['selected_ids'] = []
        self.web['review'] = {}
        ordered = self.ranked(args)
        catalog = [{k:s[k] for k in ('id','url','title','parent_url','published_at','read_status')}
                   | {'snippet':s['snippet'][:320], 'matched':s['relevance']['matched'],
                      'unknown':s['relevance']['unknown']} for s in ordered]
        inspect = [s for s in ordered if s['read_status']=='read']
        passages = self.passages(inspect, args)
        payload = {'question':self.question,'purpose':args.purpose,'constraints':[c.model_dump() for c in args.constraints],
                   'require_original':args.require_original,'catalog':catalog,'sources':passages,
                   'round':self.web['rounds'],'remaining_reads':self.MAX_READS-len(self.web['reads']),
                   'searched_queries':[q['query'] for q in self.web['queries']]}
        self.event('web.assess_started','正在核对全部候选与已读证据',{'candidates':len(catalog),'passages':len(passages)})
        try:
            content = await self.invoke_model(WebReview, REVIEW_INSTRUCTION, payload, 1200, reserve=5000)
            review = WebReview.model_validate_json(content).model_dump()
        except (ProviderError,ValueError,TypeError):
            review = WebReview(sufficient=False,missing='未完成资料适用性核对').model_dump()
            review['selected_ids'] = [p['id'] for p in self.web.get('verified_passages',[])]
            review['unavailable'] = True
            self.warning('本次适用性核对未完成，保留此前已核实的依据及已发现的链接')
        by_id = {s['id']:s for s in sources}
        excluded = {i for i in review['excluded_ids'] if i in by_id}
        excluded.update(s['id'] for s in sources if s['relevance']['different_period'])
        by_passage = {p['id']:p for p in passages}
        if not args.require_original:
            for s in sources:
                if s['read_status'] != 'read' and s['snippet']:
                    by_passage[s['id']] = {k:s[k] for k in self.PASSAGE_FIELDS} | {
                        'excerpt':s['snippet'][:320], 'excerpt_is_partial':len(s['snippet'])>320}
        if review.get('unavailable'):
            by_passage.update({p['id']:p for p in self.web.get('verified_passages',[])})
        review['excluded_ids'] = sorted(excluded)
        review['selected_ids'] = list(dict.fromkeys(i for i in review['selected_ids'] if i in by_passage and i not in excluded))
        review['read_ids'] = list(dict.fromkeys(i for i in review['read_ids'] if i in by_id and i not in excluded
                                                 and by_id[i]['read_status']=='not_read'))
        review['sufficient'] = bool(review['sufficient'] and review['selected_ids'])
        approved = [by_passage[i] for i in review['selected_ids']]
        self.web.update(review=review,selected_ids=review['selected_ids'],review_signature=signature,
                        verified_passages=approved)
        self.save()
        return review

    def next_reads(self, args, review):
        attempted = {r['url'] for r in self.web['reads']}
        candidates = [s for s in self.ranked(args) if s['url'] not in attempted and
                      (s['id'] not in review['excluded_ids'] or s['relevance']['direct'])]
        direct = [s for s in candidates if s['relevance']['direct']]
        requested = [s for s in candidates if s['id'] in review['read_ids']]
        if review['sufficient']:
            if not args.require_original or any(s['relevance']['direct'] for s in self.web['sources'] if s['id'] in review['selected_ids']):
                return []
            return direct[:1]
        if review.get('unavailable'):
            return candidates[:1] if not attempted else []
        return (direct or requested)[:2]

    def finish(self, args, review):
        approved = set(review.get('selected_ids', []))
        attempted = {r['url']:r['status'] for r in self.web['reads']}
        for s in self.web['sources']:
            if s['id'] in approved:
                reason = '适用范围已核对，已选作回答依据'
            elif s['read_status'] in ('failed','interrupted'):
                reason = '原文读取中断' if s['read_status']=='interrupted' else '已尝试读取，未取得正文'
            elif s['id'] in review.get('excluded_ids',[]):
                reason = '文件标题标明的适用年度不同' if s['relevance']['different_period'] else '适用范围或正文与问题不符'
            elif s['url'] in attempted:
                reason = '已读取，尚无足够依据支持本次回答'
            elif s['id'] in review.get('read_ids',[]) and len(attempted)>=self.MAX_READS:
                reason = '精读名额已用完'
            elif review.get('sufficient'):
                reason = '已取得所需依据，停止精读'
            else:
                reason = '本轮未选入精读'
            s['decision_reason'] = reason
        if not self.web['sources']:
            self.web['status']='failed'
            self.warning('没有找到可引用来源；不代表相关规定或资料不存在')
        else:
            self.web['status']='complete' if review.get('sufficient') and not self.web['warnings'] else 'partial'
        self.web['evidence']=self.evidence(args)
        self.save()
        self.event('web.completed','联网检索已结束',{'status':self.web['status'],'searches':len(self.web['queries']),
                   'reads':len(attempted),'rounds':self.web['rounds'],'applicable_ids':list(self.web.get('selected_ids',[]))})
        return self.web

    async def run(self, **arguments):
        args = WebSearchArgs.model_validate(arguments)
        if self.web.get('status') in ('complete','partial','failed'):
            return self.web
        self.web['status']='searching'
        self.web['rounds']=max(1,self.web['rounds'])
        self.save()
        if self.web['rounds']==1:
            await self.search_round(args.queries,args)
        else:
            await self.search_round(self.web.get('followup_queries', (self.web.get('review') or {}).get('followup_queries', [])),args)
        review = {}
        while not self.web.get('fatal'):
            review = await self.assess(args)
            remaining = self.MAX_READS-len(self.web['reads'])
            next_batch = self.next_reads(args, review)
            fresh = [q for q in review['followup_queries'] if len(search_text(q))>=2 and
                     search_text(q) not in {item['query'] for item in self.web['queries']}]
            can_search = self.web['rounds']==1 and fresh and len(self.web['queries']) < self.MAX_SEARCHES
            # First batch uses at most two slots. Keep the last slot for a new batch
            # unless it can read an already-discovered direct target.
            slots = remaining
            if can_search and not any(s['relevance']['direct'] for s in next_batch):
                slots = max(0,remaining-1)
            if next_batch and slots:
                batch = next_batch[:slots]
                self.event('web.ranked','已选出本批优先精读来源',{'ids':[s['id'] for s in batch],
                           'catalog_size':len(self.web['sources']),'matched':[s['relevance']['matched'] for s in batch]})
                await self.read_sources(batch)
                continue
            if can_search and not review['sufficient'] and (remaining or not args.require_original):
                self.web.update(rounds=2,followup_queries=fresh)
                self.save()
                self.event('web.followup','针对未核实的条件补搜一次',{'missing':review['missing']})
                await self.search_round(fresh,args)
                continue
            break
        return self.finish(args, review)

    def as_tool(self):
        return StructuredTool.from_function(coroutine=self.run,name='web_search',description=WEB_TOOL_DESCRIPTION,args_schema=WebSearchArgs)
