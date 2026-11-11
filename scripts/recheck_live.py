"""Recheck previous failed read-only sources and replay material preparation; never sends mail."""
import sys,json,time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from careerflow.catalog import CATALOG
private=ROOT/'qa/private';account=json.loads((private/'live-account.json').read_text('utf-8'))
c=httpx.Client(base_url='http://127.0.0.1:8769/api',headers={'X-CareerFlow':'1'},timeout=90)
def call(method,path,data=None):
 r=c.request(method,path,json=data);r.raise_for_status();return r.json()
call('POST','/auth/login',{'email':account['email'],'password':account['password']})
sources=call('GET','/sources');ids=[]
for s in sources:
 if s['last_result'].get('error') or s['data']['kind']=='workday':ids.append(call('POST','/sources/'+s['id']+'/collect',{})['task_id'])
for s in CATALOG[12:]:
 sid=call('POST','/sources',{**s,'max_pages':3})['id'];ids.append(call('POST','/sources/'+sid+'/collect',{})['task_id'])
deadline=time.time()+480
while time.time()<deadline:
 tasks=call('GET','/tasks');pending=[t for t in tasks if t['id'] in ids and t['state'] in ['queued','running']]
 if not pending:break
 print('Read-only rechecks pending:',len(pending),flush=True);time.sleep(5)
wf_id=call('POST','/workflow',{'collect':False,'search':False,'confirm_auto_send':False,'limit':3})['task_id']
for _ in range(40):
 wf=next((t for t in call('GET','/tasks') if t['id']==wf_id),{})
 if wf.get('state') in ['done','failed']:break
 time.sleep(2)
result={'checked_at':time.strftime('%Y-%m-%d %H:%M:%S'),'sources':call('GET','/sources'),'counts':call('GET','/dashboard')['counts'],'workflow':wf,'actual_employer_submissions':0}
(private/'live-recheck.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps({'counts':result['counts'],'sources':[{'name':s['data']['name'],'result':s['last_result']} for s in result['sources']],'workflow':wf.get('state'),'employer_submissions':0},ensure_ascii=False),flush=True)
