"""SQLite 对话与操作日志；与路径进度共用事务连接。"""
import json
import time
from .store import encode, uid
from .path_store import PathConflict

class CompanionStore:
    def __init__(self, paths):
        self.paths = paths
        self.web_configured = False
        self.store = paths.store
        with self.store.connection() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS companion_sessions(id TEXT PRIMARY KEY, path_id TEXT UNIQUE NOT NULL REFERENCES path_runs(id), data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS companion_turns(ordinal INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, session_id TEXT NOT NULL REFERENCES companion_sessions(id), client_id TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(session_id, client_id));
              CREATE TABLE IF NOT EXISTS companion_actions(id TEXT PRIMARY KEY, turn_id TEXT NOT NULL REFERENCES companion_turns(id), data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS companion_memories(id TEXT PRIMARY KEY, path_id TEXT NOT NULL REFERENCES path_runs(id), data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS companion_events(session_id TEXT NOT NULL REFERENCES companion_sessions(id), sequence INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(session_id, sequence));
            ''')

    def get(self, table, identifier, db=None):
        if db is None:
            with self.store.connection() as conn:
                return self.get(table, identifier, conn)
        assert table in ('sessions', 'turns', 'actions', 'memories')
        row = db.execute(f'SELECT data FROM companion_{table} WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        return json.loads(row[0])

    def put(self, table, value, db):
        assert table in ('sessions', 'turns', 'actions', 'memories')
        db.execute(f'UPDATE companion_{table} SET data=? WHERE id=?', (encode(value), value['id']))

    def transaction(self, callback):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            result = callback(db)
            db.commit()
            return result

    def change(self, table, identifier, changes):
        def update(db):
            item = self.get(table, identifier, db)
            item.update(changes)
            self.put(table, item, db)
            return item
        return self.transaction(update)

    def session(self, path_id):
        self.paths.get(path_id)
        def create(db):
            row = db.execute('SELECT data FROM companion_sessions WHERE path_id=?', (path_id,)).fetchone()
            if row:
                return json.loads(row[0])
            item = {'id': uid(), 'path_id': path_id, 'created_at': time.time(), 'sequence': 0,
                    'summary': '', 'summary_ordinal': 0, 'context_revision': 0, 'forgotten_turns': [], 'mode': 'auto'}
            db.execute('INSERT INTO companion_sessions VALUES(?,?,?)', (item['id'], path_id, encode(item)))
            return item
        return self.transaction(create)

    def turns(self, session_id, *, before=None, limit=40):
        with self.store.connection() as db:
            rows = db.execute('SELECT ordinal,data FROM companion_turns WHERE session_id=? AND ordinal<? ORDER BY ordinal DESC LIMIT ?',
                              (session_id, before or 2**63-1, limit+1)).fetchall()
        return {'turns': [{**json.loads(data), 'ordinal': ordinal} for ordinal, data in reversed(rows[:limit])],
                'has_older': len(rows) > limit, 'oldest_cursor': rows[min(limit, len(rows))-1][0] if rows else None}

    def actions(self, turn_id):
        with self.store.connection() as db:
            rows = db.execute('SELECT data FROM companion_actions WHERE turn_id=? ORDER BY rowid', (turn_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def memories(self, path_id, db=None):
        if db is None:
            with self.store.connection() as conn:
                return self.memories(path_id, conn)
        return [json.loads(row[0]) for row in db.execute('SELECT data FROM companion_memories WHERE path_id=? ORDER BY rowid DESC', (path_id,))]

    def emit(self, session_id, event_type, title, turn_id=None, payload=None, db=None):
        if db is None:
            return self.transaction(lambda conn: self.emit(session_id, event_type, title, turn_id, payload, conn))
        session = self.get('sessions', session_id, db)
        session['sequence'] += 1
        event = {'sequence': session['sequence'], 'agent': 'companion', 'event_type': event_type,
                 'title': title, 'turn_id': turn_id, 'occurred_at': time.time(), 'payload': payload or {}}
        db.execute('INSERT INTO companion_events VALUES(?,?,?)', (session_id, event['sequence'], encode(event)))
        self.put('sessions', session, db)

    def events(self, session_id, after=0):
        with self.store.connection() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT data FROM companion_events WHERE session_id=? AND sequence>? ORDER BY sequence LIMIT 200', (session_id, after))]

    def new_turn(self, session_id, body, token_limit):
        def create(db):
            old = db.execute('SELECT data FROM companion_turns WHERE session_id=? AND client_id=?', (session_id, body.client_message_id)).fetchone()
            if old:
                item = json.loads(old[0])
                if {'web_search':'auto', **item['input']} != body.model_dump():
                    raise PathConflict('这条消息已提交，重试请使用相同内容')
                return item, False
            session = self.get('sessions', session_id, db)
            rows = db.execute('SELECT data FROM companion_turns WHERE session_id=?', (session_id,)).fetchall()
            if any(json.loads(row[0])['status'] == 'running' for row in rows):
                raise PathConflict('伙伴正在回复上一条消息，请稍等片刻')
            item = {'id': uid(), 'session_id': session_id, 'path_id': session['path_id'], 'input': body.model_dump(),
                    'created_at': time.time(), 'status': 'running', 'reply': None, 'model_result': None,
                    'tokens_used': 0, 'token_limit': token_limit, 'estimated_usage': False, 'calls': [],
                    'active_seconds': 0, 'clock_started': time.time(), 'context_revision': session['context_revision'],
                    'path_version': None, 'progress_revision': None, 'error': None, 'decisions': {}}
            db.execute('INSERT INTO companion_turns(id,session_id,client_id,data) VALUES(?,?,?,?)', (item['id'], session_id, body.client_message_id, encode(item)))
            session['mode'] = body.mode
            self.put('sessions', session, db)
            self.emit(session_id, 'turn.started', '正在读取你的当前任务与近期对话', item['id'], db=db)
            return item, True
        return self.transaction(create)

    def publish(self, turn_id, reply, actions):
        def publish(db):
            turn = self.get('turns', turn_id, db)
            if turn['reply'] is not None:
                return
            session = self.get('sessions', turn['session_id'], db)
            if session['context_revision'] != turn['context_revision']:
                raise PathConflict('记忆已更新，请重试以使用最新信息')
            turn.update(reply=reply, status='awaiting_actions' if actions else 'completed')
            self.put('turns', turn, db)
            for action in actions:
                db.execute('INSERT OR IGNORE INTO companion_actions VALUES(?,?,?)', (action['id'], turn_id, encode(action)))
            ordinal = db.execute('SELECT ordinal FROM companion_turns WHERE id=?', (turn_id,)).fetchone()[0]
            if ordinal > session['summary_ordinal']:
                # Quote-based rollup avoids turning inferred feelings into permanent facts.
                session['summary'] = (session['summary'] + '\n用户原话：' + turn['input']['text'][:280] + '\n助手建议（非完成事实）：' + reply['message'][:180])[-1400:]
                session['summary_ordinal'] = ordinal
                self.put('sessions', session, db)
            self.emit(turn['session_id'], 'message.completed', '回应已保存', turn_id, db=db)
        self.transaction(publish)

    def public_turn(self, turn):
        result = {key: value for key, value in turn.items() if key not in ('model_result', 'calls', 'decisions', 'clock_started', 'web', 'answer_web_evidence', 'answer_web_inventory')}
        web = turn.get('web') or {}
        supplied = {s['id'] for s in turn.get('answer_web_evidence',[])}
        cited = {s['source_id'] for s in (turn.get('reply') or {}).get('web_citations',[])}
        result['web'] = {'status':web.get('status','pending' if turn['status']=='running' else 'skipped'),
            'warnings':web.get('warnings',[]),'queries':web.get('queries',[]),'rounds':web.get('rounds',0),
            'reads':len(web.get('reads',[])),'cache_hits':web.get('cache_hits',0),
            'sources':[{k:s[k] for k in ('id','title','url','host','published_at','retrieved_at','read_status','kind','parent_url')}
                | {'in_answer_context':s['id'] in supplied,'is_cited':s['id'] in cited,
                   'decision_reason':s.get('decision_reason'),'matched':s.get('relevance',{}).get('matched',[])}
                for s in web.get('sources',[])]}
        return result | {'actions': self.actions(turn['id'])}

    def snapshot(self, session_id, before=None):
        session = self.get('sessions', session_id)
        page = self.turns(session_id, before=before)
        return {'session': {key: session[key] for key in ('id', 'path_id', 'mode', 'sequence')},
                **page, 'turns': [self.public_turn(turn) for turn in page['turns']], 'memories': self.memories(session['path_id']),
                'capabilities':{'web_search':self.web_configured,'provider':'tavily'}}

    def active(self):
        with self.store.connection() as db:
            return [item for row in db.execute('SELECT data FROM companion_turns') if (item := json.loads(row[0]))['status'] == 'running']

    def edit_memory(self, memory_id, value=None):
        def edit(db):
            memory = self.get('memories', memory_id, db)
            session = json.loads(db.execute('SELECT data FROM companion_sessions WHERE path_id=?', (memory['path_id'],)).fetchone()[0])
            session['summary'] = ''
            session['context_revision'] += 1
            session['forgotten_turns'] = list(dict.fromkeys([*session['forgotten_turns'], memory['source_turn_id']]))
            self.put('sessions', session, db)
            if value is None:
                db.execute('DELETE FROM companion_memories WHERE id=?', (memory_id,))
            else:
                memory.update(value=value.strip(), edited_by_user=True, updated_at=time.time())
                if not memory['value']:
                    raise PathConflict('记忆内容不能为空')
                self.put('memories', memory, db)
            self.emit(session['id'], 'memory.changed', '个人记忆已更新，后续对话会使用新信息', db=db)
        self.transaction(edit)
