import concurrent.futures,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from careerflow.catalog import CATALOG
def probe(s):
 try:
  r=httpx.get(s['url'],timeout=30,follow_redirects=True)
  d=r.json() if r.status_code==200 else {}
  return {'name':s['name'],'url':s['url'],'status':r.status_code,'count':len(d.get('jobs',[]) if isinstance(d,dict) else d)}
 except Exception as e:return {'name':s['name'],'error':type(e).__name__}
print(json.dumps(list(concurrent.futures.ThreadPoolExecutor(4).map(probe,CATALOG[:6])),ensure_ascii=False,indent=2))
