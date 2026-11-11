"""Read-only live collection acceptance. No employer applications are sent."""
import sys,json,time,secrets,os
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from careerflow import core
from careerflow.catalog import CATALOG

def main():
 core.init();private=ROOT/'qa/private';private.mkdir(parents=True,exist_ok=True)
 c=httpx.Client(base_url='http://127.0.0.1:8769/api',headers={'X-CareerFlow':'1'},timeout=120)
 email='live-qa-'+str(int(time.time()))+'@example.test';password=secrets.token_urlsafe(24)
 def call(method,path,data=None):
  r=c.request(method,path,json=data);r.raise_for_status();return r.json()
 user=call('POST','/auth/register',{'name':'多行业验收档案（虚构）','email':email,'password':password})
 (private/'live-account.json').write_text(json.dumps({'owner':user['id'],'email':email,'password':password}),'utf-8')
 profile={'name':'验收样例（虚构）','email':email,'education':'本科','school':'示例大学（虚构）','major':'计算机科学','graduation':'2028-06','experience_years':0,'skills':['Python','SQL','product','data','analysis'],'roles':['数据分析','产品实习'],'locations':['中国','上海'],'availability':'虚构测试档案，不向真实企业投递','facts':[{'id':'demo1','kind':'project','title':'课程数据分析（虚构样例）','text':'使用Python和SQL处理合成课程数据，整理产品需求并制作展示报告。','tags':'Python,SQL,data,product,analysis','evidence':'测试合成资料','verified':True}]}
 call('PUT','/profile',profile)
 task_ids=[]
 for s in CATALOG:
  cfg={**s,'max_jobs':1000 if s['kind']!='workday' else 30,'max_pages':5}
  sid=call('POST','/sources',cfg)['id'];task=call('POST','/sources/'+sid+'/collect',{});task_ids.append(task['task_id'])
 print('Queued',len(task_ids),'real public sources',flush=True)
 deadline=time.time()+900
 while time.time()<deadline:
  tasks=call('GET','/tasks');active=[x for x in tasks if x['id'] in task_ids and x['state'] in ['queued','running']]
  if not active:break
  print('Pending',len(active),flush=True);time.sleep(10)
 source_results=call('GET','/sources')
 # Optional caller-supplied key; no dependency on another application's credentials.
 key=os.environ.get('CAREERFLOW_TEST_SEARCH_KEY','')
 if key:
  try:
   call('PUT','/settings',{'search':{'provider':'yuanbao','key':key}})
   qs=['2027 校园招聘 国企 电气 工程师 官方 招聘','2027 暑期实习 外企 数据分析 产品 官方 招聘','2026 社会招聘 制造 机械 技术支持 工程师 官网','2027 校园招聘 财务 市场 护理 物流 官网']
   ids=[call('POST','/search',{'query':q})['task_id'] for q in qs]
   for _ in range(60):
    ts=call('GET','/tasks')
    if not any(x['id'] in ids and x['state'] in ['queued','running'] for x in ts):break
    time.sleep(2)
  except Exception as e:print('Search test unavailable:',type(e).__name__,flush=True)
  finally:
   with core.db() as conn:conn.execute('DELETE FROM secrets WHERE owner=?',(user['id'],))
 # Run the actual workflow API against collected jobs, without external delivery.
 workflow=call('POST','/workflow',{'collect':False,'search':False,'limit':3})
 for _ in range(60):
  ts=call('GET','/tasks');wf=next((x for x in ts if x['id']==workflow['task_id']),{})
  if wf.get('state') in ['done','failed']:break
  time.sleep(2)
 result={'checked_at':time.strftime('%Y-%m-%d %H:%M:%S'),'owner':user['id'],'sources':source_results,'dashboard':call('GET','/dashboard'),'workflow':wf,'tasks':call('GET','/tasks'),'actual_employer_submissions':0}
 (private/'live-acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
 print(json.dumps({'counts':result['dashboard']['counts'],'source_success':sum(bool(s['last_run']) and not s['last_result'].get('error') for s in source_results),'source_total':len(source_results),'workflow':wf.get('state'),'actual_employer_submissions':0},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
