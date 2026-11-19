"""Private evidence and approved public content have separate storage."""
import hashlib
import json
import re
import time
from .experience_models import ExperienceDocument
from .path_store import PathConflict
from .store import encode, uid

OUTCOME_LABELS = {'achieved':'达成目标', 'milestone':'完成阶段目标', 'changed':'调整方向',
                  'paused':'暂停探索', 'stopped':'结束尝试'}


def index_terms(value):
    tokens = set()
    for word in re.findall(r'[a-z0-9_+#.]+|[\u3400-\u9fff]+', value.casefold()):
        if word.isascii() or len(word)==1:
            tokens.add(word)
        else:
            tokens.update(word[i:i+2] for i in range(len(word)-1))
    return sorted(tokens)


def redact(value):
    value = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)', '［已隐藏］', value)
    value = re.sub(r'\b(?:sk-|tvly-)[A-Za-z0-9_-]+|(?<!\d)\d{17}[\dXx](?!\d)', '［已隐藏］', value)
    value = re.sub(r'(?i)([?&](?:token|access_token|api_key|signature|secret)=)[^\s&"]+', r'\1［已隐藏］',value)
    return re.sub(r'(?i)(api[_ -]?key|access[_ -]?secret|password|密码)\s*[:=：]\s*\S+', '［已隐藏］',value)


class ExperienceStore:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS experience_cases (
                    id TEXT PRIMARY KEY, path_id TEXT NOT NULL REFERENCES path_runs(id),
                    request_id TEXT NOT NULL, snapshot_key TEXT NOT NULL, data TEXT NOT NULL,
                    UNIQUE(path_id, request_id), UNIQUE(path_id, snapshot_key)
                );
                CREATE TABLE IF NOT EXISTS experience_public (
                    id TEXT PRIMARY KEY REFERENCES experience_cases(id), path_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, data TEXT NOT NULL, route_id TEXT NOT NULL,
                    UNIQUE(path_id,route_id)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS experience_fts USING fts5(case_id UNINDEXED, terms);
            """)
            if 'route_id' not in {r[1] for r in db.execute('PRAGMA table_info(experience_public)')}:
                # Upgrade early local drafts without discarding their consent or index.
                db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE experience_public_routes (
                        id TEXT PRIMARY KEY REFERENCES experience_cases(id), path_id TEXT NOT NULL,
                        revision INTEGER NOT NULL, data TEXT NOT NULL, route_id TEXT NOT NULL,
                        UNIQUE(path_id,route_id)
                    );
                    INSERT INTO experience_public_routes
                        SELECT id,path_id,revision,data,'legacy' FROM experience_public;
                    DROP TABLE experience_public;
                    ALTER TABLE experience_public_routes RENAME TO experience_public;
                """)
                rows=db.execute('SELECT p.id,c.data FROM experience_public p JOIN experience_cases c ON c.id=p.id').fetchall()
                for case_id,data in rows:
                    route_id=json.loads(data)['snapshot'].get('route_id','legacy')
                    db.execute('UPDATE experience_public SET route_id=? WHERE id=?',(route_id,case_id))
                db.commit()

    def get(self, case_id, db=None):
        if db is None:
            with self.store.connection() as conn:
                return self.get(case_id,conn)
        row = db.execute('SELECT data FROM experience_cases WHERE id=?',(case_id,)).fetchone()
        if row is None:
            raise KeyError(case_id)
        return json.loads(row[0])

    def update(self, case_id, callback):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            item = self.get(case_id,db)
            callback(item,db)
            db.execute('UPDATE experience_cases SET data=? WHERE id=?',(encode(item),case_id))
            db.commit()
        return item

    def list(self, path_id):
        with self.store.connection() as db:
            rows=db.execute('SELECT data FROM experience_cases WHERE path_id=? ORDER BY rowid DESC',(path_id,)).fetchall()
        return [self.preview(json.loads(r[0])) for r in rows]

    @staticmethod
    def preview(item):
        return {k:item.get(k) for k in ('id','path_id','status','outcome','revision','document','error',
                'created_at','updated_at','consented_at','tokens_used','phase','source_count','processed_batches')}

    def create(self, path_id, body, snapshot):
        snapshot_key=hashlib.sha256(encode(snapshot).encode()).hexdigest()
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM experience_cases WHERE path_id=? AND (request_id=? OR snapshot_key=?)',
                           (path_id,body.request_id,snapshot_key)).fetchone()
            if row:
                item=json.loads(row[0])
                if item['request_id']==body.request_id and item['finish']!=body.model_dump():
                    raise PathConflict('这次提交已保存，请刷新查看')
                return item,False
            now=time.time()
            item={'id':uid(),'path_id':path_id,'request_id':body.request_id,'snapshot_key':snapshot_key,
                  'finish':body.model_dump(),'snapshot':snapshot,'outcome':body.outcome,'status':'generating',
                  'revision':1,'document':None,'facts':[],'batches':{},'tokens_used':0,'seconds_used':0,
                  'created_at':now,'updated_at':now,'consented_at':None,'error':None,'phase':'正在整理经历时间线',
                  'source_count':len(snapshot['sources']),'processed_batches':0}
            db.execute('INSERT INTO experience_cases VALUES(?,?,?,?,?)',
                       (item['id'],path_id,body.request_id,snapshot_key,encode(item)))
            # Ending the journey and creating its review are one transaction.
            run=json.loads(db.execute('SELECT data FROM path_runs WHERE id=?',(path_id,)).fetchone()[0])
            if run['version']!=body.version or run['status']!='ready' or run['progress_revision']!=snapshot['progress_revision']:
                raise PathConflict('路径正在变化，请刷新后结束探索')
            run.update(journey_status='completed' if body.outcome in ('achieved','milestone') else 'ended',
                       journey_outcome=body.outcome,updated_at=now)
            db.execute('UPDATE path_runs SET data=? WHERE id=?',(encode(run),path_id))
            db.commit()
        return item,True

    def save_document(self, case_id, body):
        def save(item,db):
            self.check_edit(item,body.revision)
            item.update(document=body.document.model_dump(),revision=item['revision']+1,updated_at=time.time())
            self.unpublish(item,db)
            item['status']='draft'
        return self.preview(self.update(case_id,save))

    @staticmethod
    def check_edit(item, revision):
        if item['revision']!=revision:
            raise PathConflict('案例已更新，请刷新后再操作')
        if item['status']=='generating' or not item['document']:
            raise PathConflict('请等待案例草稿生成完成')

    @staticmethod
    def unpublish(item,db):
        db.execute('DELETE FROM experience_fts WHERE case_id=?',(item['id'],))
        db.execute('DELETE FROM experience_public WHERE id=?',(item['id'],))
        item['consented_at']=None

    def publish(self,case_id,revision):
        def publish(item,db):
            self.check_edit(item,revision)
            doc=ExperienceDocument.model_validate(item['document']).model_dump()
            if not doc['fields'].get('actions','').strip():
                raise PathConflict('请补充实际采取的行动，再分享经历')
            if not doc['fields'].get('stage_outcomes','').strip():
                raise PathConflict('请补充实际结果或当前状态，再分享经历')
            serialized=encode(doc)
            if redact(serialized)!=serialized:
                raise PathConflict('草稿含联系方式或凭证，请删除后再分享')
            # A new review of the same journey replaces its previously shared version.
            route_id=item['snapshot'].get('route_id','legacy')
            old=db.execute('SELECT id FROM experience_public WHERE path_id=? AND route_id=?',
                           (item['path_id'],route_id)).fetchone()
            if old and old[0]!=item['id']:
                previous=self.get(old[0],db)
                self.unpublish(previous,db)
                previous.update(status='draft',revision=previous['revision']+1)
                db.execute('UPDATE experience_cases SET data=? WHERE id=?',(encode(previous),previous['id']))
            self.unpublish(item,db)
            now=time.time()
            item.update(status='shared',consented_at=now,updated_at=now)
            public={'id':item['id'],'revision':item['revision'],'outcome':item['outcome'],
                    'document':doc,'shared_at':now,'evidence_basis':'用户审阅确认的匿名自述'}
            db.execute('INSERT INTO experience_public(id,path_id,revision,data,route_id) VALUES(?,?,?,?,?)',
                       (item['id'],item['path_id'],item['revision'],encode(public),route_id))
            db.execute('INSERT INTO experience_fts VALUES(?,?)',
                       (item['id'],' '.join(index_terms(serialized))))
        return self.preview(self.update(case_id,publish))

    def withdraw(self,case_id):
        def withdraw(item,db):
            self.unpublish(item,db)
            item.update(status='draft' if item['document'] else item['status'],
                        revision=item['revision']+1,updated_at=time.time())
        return self.preview(self.update(case_id,withdraw))

    def public(self,case_id):
        with self.store.connection() as db:
            row=db.execute('SELECT data FROM experience_public WHERE id=?',(case_id,)).fetchone()
        if not row:
            raise KeyError(case_id)
        return json.loads(row[0])

    def search(self,profile,exclude_path=None,limit=6):
        anchors=[]
        for name in ('major','education','target','starting_point'):
            anchors.append((profile.get(name) or {}).get('value',''))
        anchors.extend(f['value'] for f in profile.get('planned_actions',[]))
        tokens=index_terms(' '.join(anchors))[:60]
        if not tokens:
            return []
        query=' OR '.join('"'+t.replace('"','""')+'"' for t in tokens)
        with self.store.connection() as db:
            rows=db.execute("""SELECT p.data FROM experience_fts f JOIN experience_public p ON p.id=f.case_id
                WHERE experience_fts MATCH ? AND p.path_id!=?
                ORDER BY bm25(experience_fts) LIMIT ?""",(query,exclude_path or '',limit)).fetchall()
        return [json.loads(r[0]) for r in rows]
