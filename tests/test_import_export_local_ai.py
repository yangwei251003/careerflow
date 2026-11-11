import io,json,zipfile,csv
import pytest
from test_core_flow import client,prepare,profile,job
from careerflow import core,resumes,local_models,app as web
from careerflow.imports import preview_resume,extract_document

TEXT='姓名：测试甲\n邮箱：sample@example.test\n测试大学 本科\n专业：信息管理\n预计毕业：2028年6月\n项目经历\n使用Python处理课程合成数据，形成分析报告。\n荣誉与证书\n课程演示优秀（虚构测试）'

def test_import_preview_never_saves_or_confirms(client):
 before=client.get('/api/profile').json()
 r=client.post('/api/profile/import-preview',files={'file':('resume.txt',TEXT.encode(),'text/plain')})
 assert r.status_code==200
 d=r.json();assert d['suggested']['name']=='测试甲';assert d['suggested']['graduation']=='2028-06'
 assert len(d['facts'])==2 and all(not f['verified'] for f in d['facts'])
 assert client.get('/api/profile').json()==before
 before['facts']=d['facts'];client.put('/api/profile',json=before)
 _,jid,_=job(client)
 assert client.post('/api/jobs/'+jid+'/resume',json={}).status_code==400

def test_docx_and_pdf_text_extraction(client):
 from docx import Document
 doc=Document()
 for line in TEXT.splitlines():doc.add_paragraph(line)
 buf=io.BytesIO();doc.save(buf)
 assert '合成数据' in preview_resume('a.docx',buf.getvalue())['text']
 _,_,rid,_=prepare(client)
 pdf=client.get(f'/api/resumes/{rid}/pdf').content
 text,pages=extract_document('a.pdf',pdf)
 assert 'Python' in text and pages>=1

def test_import_rejects_invalid_large_encrypted_and_image_pdf(client):
 from pypdf import PdfWriter
 for name,content in [('a.exe',b'1234567890123'),('a.txt',b'x'*4_000_001),('a.docx',b'broken zip')]:
  with pytest.raises(ValueError):extract_document(name,content)
 for encrypted in [False,True]:
  w=PdfWriter();w.add_blank_page(width=595,height=842)
  if encrypted:w.encrypt('test-only-password')
  b=io.BytesIO();w.write(b)
  with pytest.raises(ValueError):extract_document('a.pdf',b.getvalue())

def test_bulk_archive_all_or_nothing_and_owner(client):
 owner,jid,rid,_=prepare(client)
 r=client.post('/api/resumes/export',json={'ids':[rid,rid]});assert r.status_code==200
 with zipfile.ZipFile(io.BytesIO(r.content)) as z:
  assert z.testzip() is None and len(z.namelist())==3
  manifest=json.loads(z.read('manifest.json'));assert manifest[0]['confirmed_fact_ids']==['f1']
  assert all('..' not in name for name in z.namelist())
 (core.DATA/'artifacts'/owner/rid/'resume.docx').unlink()
 assert client.post('/api/resumes/export',json={'ids':[rid]}).status_code==400
 client.post('/api/logout',json={});client.post('/api/auth/register',json={'email':'two@example.test','password':'test-password-for-two','name':'乙'})
 assert client.post('/api/resumes/export',json={'ids':[rid]}).status_code==404

def test_application_export_owned_and_formula_safe(client):
 owner,jid,rid,aid=prepare(client)
 with core.db() as c:
  a=core.load(c.execute('SELECT data FROM applications WHERE id=?',(aid,)).fetchone()[0]);a['company']='=1+2'
  c.execute('UPDATE applications SET data=? WHERE id=?',(core.dump(a),aid))
 r=client.get('/api/applications/export.csv');assert r.content.startswith(b'\xef\xbb\xbf')
 rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));assert len(rows)==2
 assert rows[1][0]=="'=1+2" and '材料已备好' in rows[1]
 client.post('/api/logout',json={});client.post('/api/auth/register',json={'email':'two@example.test','password':'test-password-for-two','name':'乙'})
 assert len(list(csv.reader(io.StringIO(client.get('/api/applications/export.csv').content.decode('utf-8-sig')))))==1

def test_local_provider_cannot_turn_into_network_proxy(client,monkeypatch):
 good={'provider':'ollama','base_url':local_models.BASE,'model':'qwen3.5:2b','key':'TEST-NOT-SECRET'}
 assert client.put('/api/settings',json={'llm':good}).status_code==200
 cfg=core.get_settings(client.get('/api/me').json()['id'])['llm'];assert 'key' not in cfg
 for url in ['http://192.168.1.1:11434','http://localhost:11434','http://127.0.0.1:22','http://127.0.0.1:11434@evil.example','https://public.example']:
  assert client.put('/api/settings',json={'llm':good|{'base_url':url}}).status_code==400
 for model in ['gemma4:cloud','https://host/model','../bad']:
  assert client.put('/api/settings',json={'llm':good|{'model':model}}).status_code==400
 assert client.put('/api/settings',json={'llm':good|{'provider':'openai'}}).status_code==400
 with pytest.raises(ValueError):local_models.local_request('/api/pull',{})

def test_local_model_rejects_remote_alias_and_no_fabricated_fact(client,monkeypatch):
 cfg={'provider':'ollama','base_url':local_models.BASE,'model':'qwen3.5:2b'}
 def remote(path,payload=None,timeout=10):
  return {'models':[{'name':'qwen3.5:2b'}]} if path=='/api/tags' else {'remote_model':'hidden-remote','remote_host':'cloud.example'}
 monkeypatch.setattr(local_models,'local_request',remote)
 with pytest.raises(ValueError,match='云端'):local_models.check_local_model(cfg)
 owner,jid,_,_=prepare(client);client.put('/api/settings',json={'llm':cfg})
 seen={}
 def fake(config,messages,schema,max_tokens):
  seen['messages']=messages;seen['schema']=schema
  return json.dumps({'selected_fact_ids':['f1','not-real','f2','f1'], 'gap_notes':['待核对业务案例'], 'interview_questions':['说明你的实际职责']}),{'local':True,'elapsed_seconds':1}
 monkeypatch.setattr(resumes,'local_chat',fake)
 r=client.post('/api/jobs/'+jid+'/advice',json={});assert r.status_code==200
 assert r.json()['selected_fact_ids']==['f1']
 payload=json.loads(seen['messages'][1]['content']);assert [f['id'] for f in payload['facts']]==['f1']
 assert 'email' not in payload and '虚构大奖' not in json.dumps(payload,ensure_ascii=False)
 assert seen['schema']['properties']['selected_fact_ids']['items']['enum']==['f1']

def test_local_runtime_options_and_incomplete_rejected(monkeypatch):
 monkeypatch.setattr(local_models,'check_local_model',lambda cfg:'qwen3.5:2b')
 seen={}
 def fake(path,payload,timeout):
  seen.update(payload);return {'message':{'content':'测试成功'},'done_reason':'stop','eval_count':4,'eval_duration':1e9}
 monkeypatch.setattr(local_models,'local_request',fake)
 value,stats=local_models.local_chat({},[{'role':'user','content':'合成测试'}])
 assert value=='测试成功' and stats['local'] and seen['think'] is False
 assert seen['options']['num_ctx']==4096 and seen['options']['num_gpu']==0 and seen['keep_alive']=='2m'
 monkeypatch.setattr(local_models,'local_request',lambda *a,**k:{'message':{'content':'{unfinished'},'done_reason':'length'})
 with pytest.raises(ValueError,match='长度限制'):local_models.local_chat({},[])
