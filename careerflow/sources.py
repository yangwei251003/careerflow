from __future__ import annotations
import datetime as dt, html, json, re, time, urllib.robotparser
from urllib.parse import urlsplit,urljoin,urlunsplit,parse_qsl,urlencode
from pathlib import Path
import httpx
from bs4 import BeautifulSoup
from .core import DATA,db,digest,dump,load,now,uid,public_url,event

UA='CareerFlow/0.1 (+local user-authorized job research)'
def request(url,method='GET',payload=None,headers=None,timeout=30):
 for attempt in range(2 if method=='GET' else 1):
  try:return request_once(url,method,payload,headers,timeout)
  except httpx.TransportError:
   if method!='GET' or attempt:raise
   time.sleep(1)

def request_once(url,method='GET',payload=None,headers=None,timeout=30):
 public_url(url)
 # Every redirect is checked; credentials are never forwarded to another host.
 with httpx.Client(timeout=timeout,follow_redirects=False,trust_env=False) as c:
  for _ in range(5):
   with c.stream(method,url,json=payload,headers={'User-Agent':UA,**(headers or {})}) as r:
    if r.status_code in {301,302,303,307,308}:
     nxt=urljoin(url,r.headers.get('location',''));public_url(nxt)
     if headers:raise ValueError('带密钥的接口不允许重定向')
     url=nxt;method='GET';payload=None;continue
    if r.status_code>=400:raise ValueError(f'来源请求未成功（HTTP {r.status_code}）')
    content=bytearray()
    for b in r.iter_bytes():
     content.extend(b)
     if len(content)>12_000_000:raise ValueError('来源超过12MB读取限制')
    decoded_headers={k:v for k,v in r.headers.items() if k.lower() not in {'content-encoding','content-length','transfer-encoding'}}
    return httpx.Response(r.status_code,headers=decoded_headers,content=bytes(content),request=httpx.Request(method,url))
 raise ValueError('来源重定向次数过多')

def text(html_text):
 soup=BeautifulSoup(html.unescape(str(html_text or '')),'html.parser')
 for node in soup(['script','style','nav','footer']):node.decompose()
 return re.sub(r'\n\s*\n+','\n',soup.get_text('\n',strip=True)).strip()

def canonical(url):
 p=urlsplit(url)
 q=[(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith(('utm_','source','referrer'))]
 return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/'),urlencode(sorted(q)),''))

def job_fingerprint(job):
 return digest(dump({k:job.get(k) for k in ['title','company','description','location','salary','benefits','deadline','employment','workplace','apply_url','status']}))

def jobbase(s,title,url,description='',**extra):
 return {'title':str(title)[:500],'company':s.get('company',''),'location':'未披露','description':str(description)[:50000],
  'url':url,'apply_url':url,'source_url':s['url'],'source_name':s['name'],'source_kind':s['kind'],
  'kind':'job','status':'listed','published':'','updated_source':'','deadline':'','salary':'未披露','benefits':'未披露',
  'workplace':'未披露','employment':'未披露','company_type':'未核实','company_summary':'未核实','work_environment':'未披露','company_source':'','evidence_level':'公开职位接口','checked_at':now(),**extra}

def parse_greenhouse(data,s):
 out=[]
 for j in data.get('jobs',[]):
  out.append(jobbase(s,j['title'],j['absolute_url'],text(j.get('content','')),external_id=str(j['id']),location=j.get('location',{}).get('name','未披露'),published=j.get('first_published',''),updated_source=j.get('updated_at',''),deadline=j.get('application_deadline','')))
 return out
def parse_lever(data,s):
 out=[]
 for j in data:
  salary=j.get('salaryRange')
  sal=(f"{salary.get('min','')}–{salary.get('max','')} {salary.get('currency','')} / {salary.get('interval','周期未披露')}" if salary else text(j.get('salaryDescription','')) or '未披露')
  desc=j.get('descriptionPlain','')+'\n'+'\n'.join(x.get('text','')+'\n'+text(x.get('content','')) for x in j.get('lists',[]))+'\n'+j.get('additionalPlain','')
  out.append(jobbase(s,j['text'],j['hostedUrl'],desc,external_id=j['id'],apply_url=j.get('applyUrl',j['hostedUrl']),location=j.get('categories',{}).get('location','未披露'),employment=j.get('categories',{}).get('commitment','未披露'),workplace=j.get('workplaceType','未披露'),salary=sal))
 return out
def parse_ashby(data,s):
 out=[]
 for j in data.get('jobs',[]):
  if j.get('isListed') is False:continue
  comp=j.get('compensation') or {}
  out.append(jobbase(s,j['title'],j['jobUrl'],j.get('descriptionPlain') or text(j.get('descriptionHtml','')),external_id=j.get('id',digest(j['jobUrl'])[:20]),apply_url=j.get('applyUrl',j['jobUrl']),location=j.get('location','未披露'),employment=j.get('employmentType','未披露'),workplace=j.get('workplaceType','未披露'),published=j.get('publishedAt',''),salary=comp.get('scrapeableCompensationSalarySummary') or comp.get('compensationTierSummary') or '未披露'))
 return out

def jsonld_jobs(body,s,url):
 soup=BeautifulSoup(body,'html.parser');nodes=[]
 for node in soup.select('script[type="application/ld+json"]'):
  try:
   data=json.loads(node.string or node.get_text());nodes.extend(data if isinstance(data,list) else [data])
  except (ValueError,TypeError):continue
 out=[]
 while nodes:
  j=nodes.pop(0)
  if not isinstance(j,dict):continue
  nodes.extend(j.get('@graph',[]))
  typ=j.get('@type',[]);typ=[typ] if isinstance(typ,str) else typ
  if 'JobPosting' not in typ:continue
  loc=j.get('jobLocation',[]);loc=[loc] if isinstance(loc,dict) else loc
  locations=[]
  for l in loc:
   a=l.get('address',{}) if isinstance(l,dict) else {}
   locations.append(' '.join(str(a.get(k,'')) for k in ['addressCountry','addressRegion','addressLocality','streetAddress']).strip())
  org=j.get('hiringOrganization',{});org=org.get('name','') if isinstance(org,dict) else str(org)
  sal=j.get('baseSalary',{});sal=sal[0] if isinstance(sal,list) and sal else sal
  salary='未披露'
  if isinstance(sal,dict) and sal:
   value=sal.get('value',{});value=value if isinstance(value,dict) else {'value':value}
   salary=f"{value.get('minValue',value.get('value',''))}–{value.get('maxValue','')} {sal.get('currency','')} / {value.get('unitText','周期未披露')}"
  out.append(jobbase(s,j.get('title','未命名岗位'),j.get('url',url),text(j.get('description','')),company=org or s.get('company',''),location=' / '.join(filter(None,locations)) or '未披露',published=j.get('datePosted',''),deadline=j.get('validThrough',''),employment=str(j.get('employmentType','未披露')),salary=salary,benefits=text(j.get('jobBenefits','')) or '未披露',evidence_level='网页结构化职位数据'))
 return out

def robots_allowed(url):
 p=urlsplit(url);robot=urlunsplit((p.scheme,p.netloc,'/robots.txt','',''))
 try:r=request(robot,timeout=12)
 except ValueError as e:
  if '404' in str(e):return True
  # Unknown policy is not treated as permission for bulk traversal.
  return False
 parser=urllib.robotparser.RobotFileParser();parser.parse(r.text.splitlines());return parser.can_fetch('CareerFlow',url)

def parse_website(s,max_pages=12):
 if not robots_allowed(s['url']):raise ValueError('未能确认该站允许此自动读取；请使用原站或导入已取得的JD')
 first=request(s['url']);body=first.text;url=str(first.url)
 jobs=jsonld_jobs(body,s,url);soup=BeautifulSoup(body,'html.parser')
 links=[]
 for a in soup.select('a[href]'):
  link=urljoin(url,a['href']);label=a.get_text(' ',strip=True)
  if urlsplit(link).hostname!=urlsplit(url).hostname:continue
  if re.search(r'招聘|岗位|职位|实习|应聘|career|job|position|recruit|zpdetail',label+' '+link,re.I) and canonical(link)!=canonical(url):
   if link not in links and not re.search(r'\.(png|jpg|zip|docx?|pdf|xlsx?)(\?|$)',link,re.I):links.append(link)
 if not jobs:
  title=(soup.title.get_text(' ',strip=True) if soup.title else s['name'])
  jobs.append(jobbase(s,title,url,text(body)[:20000],kind='lead',status='needs_review',apply_url='',evidence_level='公开网页正文，未确认单岗'))
 errors=[]
 for link in links[:max_pages-1]:
  try:
   if not robots_allowed(link):continue
   time.sleep(.3);r=request(link,timeout=20);found=jsonld_jobs(r.text,s,str(r.url))
   if found:jobs+=found
   else:
    bs=BeautifulSoup(r.text,'html.parser');title=bs.title.get_text(' ',strip=True) if bs.title else link
    jobs.append(jobbase(s,title,str(r.url),text(r.text)[:25000],kind='lead',status='needs_review',apply_url='',evidence_level='招聘/公告网页，需核对职位字段'))
  except Exception as e:errors.append({'url':link,'error':str(e)[:150]})
 return jobs,{'complete':False,'links_found':len(links),'pages_checked':min(len(links)+1,max_pages),'errors':errors,'note':'仅遍历限定页数；不宣称已抓完整企业官网'}

def parse_workday(s,limit=80):
 p=urlsplit(s['url']);tenant=p.hostname.split('.')[0];site=p.path.rstrip('/').split('/')[-1]
 base=f'{p.scheme}://{p.netloc}/wday/cxs/{tenant}/{site}'
 out=[];offset=0;total=None;errors=[]
 while offset<limit:
  d=request(base+'/jobs','POST',{'appliedFacets':{},'limit':20,'offset':offset,'searchText':s.get('search','')}).json()
  total=d.get('total',0);items=d.get('jobPostings',[])
  if not items:break
  for j in items[:limit-len(out)]:
   try:
    detail=request(base+j['externalPath']).json().get('jobPostingInfo',{})
    url=f'{p.scheme}://{p.netloc}/en-US/{site}'+j['externalPath']
    out.append(jobbase(s,detail.get('title',j['title']),url,text(detail.get('jobDescription','')),external_id=detail.get('jobReqId',''),location=detail.get('location',j.get('locationsText','未披露')),published=detail.get('startDate',''),deadline=detail.get('endDate',''),employment=detail.get('timeType','未披露'),status='listed' if detail.get('canApply') else 'closed',evidence_level='企业公开招聘网页数据（接口可能变化）'))
   except Exception as e:errors.append({'title':j['title'],'error':str(e)[:100]})
  offset+=len(items)
  if offset>=total:break
 return out,{'complete':offset>=int(total or 0) and not errors,'total_reported':total,'checked':len(out),'errors':errors}

def collect(s):
 kind=s['kind'];max_jobs=min(1000,max(1,int(s.get('max_jobs',400))))
 if kind in {'greenhouse','lever','ashby'}:
  d=request(s['url']).json();all_jobs={'greenhouse':parse_greenhouse,'lever':parse_lever,'ashby':parse_ashby}[kind](d,s)
  return all_jobs[:max_jobs],{'complete':len(all_jobs)<=max_jobs,'total_reported':len(all_jobs),'checked':min(len(all_jobs),max_jobs)}
 if kind=='workday':return parse_workday(s,min(max_jobs,200))
 if kind=='website':return parse_website(s,min(30,int(s.get('max_pages',12))))
 raise ValueError('此来源类型尚未接入')

def store_jobs(owner,source_id,jobs,complete=False):
 counts={'new':0,'updated':0,'unchanged':0,'closed':0};seen=[]
 for j in jobs:
  if not j.get('url'):continue
  try:public_url(j['url'])
  except ValueError:continue
  key=canonical(j['url']);seen.append(key);j['source_id']=source_id
  j['content_hash']=job_fingerprint(j);j['checked_at']=now()
  with db() as c:
   old=c.execute('SELECT id,data FROM jobs WHERE owner=? AND canonical=?',(owner,key)).fetchone()
   if old:
    before=load(old['data']);j['first_seen']=before.get('first_seen',now());j['previous_hash']=before.get('content_hash','')
    if before.get('kind')=='job' and j.get('kind')=='lead':
     extra_sources=list(dict.fromkeys(before.get('additional_sources',[])+[j.get('source_url','')]))
     j={**before,'additional_sources':extra_sources}
    for k in ('application_email','email_confirmed','email_source','company_type','company_summary','work_environment','company_source'):
     if k.startswith('company_') or k=='work_environment':
      if j.get(k) not in ('',None,'未核实','未披露'):continue
     if k in before:j[k]=before[k]
    changed=any(before.get(k)!=j.get(k) for k in ['content_hash','salary','deadline','status','title'])
    counts['updated' if changed else 'unchanged']+=1
    c.execute('UPDATE jobs SET data=?,updated=? WHERE id=?',(dump(j),now(),old['id']))
   else:
    j['first_seen']=now();c.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(uid(),owner,key,dump(j),now()));counts['new']+=1
   snapshot_hash=digest(dump({k:j.get(k) for k in ['title','company','description','salary','benefits','deadline','status','evidence_level']}))
   c.execute('INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?,?)',(owner,key,snapshot_hash,dump(j),now()))
 if complete:
  with db() as c:
   rows=c.execute('SELECT id,canonical,data FROM jobs WHERE owner=?',(owner,)).fetchall()
   for r in rows:
    j=load(r['data'])
    if j.get('source_id')==source_id and r['canonical'] not in seen and j.get('status')!='closed':
     j['status']='closed';j['closure_reason']='完整来源列表已不包含此岗位';j['checked_at']=now()
     c.execute('UPDATE jobs SET data=?,updated=? WHERE id=?',(dump(j),now(),r['id']));counts['closed']+=1
 event(owner,'source_import',source_id,counts)
 return counts

def search_web(config,query):
 provider=config.get('provider','yuanbao');key=config.get('key','')
 if not key:raise ValueError('请先配置搜索API密钥')
 if provider=='yuanbao':
  r=request('https://api.wsa.cloud.tencent.com/SearchPro','POST',{'Query':query},headers={'Authorization':'Bearer '+key}).json()
  r=r.get('Response',{})
  if r.get('Error'):raise ValueError('搜索服务拒绝请求，请检查API配置或额度')
  pages=r.get('Pages',[]);out=[]
  for x in pages:
   if isinstance(x,str):x=json.loads(x)
   out.append({'title':x.get('title',''),'url':x.get('url',''),'description':x.get('passage',''),'published':x.get('date','')})
  return out
 if provider=='tavily':
  r=request('https://api.tavily.com/search','POST',{'query':query,'max_results':10,'search_depth':'basic','include_answer':False},headers={'Authorization':'Bearer '+key}).json()
  return [{'title':x.get('title',''),'url':x.get('url',''),'description':x.get('content',''),'published':x.get('published_date','')} for x in r.get('results',[])]
 raise ValueError('搜索服务仅支持元宝与Tavily')
