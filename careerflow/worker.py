from __future__ import annotations
import concurrent.futures,threading,time
from .core import db,load,dump,now,uid,owned,enqueue,get_profile,get_settings,save_settings,event
from .sources import collect,store_jobs,search_web,jobbase,parse_website
from .matching import match
from .resumes import build_resume
from .mail import poll_mail,prepare_application,send_application

def query_plan(profile):
 roles=profile.get('roles',[])[:3] or ['实习 校园招聘' if profile.get('graduation','') else '社会招聘']
 location=' '.join(profile.get('locations',[])[:2]);queries=[]
 for role in roles:
  queries.extend([f'{role} {location} 招聘 企业官网',f'{role} {location} 招聘 公告 国企 外企 民营'])
 for domain in ['zhipin.com','zhaopin.com','51job.com','liepin.com']:
  queries.append(f'site:{domain} '+roles[0]+' '+location+' 招聘')
 return queries[:10]

STOP=threading.Event()
def collect_source(owner,id):
 s=owned('sources',id,owner);config=s['data'];jobs,meta=collect(config)
 counts=store_jobs(owner,id,jobs,meta.get('complete',False));result={**meta,**counts}
 with db() as c:c.execute('UPDATE sources SET last_run=?,last_result=? WHERE id=? AND owner=?',(now(),dump(result),id,owner))
 return result

def run_task(t):
 owner=t['owner'];d=load(t['data']);kind=t['kind']
 try:
  if kind=='collect':result=collect_source(owner,d['source_id'])
  elif kind=='search':
   cfg=get_settings(owner).get('search',{});pages=search_web(cfg,d['query']);source={'name':'搜索发现：'+d['query'],'kind':'search','url':'https://api.wsa.cloud.tencent.com/' if cfg.get('provider')=='yuanbao' else 'https://api.tavily.com/'}
   jobs=[jobbase(source,x['title'],x['url'],x['description'],kind='lead',status='needs_review',apply_url='',published=x.get('published',''),evidence_level='搜索线索，需核验原始网页') for x in pages if x.get('url')]
   result=store_jobs(owner,'search',jobs);result['found']=len(jobs)
  elif kind=='mail_poll':result=poll_mail(owner)
  elif kind=='workflow':
   result={'sources':[],'searches':[],'prepared':[],'sent':[],'note':'只按明确授权的可用渠道投递；未满足条件的申请保留为待处理'}
   profile=get_profile(owner);search_cfg=get_settings(owner).get('search',{})
   if d.get('search',True) and search_cfg.get('key'):
    for query in query_plan(profile):
     try:
      pages=search_web(search_cfg,query);s={'name':'搜索发现：'+query,'kind':'search','url':'https://api.wsa.cloud.tencent.com/' if search_cfg.get('provider')=='yuanbao' else 'https://api.tavily.com/'}
      leads=[jobbase(s,x['title'],x['url'],x['description'],kind='lead',status='needs_review',apply_url='',published=x.get('published',''),evidence_level='搜索线索，需原网页核验') for x in pages if x.get('url')]
      result['searches'].append({'query':query,**store_jobs(owner,'search',leads)})
      for lead in leads[:2]:
       try:
        source={'name':lead['title'],'kind':'website','url':lead['url'],'company':''};found,meta=parse_website(source,max_pages=2);store_jobs(owner,'search-verified',found)
       except Exception:pass
     except Exception as e:result['searches'].append({'query':query,'error':str(e)[:150]})
   if d.get('collect',True):
    with db() as c:sources=c.execute('SELECT id FROM sources WHERE owner=?',(owner,)).fetchall()
    for s in sources:
     try:result['sources'].append({'id':s['id'],'result':collect_source(owner,s['id'])})
     except Exception as e:result['sources'].append({'id':s['id'],'error':str(e)[:200]})
   with db() as c:rows=c.execute('SELECT id,data FROM jobs WHERE owner=?',(owner,)).fetchall()
   choices=[]
   for r in rows:
    job=load(r['data']);m=match(profile,job)
    if not m['gates'] and job.get('kind')=='job' and m['relevance']>=10:choices.append((m['relevance'],r['id'],job))
   for score,id,job in sorted(choices,reverse=True)[:min(10,max(1,int(d.get('limit',3))))]:
    resume=build_resume(owner,profile,job,id);application=prepare_application(owner,id,resume['id'])
    result['prepared'].append({'job_id':id,'resume_id':resume['id'],'application_id':application['id'],'state':application['state']})
    if d.get('auto_send') and application['state']=='prepared' and job.get('email_confirmed') and match(profile,job)['verdict']=='candidate':
     try:
      sent=send_application(owner,application['id'],job['application_email'],'应聘 '+job['title'],f"您好，\n我希望申请贵公司的{job['title']}岗位。附件为我的岗位相关简历，期待进一步交流。\n{profile.get('name','')}\n{profile.get('email','')}")
      result['sent'].append({'application_id':sent['id'],'state':sent['state']})
     except Exception as e:result['sent'].append({'application_id':application['id'],'error':str(e)[:150]})
   if not result['prepared']:result['note']='没有找到符合当前档案且有足够相关证据的岗位；请补充事实、搜索范围或资格。'
  else:raise ValueError('未知任务类型')
  with db() as c:c.execute('UPDATE tasks SET state=?,result=?,updated=? WHERE id=?',('done',dump(result),now(),t['id']))
 except Exception as e:
  message=str(e)[:250] if isinstance(e,(ValueError,LookupError)) else '处理未完成（'+type(e).__name__+'），请检查来源或设置后重试'
  with db() as c:
   c.execute('UPDATE tasks SET state=?,error=?,updated=? WHERE id=?',('failed',message,now(),t['id']))
   if kind=='collect':
    old=c.execute('SELECT last_result FROM sources WHERE id=? AND owner=?',(d['source_id'],owner)).fetchone()
    failures=int(load(old['last_result']).get('failures',0))+1 if old else 1
    delay=min(21600,900*2**min(5,failures-1))
    c.execute('UPDATE sources SET last_run=?,last_result=?,next_run=? WHERE id=? AND owner=?',(now(),dump({'error':message,'failures':failures,'retry_after_seconds':delay}),now()+delay,d['source_id'],owner))

def tick():
 t=now()
 with db() as c:
  due=c.execute('SELECT * FROM sources WHERE enabled=1 AND next_run<=?',(t,)).fetchall()
  for s in due:
   pending=c.execute("SELECT 1 FROM tasks WHERE owner=? AND kind='collect' AND state IN ('queued','running') AND data LIKE ?",(s['owner'],'%'+s['id']+'%')).fetchone()
   config=load(s['data']);interval=max(900,int(config.get('interval_seconds',21600)))
   c.execute('UPDATE sources SET next_run=? WHERE id=?',(t+interval,s['id']))
   if not pending:c.execute('INSERT INTO tasks(id,owner,kind,state,data,created,updated) VALUES(?,?,?,?,?,?,?)',(uid(),s['owner'],'collect','queued',dump({'source_id':s['id']}),t,t))

def worker():
 STOP.clear()
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
  futures=[];last_mail=0
  while not STOP.wait(1):
   futures=[f for f in futures if not f.done()]
   try:
    tick()
    if now()-last_mail>60:
     last_mail=now()
     with db() as c:owners=c.execute('SELECT owner FROM secrets').fetchall()
     for row in owners:
      cfg=get_settings(row['owner'])
      if cfg.get('mail',{}).get('poll_enabled') and now()-cfg.get('last_mail_poll',0)>300:
       cfg['last_mail_poll']=now();save_settings(row['owner'],cfg);enqueue(row['owner'],'mail_poll',{},deduplicate=True)
    if len(futures)>=3:continue
    with db() as c:
     c.execute('BEGIN IMMEDIATE');task=c.execute("SELECT * FROM tasks WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
     if task:c.execute("UPDATE tasks SET state='running',updated=? WHERE id=?",(now(),task['id']))
    if task:futures.append(pool.submit(run_task,dict(task)))
   except Exception:time.sleep(1)

def start():
 with db() as c:
  c.execute("UPDATE tasks SET state='interrupted',error='服务上次中断，请核查后重试',updated=? WHERE state='running'",(now(),))
  c.execute("UPDATE applications SET state='send_unknown',updated=? WHERE state='sending'",(now(),))
 thread=threading.Thread(target=worker,name='careerflow-worker',daemon=True);thread.start();return thread
