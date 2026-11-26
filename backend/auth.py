"""Accounts, opaque sessions, encrypted per-user credentials and resource ownership."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import unicodedata
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from .store import encode, uid

COOKIE_NAME='lifelab_session'
current_user=ContextVar('lifelab_user',default=None)
model_owner=ContextVar('lifelab_model_owner',default=None)
SESSION_SECONDS=7*24*3600


def password_hash(password, salt=None):
    salt=salt or secrets.token_bytes(16)
    derived=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000)
    return 'pbkdf2_sha256$600000$'+base64.b64encode(salt).decode()+'$'+base64.b64encode(derived).decode()


def verify_password(password,encoded):
    try:
        _,_,salt,_=encoded.split('$')
        return hmac.compare_digest(password_hash(password,base64.b64decode(salt)),encoded)
    except (ValueError,TypeError):
        return False


def username_key(username):
    return unicodedata.normalize('NFKC',username.strip()).casefold()


class AuthStore:
    def __init__(self,store,platform_key=None):
        self.store=store
        self.platform_key=platform_key or (lambda: '')
        self.fernet=Fernet(self.encryption_key())
        with store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,username TEXT NOT NULL,username_key TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('user','admin','superadmin')),
                    created_at REAL NOT NULL,model_key TEXT,key_suffix TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_superadmin ON users(role) WHERE role='superadmin';
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_login_attempts (
                    subject TEXT PRIMARY KEY,count INTEGER NOT NULL,expires REAL NOT NULL
                );
            """)
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT id FROM users WHERE role='superadmin'").fetchone()
            if row is None:
                identifier=uid()
                db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,NULL,NULL)',
                           (identifier,'ailifelab','ailifelab',password_hash('66666666'),'superadmin',time.time()))
            else:
                identifier=row[0]
            self.master_id=identifier
            for _,data in db.execute('SELECT id,data FROM runs').fetchall():
                run=json.loads(data)
                if not run.get('owner_id'):
                    run['owner_id']=identifier
                    db.execute('UPDATE runs SET data=? WHERE id=?',(encode(run),run['id']))
            db.commit()
        store.default_owner_id=self.master_id
        self.dummy_hash=password_hash(secrets.token_urlsafe(24))

    def encryption_key(self):
        path=self.store.path.parent/'auth.key'
        try:
            with path.open('rb') as file:
                return file.read()
        except FileNotFoundError:
            key=Fernet.generate_key()
            try:
                descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            except FileExistsError:
                return path.read_bytes()
            with os.fdopen(descriptor,'wb') as file:
                file.write(key)
            return key

    def user(self,user_id):
        with self.store.connection() as db:
            row=db.execute('SELECT id,username,role,created_at,model_key,key_suffix FROM users WHERE id=?',(user_id,)).fetchone()
        if not row:
            raise HTTPException(401,'请重新登录')
        source='personal' if row[4] else 'platform' if row[2] in ('admin','superadmin') and self.platform_key().strip() else None
        return {'id':row[0],'username':row[1],'role':row[2],'created_at':row[3],
                'has_api_key':bool(row[4]),'key_suffix':row[5],
                'model_key_source':source,'model_configured':source is not None}

    def register(self,username,password,role,invitation):
        normalized=unicodedata.normalize('NFKC',username.strip())
        key=username_key(normalized)
        if not re.fullmatch(r'[\w.-]{3,32}',normalized) or key=='ailifelab':
            raise HTTPException(422,'用户名需为3至32位字母、数字、汉字、下划线或点，且不能使用保留账号')
        if role=='admin' and not hmac.compare_digest(invitation.encode(),'lbrnb666'.encode()):
            raise HTTPException(403,'管理员邀请码不正确')
        identifier=uid()
        try:
            with self.store.connection() as db:
                db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,NULL,NULL)',
                           (identifier,normalized,key,password_hash(password),role,time.time()))
                db.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(409,'用户名已注册')
        return self.user(identifier)

    def login(self,username,password):
        key=username_key(username)
        subject=hashlib.sha256(key.encode()).hexdigest()
        with self.store.connection() as db:
            attempt=db.execute('SELECT count,expires FROM auth_login_attempts WHERE subject=?',(subject,)).fetchone()
            if attempt and attempt[1]>time.time() and attempt[0]>=10:
                raise HTTPException(429,'尝试次数较多，请稍后再登录')
            row=db.execute('SELECT id,password_hash FROM users WHERE username_key=?',(key,)).fetchone()
        valid=verify_password(password,row[1] if row else self.dummy_hash)
        if not row or not valid:
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                now=time.time()
                attempt=db.execute('SELECT count,expires FROM auth_login_attempts WHERE subject=?',(subject,)).fetchone()
                count=attempt[0]+1 if attempt and attempt[1]>now else 1
                expires=attempt[1] if attempt and attempt[1]>now else now+300
                db.execute('INSERT OR REPLACE INTO auth_login_attempts VALUES(?,?,?)',(subject,count,expires))
                db.commit()
            raise HTTPException(401,'用户名或密码错误')
        with self.store.connection() as db:
            db.execute('DELETE FROM auth_login_attempts WHERE subject=?',(subject,))
            db.commit()
        return self.user(row[0])

    def new_session(self,user_id):
        token=secrets.token_urlsafe(32)
        with self.store.connection() as db:
            db.execute('DELETE FROM auth_sessions WHERE expires<=?',(time.time(),))
            db.execute('INSERT INTO auth_sessions VALUES(?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(),user_id,time.time()+SESSION_SECONDS))
            db.commit()
        return token

    def authenticate(self,token):
        if not token or len(token)>128:
            return None
        with self.store.connection() as db:
            row=db.execute('SELECT user_id FROM auth_sessions WHERE token_hash=? AND expires>?',
                           (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        return self.user(row[0]) if row else None

    def logout(self,token):
        if token:
            with self.store.connection() as db:
                db.execute('DELETE FROM auth_sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
                db.commit()

    def set_key(self,user_id,key):
        encrypted=self.fernet.encrypt(key.encode()).decode() if key else None
        with self.store.connection() as db:
            db.execute('UPDATE users SET model_key=?,key_suffix=? WHERE id=?',
                       (encrypted,key[-4:] if key else None,user_id))
            db.commit()
        return self.user(user_id)

    def api_key(self,user_id):
        with self.store.connection() as db:
            row=db.execute('SELECT model_key,role FROM users WHERE id=?',(user_id,)).fetchone()
        if row and not row[0] and row[1] in ('admin','superadmin'):
            key=self.platform_key().strip()
            if key:
                return key
            raise HTTPException(409,'请在服务端 .env 配置 DEEPSEEK_API_KEY，或在模型设置中填写个人 API Key')
        if not row or not row[0]:
            raise HTTPException(409,'请先在模型设置中填写自己的 DeepSeek API Key')
        try:
            return self.fernet.decrypt(row[0].encode()).decode()
        except InvalidToken:
            raise HTTPException(409,'模型密钥无法解密，请在模型设置中重新保存')

    def owner_for_run(self,run_id):
        return self.store.get(run_id).get('owner_id') or self.master_id

    def owner_for_path(self,path_id):
        with self.store.connection() as db:
            row=db.execute('SELECT retrieval_run_id FROM path_runs WHERE id=?',(path_id,)).fetchone()
        if not row:
            raise KeyError(path_id)
        return self.owner_for_run(row[0])

    def resource_owner(self,path):
        parts=path.strip('/').split('/')
        if len(parts)<3:
            return None
        kind,identifier=parts[1:3]
        if kind=='runs':
            return self.owner_for_run(identifier)
        if kind=='paths':
            return self.owner_for_path(identifier)
        tables={'experiences':'experience_cases'}
        if kind=='companion' and len(parts)>=4:
            kind,identifier=parts[2:4]
            tables={'sessions':'companion_sessions','turns':'companion_turns',
                    'actions':'companion_actions','memories':'companion_memories'}
        table=tables.get(kind)
        if table:
            with self.store.connection() as db:
                row=db.execute(f'SELECT data FROM {table} WHERE id=?',(identifier,)).fetchone()
            if not row:
                raise KeyError(identifier)
            scope_id = json.loads(row[0])['path_id']
            if table.startswith('companion_'):
                with self.store.connection() as db:
                    scope = db.execute('SELECT owner_id,path_id FROM companion_scopes WHERE id=?',(scope_id,)).fetchone()
                if scope and scope[1] is None:
                    return scope[0]
            return self.owner_for_path(scope_id)
        return None

    def assert_access(self,path,user):
        if path.startswith('/api/admin/'):
            if user['role'] not in ('admin','superadmin'):
                raise HTTPException(403,'需要管理员权限')
            return
        try:
            owner=self.resource_owner(path)
        except KeyError:
            raise HTTPException(404,'记录不存在')
        if owner and owner!=user['id']:
            raise HTTPException(404,'记录不存在')

    def admin_overview(self,search='',page=1):
        today=datetime.now(timezone(timedelta(hours=8))).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        with self.store.connection() as db:
            total=db.execute('SELECT count(*) FROM users').fetchone()[0]
            admins=db.execute("SELECT count(*) FROM users WHERE role IN ('admin','superadmin')").fetchone()[0]
            new=db.execute('SELECT count(*) FROM users WHERE created_at>=?',(today,)).fetchone()[0]
            pattern='%'+search.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            matched=db.execute("SELECT count(*) FROM users WHERE username LIKE ? ESCAPE ?",(pattern,chr(92))).fetchone()[0]
            users=db.execute("""SELECT id,username,role,created_at FROM users
                WHERE username LIKE ? ESCAPE ? ORDER BY created_at DESC LIMIT 20 OFFSET ?""",
                (pattern,chr(92),(page-1)*20)).fetchall()
        return {'stats':{'users':total,'ordinary':total-admins,'admins':admins,'today':new},
                'total':matched,'page':page,'users':[dict(zip(('id','username','role','created_at'),r)) for r in users]}

    def admin_reviews(self,user_id,page=1):
        self.user(user_id)
        with self.store.connection() as db:
            rows=db.execute("""SELECT e.data FROM experience_cases e
                JOIN path_runs p ON p.id=e.path_id JOIN runs r ON r.id=p.retrieval_run_id
                WHERE json_extract(r.data,'$.owner_id')=? ORDER BY e.rowid DESC""",(user_id,)).fetchall()
        items=[]
        for row in rows:
            item=json.loads(row[0])
            if item['status'] not in ('draft','shared') or not item.get('document'):
                continue
            items.append({k:item.get(k) for k in ('id','outcome','status','created_at','updated_at','document')})
        return {'total':len(items),'page':page,'reviews':items[(page-1)*20:page*20]}
