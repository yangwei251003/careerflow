from __future__ import annotations
import asyncio,contextlib,json,os,re,secrets,sqlite3,time
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI,Request,Response,HTTPException,Depends,UploadFile,File
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .core import *
from .catalog import CATALOG,PLATFORMS
from .sources import request as fetch,jobbase,text,jsonld_jobs,store_jobs,canonical,job_fingerprint
from .matching import match
from .resumes import build_resume,ai_advice,interview_pack
from .mail import prepare_application,update_state,send_application,send_self_test
from . import worker
from .imports import preview_resume,MAX_FILE
from .exports import resume_archive,application_csv
from .local_models import validate_local,local_chat,status as local_status,BASE as LOCAL_BASE,DEFAULT_MODEL

@contextlib.asynccontextmanager
async def lifespan(app):
 init();thread=worker.start() if os.environ.get('CAREERFLOW_NO_WORKER')!='1' else None
 yield
 worker.STOP.set()

app=FastAPI(title='CareerFlow API',version='0.1.0',lifespan=lifespan)
allowed=os.environ.get('CAREERFLOW_ALLOWED_HOSTS','127.0.0.1,localhost,testserver').split(',')
app.add_middleware(TrustedHostMiddleware,allowed_hosts=allowed)
rate={}
@app.middleware('http')
async def guard(req,call_next):
 if req.url.path.startswith('/api/') and req.method in {'POST','PUT','PATCH','DELETE'}:
  if req.headers.get('x-careerflow')!='1':return JSONResponse({'detail':'请从职航页面发起操作'},status_code=403)
  origin=req.headers.get('origin')
  if origin and urlsplit(origin).netloc!=req.headers.get('host'):return JSONResponse({'detail':'来源校验失败'},status_code=403)
  maximum=MAX_FILE+100_000 if req.url.path=='/api/profile/import-preview' else 1_000_000
  try:length=int(req.headers.get('content-length','0'))
  except ValueError:return JSONResponse({'detail':'请求长度格式无效'},status_code=400)
  if length>maximum:return JSONResponse({'detail':'请求内容过大'},status_code=413)
 response=await call_next(req)
 response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='no-referrer'
 response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
 if req.url.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
 return response

@app.exception_handler(ValueError)
async def value_error(req,e):return JSONResponse({'detail':str(e)[:400]},status_code=400)
@app.exception_handler(LookupError)
async def lookup_error(req,e):return JSONResponse({'detail':'资源不存在'},status_code=404)

def user(req:Request):
 token=req.cookies.get('cf_session','')
 with db() as c:r=c.execute('SELECT u.id,u.name,u.email FROM sessions s JOIN users u ON u.id=s.owner WHERE s.token=? AND s.expires>?',(digest(token),now())).fetchone()
 if not r:raise HTTPException(401,'请先登录')
 return dict(r)
def session(response,owner):
 token=secrets.token_urlsafe(32)
 with db() as c:c.execute('INSERT INTO sessions VALUES(?,?,?)',(digest(token),owner,now()+86400*7))
 response.set_cookie('cf_session',token,httponly=True,samesite='strict',secure=os.environ.get('CAREERFLOW_HTTPS')=='1',max_age=604800)

@app.get('/api/health')
def health():return {'ok':True,'version':'0.1.1','mode':'本机完整应用','external_submission':'仅已授权邮箱；平台内自动投递未接通'}
@app.post('/api/auth/{action}')
def auth(action:str,p:dict,response:Response,req:Request):
 ip=req.client.host if req.client else 'local';attempts=[t for t in rate.get(ip,[]) if t>now()-60];rate[ip]=attempts+[now()]
 if len(attempts)>=15:raise HTTPException(429,'请求过多，请稍后再试')
 email=str(p.get('email','')).strip().lower();password=str(p.get('password',''))
 if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or len(email)>250 or len(password)>200:raise ValueError('邮箱或密码格式无效')
 if action=='register':
  if len(password)<10:raise ValueError('密码至少10位')
  id=uid();salt=secrets.token_hex(16);name=str(p.get('name','求职者'))[:80]
  try:
   with db() as c:c.execute('INSERT INTO users VALUES(?,?,?,?,?,?)',(id,email,name,password_hash(password,salt),salt,now()))
  except sqlite3.IntegrityError:raise ValueError('该邮箱已注册，请登录') from None
  profile=normalize_profile({'name':name,'email':email})
  with db() as c:c.execute('INSERT INTO profiles VALUES(?,?)',(id,dump(profile)))
  session(response,id);return {'id':id,'name':name,'email':email}
 if action!='login':raise HTTPException(404)
 with db() as c:r=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
 if not r or not secrets.compare_digest(r['password'],password_hash(password,r['salt'])):raise HTTPException(401,'邮箱或密码不正确')
 session(response,r['id']);return {'id':r['id'],'name':r['name'],'email':r['email']}
@app.post('/api/logout')
def logout(req:Request,response:Response):
 with db() as c:c.execute('DELETE FROM sessions WHERE token=?',(digest(req.cookies.get('cf_session','')),))
 response.delete_cookie('cf_session');return {'ok':True}
@app.get('/api/me')
def me(u=Depends(user)):return u
@app.get('/api/profile')
def profile(u=Depends(user)):return get_profile(u['id'])
@app.put('/api/profile')
def save_profile(p:dict,u=Depends(user)):
 p=normalize_profile(p)
 with db() as c:c.execute('INSERT INTO profiles VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET data=excluded.data',(u['id'],dump(p)))
 return p
@app.post('/api/profile/import-preview')
async def import_profile(file:UploadFile=File(...),u=Depends(user)):
 try:
  content=await file.read(MAX_FILE+1)
  return preview_resume(file.filename or '',content)
 finally:await file.close()
@app.get('/api/settings')
def settings(u=Depends(user)):
 cfg=get_settings(u['id'])
 for section in ('llm','search','mail'):
  cfg.setdefault(section,{})
  for k in ('key','password','imap_password'):
   if k in cfg[section]:cfg[section][k+'_saved']=bool(cfg[section].pop(k))
 return cfg
@app.put('/api/settings')
def set_settings(p:dict,u=Depends(user)):
 cfg=get_settings(u['id'])
 allowed={'llm':{'provider','base_url','model','key'},'search':{'provider','key'},'mail':{'username','password','imap_password','smtp_host','smtp_port','imap_host','imap_port','poll_enabled'}}
 for section,keys in allowed.items():
  if section not in p:continue
  old=cfg.get(section,{});incoming={k:v for k,v in p[section].items() if k in keys}
  for k in ('key','password','imap_password'):
   if k in incoming and not incoming[k]:incoming.pop(k)
  merged=old|incoming
  if section=='llm':
   if merged.get('provider','openai') not in {'openai','ollama'}:raise ValueError('模型服务类型无效')
   if merged.get('provider')=='ollama':
    merged['base_url']=merged.get('base_url') or LOCAL_BASE;merged['model']=merged.get('model') or DEFAULT_MODEL
    validate_local(merged);merged.pop('key',None)
   elif merged.get('base_url'):public_url(merged['base_url'])
  if section=='search' and merged.get('provider') not in {'yuanbao','tavily'}:raise ValueError('搜索服务类型无效')
  if section=='mail':
   for k in ('smtp_host','imap_host'):
    if merged.get(k):public_host(merged[k])
   if any(old.get(k)!=merged.get(k) for k in ('username','smtp_host','imap_host')):cfg.pop('mail_test',None)
  if len(dump(merged))>8000:raise ValueError('设置过长')
  cfg[section]=merged
 save_settings(u['id'],cfg);return {'ok':True}
@app.post('/api/settings/test-model')
def test_model(u=Depends(user)):
 cfg=get_settings(u['id']).get('llm',{})
 if cfg.get('provider')=='ollama':
  answer,stats=local_chat(cfg,[{'role':'user','content':'只回复：本地连接正常'}],max_tokens=30)
  return {'ok':True,'note':f'本地AI已真实响应（{stats["elapsed_seconds"]}秒）；无需API密钥，没有发送个人档案','runtime':stats}
 if not all(cfg.get(k) for k in ['base_url','key','model']):raise ValueError('请先保存完整模型配置')
 d=fetch(cfg['base_url'].rstrip('/')+'/chat/completions','POST',{'model':cfg['model'],'messages':[{'role':'user','content':'Reply with OK.'}],'max_tokens':8},headers={'Authorization':'Bearer '+cfg['key']},timeout=50).json()
 if not d.get('choices'):raise ValueError('模型响应格式不兼容')
 return {'ok':True,'note':'模型已真实响应；没有发送个人档案'}
@app.get('/api/settings/local-models')
def local_models(u=Depends(user)):return local_status()
@app.post('/api/mail/self-test')
def mail_test(u=Depends(user)):return send_self_test(u['id'])
@app.post('/api/mail/poll')
def mail_poll(u=Depends(user)):return {'task_id':enqueue(u['id'],'mail_poll',{},deduplicate=True)}
@app.get('/api/catalog')
def catalog(u=Depends(user)):return {'sources':CATALOG,'platforms':PLATFORMS}
@app.get('/api/sources')
def sources(u=Depends(user)):
 with db() as c:rows=c.execute('SELECT * FROM sources WHERE owner=?',(u['id'],)).fetchall()
 return [{**dict(r),'data':load(r['data']),'last_result':load(r['last_result'])} for r in rows]
@app.post('/api/sources')
def add_source(p:dict,u=Depends(user)):
 if p.get('kind') not in {'greenhouse','lever','ashby','workday','website'}:raise ValueError('来源类型无效')
 public_url(p.get('url',''));p={k:v for k,v in p.items() if k in {'name','kind','url','company','board','search','max_jobs','max_pages','interval_seconds','region'}}
 p['interval_seconds']=max(900,min(604800,int(p.get('interval_seconds',21600))));p['max_jobs']=min(1000,max(1,int(p.get('max_jobs',400))));p['name']=str(p.get('name','自定义来源'))[:150]
 id=uid()
 with db() as c:
  old=c.execute('SELECT id,data FROM sources WHERE owner=?',(u['id'],)).fetchall()
  for r in old:
   if canonical(load(r['data']).get('url',''))==canonical(p['url']):return {'id':r['id'],'existing':True}
  c.execute('INSERT INTO sources(id,owner,data) VALUES(?,?,?)',(id,u['id'],dump(p)))
 return {'id':id}
@app.patch('/api/sources/{id}')
def schedule_source(id:str,p:dict,u=Depends(user)):
 s=owned('sources',id,u['id']);d=s['data'];d['interval_seconds']=max(900,min(604800,int(p.get('interval_seconds',d.get('interval_seconds',21600)))))
 with db() as c:c.execute('UPDATE sources SET enabled=?,next_run=?,data=? WHERE id=? AND owner=?',(bool(p.get('enabled')),now()+d['interval_seconds'],dump(d),id,u['id']))
 return {'ok':True}
@app.delete('/api/sources/{id}')
def remove_source(id:str,u=Depends(user)):
 owned('sources',id,u['id'])
 with db() as c:c.execute('DELETE FROM sources WHERE id=? AND owner=?',(id,u['id']))
 return {'ok':True}
@app.post('/api/sources/{id}/collect')
def pull(id:str,u=Depends(user)):
 owned('sources',id,u['id']);return {'task_id':enqueue(u['id'],'collect',{'source_id':id})}
@app.post('/api/search')
def search(p:dict,u=Depends(user)):
 q=str(p.get('query','')).strip()
 if not q or len(q)>500:raise ValueError('搜索词须为1—500字')
 return {'task_id':enqueue(u['id'],'search',{'query':q})}
@app.post('/api/workflow')
def workflow(p:dict,u=Depends(user)):
 if not any(f.get('verified') for f in get_profile(u['id']).get('facts',[])):raise ValueError('请先建立并确认经历事实')
 return {'task_id':enqueue(u['id'],'workflow',{'collect':bool(p.get('collect',True)),'search':bool(p.get('search',True)),'auto_send':p.get('confirm_auto_send') is True,'limit':min(10,int(p.get('limit',3)))})}
@app.get('/api/tasks')
def tasks(u=Depends(user)):
 with db() as c:rows=c.execute('SELECT * FROM tasks WHERE owner=? ORDER BY created DESC LIMIT 30',(u['id'],)).fetchall()
 return [{**dict(r),'data':load(r['data']),'result':load(r['result'])} for r in rows]
@app.get('/api/tasks/{id}')
def task(id:str,u=Depends(user)):return owned('tasks',id,u['id'])
@app.get('/api/jobs')
def jobs(q:str='',kind:str='',verdict:str='',offset:int=0,limit:int=40,u=Depends(user)):
 p=get_profile(u['id'])
 with db() as c:rows=c.execute('SELECT * FROM jobs WHERE owner=? ORDER BY updated DESC',(u['id'],)).fetchall()
 out=[]
 for r in rows:
  j=load(r['data'])
  if kind and j.get('kind')!=kind:continue
  if q.lower() not in (' '.join(str(j.get(k,'')) for k in ['title','company','location','description'])).lower():continue
  m=match(p,j)
  if verdict and m['verdict']!=verdict:continue
  out.append({'id':r['id'],'data':{k:v for k,v in j.items() if k!='description'}|{'excerpt':j.get('description','')[:260]},'match':m})
 out.sort(key=lambda x:(x['match']['verdict']!='blocked',x['match']['relevance']),reverse=True)
 return {'total':len(out),'items':out[max(0,offset):max(0,offset)+min(100,max(1,limit))]}
@app.get('/api/jobs/{id}')
def get_job(id:str,u=Depends(user)):
 j=owned('jobs',id,u['id']);j['match']=match(get_profile(u['id']),j['data']);return j
@app.post('/api/jobs/import')
def import_job(p:dict,u=Depends(user)):
 public_url(p.get('url',''))
 if not p.get('title') or not p.get('description'):raise ValueError('请填写职位名称与原文职责')
 s={'name':'用户导入原文','url':p['url'],'kind':'manual','company':str(p.get('company',''))}
 j=jobbase(s,str(p['title']),p['url'],str(p['description']),location=str(p.get('location','未披露')),deadline=str(p.get('deadline','')),salary=str(p.get('salary','未披露')),benefits=str(p.get('benefits','未披露')),evidence_level='用户提供JD，未代替官网核验')
 j['status']='needs_review';store_jobs(u['id'],'manual',[j])
 with db() as c:row=c.execute('SELECT id FROM jobs WHERE owner=? AND canonical=?',(u['id'],canonical(j['url']))).fetchone()
 edit_job(row['id'],p,u)
 return {'ok':True,'id':row['id']}
@app.post('/api/jobs/{id}/verify')
def verify_job(id:str,u=Depends(user)):
 old=owned('jobs',id,u['id']);j=old['data'];r=fetch(j['url']);body=text(r.text)
 closed=bool(re.search(r'no longer available|position (?:has been|is) (?:filled|closed)|职位已关闭|职位已下线|招聘已结束',body,re.I))
 found=jsonld_jobs(r.text,{'name':j['source_name'],'kind':'website','url':j['source_url'],'company':j.get('company','')},j['url'])
 if found:
  new=found[0];new['source_id']=j.get('source_id');j.update(new)
 else:j['verification_note']='页面可读取；未取得结构化单岗数据，须结合原文核对'
 if closed:j['status']='closed'
 j['checked_at']=now();j['last_page_hash']=digest(body);j['content_hash']=job_fingerprint(j)
 with db() as c:c.execute('UPDATE jobs SET data=?,updated=? WHERE id=? AND owner=?',(dump(j),now(),id,u['id']))
 return {'ok':True,'closed':closed,'structured':bool(found),'note':j.get('verification_note','已读回职位结构化数据')}
@app.patch('/api/jobs/{id}')
def edit_job(id:str,p:dict,u=Depends(user)):
 old=owned('jobs',id,u['id']);j=dict(old['data'])
 for k in ['title','company','location','salary','benefits','deadline','description','apply_url','application_email','email_source','company_type','company_summary','work_environment','company_source','workplace','employment']:
  if k in p:j[k]=str(p[k])[:50000 if k=='description' else 3000]
 if j.get('apply_url'):public_url(j['apply_url'])
 if p.get('confirm_job'):
  if not j.get('title') or not j.get('description') or not j.get('apply_url'):raise ValueError('确认单岗前请填写职位、原文和投递网址')
  j['kind']='job';j['status']='listed';j['evidence_level']='用户已核对职位字段';j['user_confirmed_at']=now();j['checked_at']=now()
 if 'email_confirmed' in p:j['email_confirmed']=p['email_confirmed'] is True
 if any(k in p and str(p[k])!=str(old['data'].get(k,'')) for k in ['application_email','email_source']):j['email_confirmed']=p.get('email_confirmed') is True
 if p.get('email_confirmed'):
  if not j.get('email_source') or not j.get('application_email'):raise ValueError('请填写招聘邮箱和公开来源')
  public_url(j['email_source']);j['email_confirmed']=True
 if j.get('company_source'):public_url(j['company_source'])
 j['content_hash']=job_fingerprint(j)
 with db() as c:c.execute('UPDATE jobs SET data=?,updated=? WHERE id=? AND owner=?',(dump(j),now(),id,u['id']))
 return {'ok':True}
@app.post('/api/jobs/{id}/advice')
def advice(id:str,u=Depends(user)):return ai_advice(u['id'],get_profile(u['id']),owned('jobs',id,u['id'])['data'])
@app.get('/api/jobs/{id}/interview')
def interview(id:str,u=Depends(user)):return interview_pack(get_profile(u['id']),owned('jobs',id,u['id'])['data'])
@app.post('/api/jobs/{id}/resume')
def resume(id:str,p:dict,u=Depends(user)):return build_resume(u['id'],get_profile(u['id']),owned('jobs',id,u['id'])['data'],id,p.get('fact_ids'))
@app.get('/api/resumes')
def resumes(u=Depends(user)):
 with db() as c:rows=c.execute('SELECT * FROM resumes WHERE owner=? ORDER BY created DESC',(u['id'],)).fetchall()
 return [{**dict(r),'data':load(r['data'])} for r in rows]
@app.post('/api/resumes/export')
def export_resumes(p:dict,u=Depends(user)):
 return Response(resume_archive(u['id'],p.get('ids'),p.get('formats')),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="CareerFlow-resumes.zip"'})
@app.get('/api/resumes/{id}/{format}')
def download(id:str,format:str,u=Depends(user)):
 r=owned('resumes',id,u['id'])
 if format not in {'pdf','docx','txt'}:raise HTTPException(404)
 f=DATA/'artifacts'/u['id']/id/('resume.'+format)
 if not f.is_file():raise HTTPException(404,'附件文件已缺失，请重新生成')
 return FileResponse(f,filename=re.sub(r'[^\w\-\u4e00-\u9fff]','_',r['data'].get('job_title','Resume'))[:70]+'.'+format)
@app.get('/api/applications')
def applications(u=Depends(user)):
 with db() as c:rows=c.execute('SELECT * FROM applications WHERE owner=? ORDER BY updated DESC',(u['id'],)).fetchall()
 return [{**dict(r),'data':load(r['data'])} for r in rows]
@app.get('/api/applications/export.csv')
def export_applications(u=Depends(user)):
 return Response(application_csv(u['id']),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="CareerFlow-applications.csv"'})
@app.post('/api/applications')
def application(p:dict,u=Depends(user)):return prepare_application(u['id'],p['job_id'],p['resume_id'])
@app.post('/api/applications/{id}/record')
def record(id:str,p:dict,u=Depends(user)):
 owned('applications',id,u['id']);state=p.get('state')
 if state not in {'reported_submitted','interview','offer','rejected','withdrawn'}:raise ValueError('状态无效')
 if not str(p.get('evidence','')).strip():raise ValueError('请填写回执编号、链接或实际情况说明')
 update_state(u['id'],id,state,{'receipt':str(p['evidence'])[:5000],'source':'用户手动记录'});return {'ok':True}
@app.post('/api/applications/{id}/send')
def send(id:str,p:dict,u=Depends(user)):
 if p.get('confirm') is not True:raise ValueError('请确认实际发送')
 return send_application(u['id'],id,str(p.get('recipient','')),str(p.get('subject','应聘申请'))[:150],str(p.get('body',''))[:10000])
@app.get('/api/messages')
def messages(u=Depends(user)):
 with db() as c:rows=c.execute('SELECT * FROM messages WHERE owner=? ORDER BY created DESC LIMIT 300',(u['id'],)).fetchall()
 return [{**dict(r),'data':load(r['data'])} for r in rows]
@app.get('/api/dashboard')
def dashboard(u=Depends(user)):
 with db() as c:
  counts={t:c.execute(f'SELECT COUNT(*) FROM {t} WHERE owner=?',(u['id'],)).fetchone()[0] for t in ['jobs','sources','resumes','applications','messages']}
  counts['submitted']=c.execute("SELECT COUNT(*) FROM applications WHERE owner=? AND state IN ('smtp_accepted','reported_submitted','receipt_received','reply_received','interview','offer')",(u['id'],)).fetchone()[0]
  events=c.execute('SELECT * FROM events WHERE owner=? ORDER BY created DESC LIMIT 8',(u['id'],)).fetchall()
 return {'counts':counts,'events':[{**dict(e),'data':load(e['data'])} for e in events]}

app.mount('/',StaticFiles(directory=ROOT/'web',html=True),name='web')
