from __future__ import annotations
import hashlib, ipaddress, json, os, secrets, socket, sqlite3, time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from cryptography.fernet import Fernet

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('CAREERFLOW_DATA',ROOT/'data')).resolve()
DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'careerflow.sqlite'
def now(): return time.time()
def uid(): return secrets.token_hex(12)
def digest(v): return hashlib.sha256((v if isinstance(v,bytes) else str(v).encode())).hexdigest()
def dump(v): return json.dumps(v,ensure_ascii=False,separators=(',',':'))
def load(v): return json.loads(v) if v else {}

@contextmanager
def db():
 c=sqlite3.connect(DB,timeout=20);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=20000')
 try: yield c; c.commit()
 except Exception:c.rollback();raise
 finally:c.close()

def init():
 with db() as c:
  c.execute('PRAGMA journal_mode=WAL')
  c.executescript('''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,name TEXT,password TEXT,salt TEXT,created REAL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,owner TEXT,expires REAL);
CREATE TABLE IF NOT EXISTS profiles(owner TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS secrets(owner TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,owner TEXT NOT NULL,data TEXT NOT NULL,enabled INTEGER DEFAULT 0,next_run REAL DEFAULT 0,last_run REAL DEFAULT 0,last_result TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,owner TEXT NOT NULL,canonical TEXT NOT NULL,data TEXT NOT NULL,updated REAL,UNIQUE(owner,canonical));
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,owner TEXT NOT NULL,kind TEXT NOT NULL,state TEXT NOT NULL,data TEXT,result TEXT DEFAULT '{}',error TEXT DEFAULT '',created REAL,updated REAL);
CREATE TABLE IF NOT EXISTS resumes(id TEXT PRIMARY KEY,owner TEXT NOT NULL,job_id TEXT NOT NULL,data TEXT NOT NULL,created REAL);
CREATE TABLE IF NOT EXISTS applications(id TEXT PRIMARY KEY,owner TEXT NOT NULL,job_id TEXT NOT NULL,resume_id TEXT NOT NULL,state TEXT NOT NULL,data TEXT NOT NULL,created REAL,updated REAL,UNIQUE(owner,job_id));
CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,owner TEXT NOT NULL,mail_key TEXT NOT NULL,application_id TEXT,data TEXT NOT NULL,created REAL,UNIQUE(owner,mail_key));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,owner TEXT,kind TEXT,object_id TEXT,data TEXT,created REAL);
CREATE TABLE IF NOT EXISTS snapshots(owner TEXT,canonical TEXT,hash TEXT,data TEXT,created REAL,UNIQUE(owner,canonical,hash));
CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner,updated);
CREATE INDEX IF NOT EXISTS tasks_queue ON tasks(state,created);
''')
 if not (DATA/'vault.key').exists():
  try:
   fd=os.open(DATA/'vault.key',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
   with os.fdopen(fd,'wb') as f:f.write(Fernet.generate_key())
  except FileExistsError:pass

def password_hash(password,salt): return hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),240000).hex()
def vault(): return Fernet((DATA/'vault.key').read_bytes())
def get_settings(owner):
 with db() as c:r=c.execute('SELECT data FROM secrets WHERE owner=?',(owner,)).fetchone()
 return load(vault().decrypt(r['data'].encode()).decode()) if r else {}
def save_settings(owner,data):
 with db() as c:c.execute('INSERT INTO secrets VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET data=excluded.data',(owner,vault().encrypt(dump(data).encode()).decode()))
def get_profile(owner):
 with db() as c:r=c.execute('SELECT data FROM profiles WHERE owner=?',(owner,)).fetchone()
 return load(r['data']) if r else {}
def event(owner,kind,obj,data=None):
 with db() as c:c.execute('INSERT INTO events(owner,kind,object_id,data,created) VALUES(?,?,?,?,?)',(owner,kind,obj,dump(data or {}),now()))
def owned(table,id,owner):
 if table not in {'jobs','sources','resumes','applications','tasks','messages'}:raise ValueError('无效资源')
 with db() as c:r=c.execute(f'SELECT * FROM {table} WHERE id=? AND owner=?',(id,owner)).fetchone()
 if not r:raise LookupError('资源不存在或不属于当前账号')
 d=dict(r)
 for key in ('data','result','last_result'):
  if key in d:d[key]=load(d[key])
 return d
def enqueue(owner,kind,data):
 id=uid()
 with db() as c:c.execute('INSERT INTO tasks(id,owner,kind,state,data,created,updated) VALUES(?,?,?,?,?,?,?)',(id,owner,kind,'queued',dump(data),now(),now()))
 return id

def public_url(url):
 p=urlsplit(url)
 if len(url)>3000 or p.scheme not in {'https','http'} or not p.hostname or p.username or p.password:raise ValueError('只允许公开HTTP/HTTPS网址')
 if p.port and p.port not in {80,443}:raise ValueError('只允许标准网页端口')
 public_host(p.hostname)
 return url
def public_host(host):
 if host.lower() in {'localhost','metadata.google.internal'} or host.lower().endswith(('.localhost','.local','.internal')):raise ValueError('不允许本机或内网地址')
 try:answers=socket.getaddrinfo(host,None,proto=socket.IPPROTO_TCP)
 except OSError:raise ValueError('域名暂时无法解析') from None
 if not answers or any(not ipaddress.ip_address(a[4][0]).is_global for a in answers):raise ValueError('不允许内网、保留或回环地址')
 return host

def normalize_profile(p):
 allowed={'name','email','phone','headline','education','school','major','graduation','experience_years','skills','languages','locations','roles','employment','salary','availability','facts','portfolio','work_authorization','certificates'}
 if not isinstance(p,dict):raise ValueError('档案格式错误')
 p={k:v for k,v in p.items() if k in allowed}
 if len(dump(p))>80000:raise ValueError('档案过大')
 for k in ['name','email','phone','headline','education','school','major','graduation','salary','availability','portfolio']:
  p[k]=str(p.get(k,'')).strip()[:2000]
 for k in ['skills','languages','locations','roles','employment','work_authorization','certificates']:
  vals=p.get(k,[])
  if isinstance(vals,str):vals=[x.strip() for x in vals.replace('，',',').split(',')]
  p[k]=[str(x)[:100] for x in vals if str(x).strip()][:80]
 p['experience_years']=max(0,min(70,float(p.get('experience_years',0) or 0)))
 facts=[]
 for f in p.get('facts',[])[:80]:
  if not isinstance(f,dict):continue
  facts.append({k:str(f.get(k,''))[:(4000 if k=='text' else 400)] for k in ('id','kind','title','org','dates','text','tags','evidence')}|{'verified':f.get('verified') is True})
 for f in facts:
  if not f['id']:f['id']=uid()
 p['facts']=facts
 return p
