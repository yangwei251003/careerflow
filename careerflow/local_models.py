"""Explicit local Ollama transport; never relax the public-source URL policy."""
from __future__ import annotations
import json,re,threading,time
import httpx

BASE='http://127.0.0.1:11434'
DEFAULT_MODEL='qwen3.5:4b'
_generation=threading.Lock()

def validate_local(cfg):
 if cfg.get('base_url',BASE).rstrip('/')!=BASE:raise ValueError('本地模型仅支持 http://127.0.0.1:11434；其他服务请使用云端模式')
 name=cfg.get('model') or DEFAULT_MODEL
 if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,149}',name) or '://' in name or '..' in name or 'cloud' in name.lower():raise ValueError('请选择已下载的本地模型，不能使用云端模型或网址')
 return name

def local_request(path,payload=None,timeout=10):
 if path not in {'/api/tags','/api/show','/api/chat','/api/ps'}:raise ValueError('不支持此本地模型操作')
 try:
  with httpx.Client(trust_env=False,follow_redirects=False,timeout=httpx.Timeout(timeout,connect=3)) as client:
   with client.stream('GET' if payload is None else 'POST',BASE+path,json=payload) as r:
    if r.status_code!=200:raise ValueError('本地模型未完成请求，请检查模型是否已下载、服务是否可用')
    data=bytearray()
    for chunk in r.iter_bytes(16384):
     data.extend(chunk)
     if len(data)>200_000:raise ValueError('本地模型返回内容过大')
  result=json.loads(data)
  if not isinstance(result,dict):raise ValueError('本地模型响应格式无效')
  return result
 except httpx.ConnectError:raise ValueError('本地AI尚未启动。请运行“启动本地AI.cmd”，再重试') from None
 except httpx.TimeoutException:raise ValueError('本地AI响应超时，请减少同时运行的任务或缩短经历内容') from None
 except (httpx.HTTPError,json.JSONDecodeError):raise ValueError('本地AI连接或响应异常，请检查运行状态') from None

def check_local_model(cfg):
 name=validate_local(cfg)
 models=local_request('/api/tags').get('models',[])
 if not any(m.get('name')==name or m.get('model')==name for m in models):raise ValueError('模型尚未下载，请先在本机安装所选模型')
 detail=local_request('/api/show',{'model':name})
 if detail.get('remote_model') or detail.get('remote_host'):raise ValueError('该名称指向云端模型，请选择完全本地的模型')
 return name

def local_chat(cfg,messages,schema=None,max_tokens=420):
 if not _generation.acquire(blocking=False):raise ValueError('本地AI正在处理上一项任务，请稍后再试')
 try:
  name=check_local_model(cfg);started=time.monotonic()
  body={'model':name,'messages':messages,'stream':False,'think':False,'keep_alive':'2m','options':{'num_ctx':4096,'num_predict':max_tokens,'num_thread':4,'num_gpu':0,'temperature':0.2,'seed':42}}
  if schema:body['format']=schema
  result=local_request('/api/chat',body,timeout=180)
  content=result.get('message',{}).get('content','')
  if not isinstance(content,str) or not content.strip():raise ValueError('本地模型没有返回可用内容')
  if result.get('done_reason')=='length':raise ValueError('本地模型达到本次输出长度限制，请缩短岗位和经历内容后重试')
  seconds=round(time.monotonic()-started,2);duration=result.get('eval_duration',0)/1e9
  return content,{'provider':'ollama','model':name,'elapsed_seconds':seconds,'output_tokens':result.get('eval_count',0),'tokens_per_second':round(result.get('eval_count',0)/duration,2) if duration else None,'local':True}
 finally:_generation.release()

def status():
 data=local_request('/api/tags')
 return {'ok':True,'base_url':BASE,'models':[{'name':m.get('name'),'size':m.get('size'),'parameter_size':m.get('details',{}).get('parameter_size')} for m in data.get('models',[]) if 'cloud' not in m.get('name','').lower()]}
