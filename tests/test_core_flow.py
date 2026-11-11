import json,os,sys,uuid
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['CAREERFLOW_NO_WORKER']='1'
from fastapi.testclient import TestClient
from careerflow import core,app as web,mail,resumes,sources,worker
from careerflow.matching import match

@pytest.fixture
def client(tmp_path,monkeypatch):
 monkeypatch.setattr(core,'DATA',tmp_path);monkeypatch.setattr(core,'DB',tmp_path/'test.sqlite');monkeypatch.setattr(mail,'DATA',tmp_path);monkeypatch.setattr(resumes,'DATA',tmp_path);monkeypatch.setattr(web,'DATA',tmp_path)
 web.rate.clear();core.init()
 with TestClient(web.app,headers={'X-CareerFlow':'1'}) as c:
  assert c.post('/api/auth/register',json={'name':'虚构验收样例','email':'one@example.test','password':'Sample-only-Password-2026'}).status_code==200
  yield c

def profile():return {'name':'虚构测试甲','email':'one@example.test','school':'测试大学','education':'本科','major':'计算机','graduation':'2028-06','skills':['Python','SQL'],'experience_years':0,'availability':'仅用于测试，不投真实企业','facts':[{'id':'f1','kind':'project','title':'测试数据项目','text':'使用Python处理100条合成记录，完成SQL分析。','tags':'Python,SQL','verified':True,'evidence':'合成测试资料'},{'id':'f2','title':'未经确认的大奖','text':'虚构大奖不得进入简历','verified':False}]}
def job(client,**changes):
 owner=client.get('/api/me').json()['id'];id=core.uid()
 j={'title':'Python数据分析实习','company':'虚构测试企业','kind':'job','status':'listed','description':'本科及以上，2028届毕业生，Python SQL数据分析。','url':'https://example.com/job/'+id,'apply_url':'https://example.com/job/'+id,'checked_at':core.now(),'content_hash':'jobhash','location':'上海','salary':'未披露','source_name':'验收样例','application_email':'hr@example.test','email_confirmed':True,'email_source':'https://example.com/careers',**changes}
 with core.db() as c:c.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',(id,owner,j['url'],core.dump(j),core.now()))
 return owner,id,j
def prepare(client):
 assert client.put('/api/profile',json=profile()).status_code==200
 owner,jid,j=job(client);r=client.post('/api/jobs/'+jid+'/resume',json={});assert r.status_code==200,r.text
 rid=r.json()['id'];a=client.post('/api/applications',json={'job_id':jid,'resume_id':rid});assert a.status_code==200,a.text
 return owner,jid,rid,a.json()['id']

def test_profile_isolation_and_auth(client):
 client.put('/api/profile',json=profile());owner,jid,j=job(client)
 client.post('/api/logout',json={});assert client.get('/api/profile').status_code==401
 client.post('/api/auth/register',json={'name':'第二位','email':'two@example.test','password':'Sample-only-Password-2026'})
 assert client.get('/api/jobs/'+jid).status_code==404
 assert client.get('/api/profile').json()['name']=='第二位'
 assert client.post('/api/sources/'+jid+'/collect',json={}).status_code==404

def test_csrf_and_untrusted_host(client):
 assert client.put('/api/profile',json={},headers={'X-CareerFlow':''}).status_code==403
 assert client.put('/api/profile',json={},headers={'Origin':'https://evil.example'}).status_code==403
 assert client.get('/api/health',headers={'Host':'evil.example'}).status_code==400

@pytest.mark.parametrize('address',['127.0.0.1','10.0.0.1','169.254.169.254','192.168.1.1','::1'])
def test_ssrf_private_addresses(address,monkeypatch):
 monkeypatch.setattr(core.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',(address,80))])
 with pytest.raises(ValueError):core.public_url('https://public.example/')

def test_ssrf_protocol_credentials():
 for u in ['file:///etc/passwd','https://user:password@example.com','http://localhost/','http://example.com:3306/']:
  with pytest.raises(ValueError):core.public_url(u)

def test_matching_different_people():
 j={'kind':'job','status':'listed','title':'2027届软件工程师','description':'本科及以上，3年以上工作经验，Python','apply_url':'https://example.com','checked_at':core.now()}
 p=profile();m=match(p,j);assert m['verdict']=='blocked';assert len(m['gates'])==2
 p.update(graduation='2027-06',experience_years=4);assert not match(p,j)['gates']
 p['education']='大专';assert any('学历' in s for s in match(p,j)['gates'])

def test_closed_and_expired_block():
 for change in [{'status':'closed'},{'deadline':'2020-01-01'}]:assert match(profile(),{'kind':'job','title':'岗位',**change})['verdict']=='blocked'

def test_experience_and_location_are_not_keyword_passes():
 p=profile();p['locations']=['上海']
 j={'title':'Data Scientist','kind':'job','status':'listed','description':'3+ years of industry experience in data analysis.','location':'New York','checked_at':core.now(),'apply_url':'https://example.com'}
 m=match(p,j);assert m['gates'];assert any('地点' in x for x in m['warnings'])
 j['description']='Preferred: 3 years of experience.';assert not match(p,j)['gates']

def test_search_snippet_does_not_downgrade_verified_job(client,monkeypatch):
 monkeypatch.setattr(sources,'public_url',lambda x:x);owner=client.get('/api/me').json()['id']
 sources.store_jobs(owner,'official',[{'title':'岗位','url':'https://example.com/job','kind':'job','description':'完整官方职责','salary':'100 CNY / DAY','status':'listed'}])
 sources.store_jobs(owner,'search',[{'title':'搜索摘要','url':'https://example.com/job','kind':'lead','description':'不完整摘要','status':'needs_review','source_url':'https://example.com/search'}])
 row=client.get('/api/jobs').json()['items'][0]['data'];assert row['kind']=='job';assert row['salary']=='100 CNY / DAY'

def test_stale_resume_requires_regeneration(client,monkeypatch):
 owner,jid,rid,aid=prepare(client);p=profile();p['phone']='123456';client.put('/api/profile',json=p)
 monkeypatch.setattr(mail,'config',lambda o:{'username':'sender@example.test'})
 r=client.post(f'/api/applications/{aid}/send',json={'recipient':'hr@example.test','confirm':True});assert r.status_code==400;assert '档案已更新' in r.json()['detail']
 r=client.post('/api/jobs/'+jid+'/resume',json={});new=r.json()['id'];client.post('/api/applications',json={'job_id':jid,'resume_id':new})
 assert client.get('/api/applications').json()[0]['resume_id']==new

def test_resume_artifacts_facts_and_ownership(client):
 from pypdf import PdfReader
 owner,jid,rid,aid=prepare(client)
 text=client.get(f'/api/resumes/{rid}/txt').text
 assert '100条合成记录' in text and '虚构大奖' not in text
 assert client.get(f'/api/resumes/{rid}/docx').status_code==200
 pdf=core.DATA/'artifacts'/owner/rid/'resume.pdf';reader=PdfReader(str(pdf));assert len(reader.pages)>=1;assert 'Python' in reader.pages[0].extract_text()
 client.post('/api/logout',json={});client.post('/api/auth/register',json={'email':'other@example.test','password':'Another-Password-123','name':'乙'})
 assert client.get(f'/api/resumes/{rid}/pdf').status_code==404
 assert client.post(f'/api/applications/{aid}/record',json={'state':'offer','evidence':'x'}).status_code==404

def test_duplicate_application(client):
 owner,jid,rid,aid=prepare(client)
 for _ in range(2):assert client.post('/api/applications',json={'job_id':jid,'resume_id':rid}).json()['id']==aid
 assert len(client.get('/api/applications').json())==1
 assert client.get('/api/dashboard').json()['counts']['submitted']==0

def test_receipt_requires_evidence(client):
 owner,jid,rid,aid=prepare(client)
 assert client.post(f'/api/applications/{aid}/record',json={'state':'reported_submitted','evidence':''}).status_code==400
 assert client.post(f'/api/applications/{aid}/record',json={'state':'reported_submitted','evidence':'测试回执，不是真实投递'}).status_code==200
 a=client.get('/api/applications').json()[0];assert a['data']['source']=='用户手动记录'

def test_secret_redaction_and_encryption(client,monkeypatch):
 monkeypatch.setattr(web,'public_url',lambda x:x)
 key='UNITTEST-NOT-A-REAL-KEY'
 assert client.put('/api/settings',json={'llm':{'base_url':'https://example.com/v1','model':'test','key':key}}).status_code==200
 result=client.get('/api/settings');assert key not in result.text;assert result.json()['llm']['key_saved'] is True
 with core.db() as c:raw=c.execute('SELECT data FROM secrets').fetchone()[0]
 assert key not in raw
 client.put('/api/settings',json={'llm':{'key':'','model':'test2'}});assert core.get_settings(client.get('/api/me').json()['id'])['llm']['key']==key

def test_connector_normalization_no_guessed_salary():
 s={'name':'样例','kind':'ashby','company':'样例公司','url':'https://example.com'}
 j=sources.parse_ashby({'jobs':[{'title':'岗位','jobUrl':'https://example.com/j','applyUrl':'https://example.com/a','descriptionPlain':'职责','isListed':True}]},s)[0]
 assert j['salary']=='未披露' and j['deadline']=='' and j['apply_url'].endswith('/a')
 assert sources.parse_ashby({'jobs':[{'isListed':False}]},s)==[]

def test_source_dedup_and_complete_only_closure(client,monkeypatch):
 monkeypatch.setattr(sources,'public_url',lambda x:x);owner=client.get('/api/me').json()['id']
 j={'title':'A','url':'https://example.com/a?utm_source=x','status':'listed','description':'text','kind':'job'}
 assert sources.store_jobs(owner,'s',[j])['new']==1
 assert sources.store_jobs(owner,'s',[j])['unchanged']==1
 sources.store_jobs(owner,'s',[],False);assert client.get('/api/jobs').json()['items'][0]['data']['status']=='listed'
 sources.store_jobs(owner,'s',[],True);assert client.get('/api/jobs').json()['items'][0]['data']['status']=='closed'

def test_scheduler_persistent_queue_no_duplicate(client):
 owner=client.get('/api/me').json()['id']
 with core.db() as c:c.execute('INSERT INTO sources(id,owner,data,enabled,next_run) VALUES(?,?,?,?,?)',('s',owner,core.dump({'interval_seconds':900}),1,0))
 worker.tick();worker.tick()
 assert len(client.get('/api/tasks').json())==1
 assert client.get('/api/sources').json()[0]['next_run']>core.now()

class FakeSMTP:
 def __init__(self,fail=False):self.sent=[];self.fail=fail
 def send_message(self,m):
  self.sent.append(m)
  if self.fail:raise TimeoutError('simulated after DATA')
  return {}
 def quit(self):pass

def test_mail_application_acceptance_not_delivery(client,monkeypatch):
 owner,jid,rid,aid=prepare(client);smtp=FakeSMTP()
 monkeypatch.setattr(mail,'config',lambda o:{'username':'sender@example.test'})
 monkeypatch.setattr(mail,'smtp_connect',lambda c:smtp)
 r=client.post(f'/api/applications/{aid}/send',json={'recipient':'hr@example.test','subject':'测试','body':'测试','confirm':True})
 assert r.status_code==200,r.text;assert r.json()['state']=='smtp_accepted';assert len(smtp.sent)==1
 assert client.post(f'/api/applications/{aid}/send',json={'recipient':'hr@example.test','confirm':True}).status_code==400
 assert len(smtp.sent)==1

def test_uncertain_send_is_not_retried(client,monkeypatch):
 owner,jid,rid,aid=prepare(client);smtp=FakeSMTP(fail=True)
 monkeypatch.setattr(mail,'config',lambda o:{'username':'sender@example.test'});monkeypatch.setattr(mail,'smtp_connect',lambda c:smtp)
 assert client.post(f'/api/applications/{aid}/send',json={'recipient':'hr@example.test','confirm':True}).status_code==400
 assert client.get('/api/applications').json()[0]['state']=='send_unknown'
 assert client.post(f'/api/applications/{aid}/send',json={'recipient':'hr@example.test','confirm':True}).status_code==400
 assert len(smtp.sent)==1

def test_self_test_is_only_to_self(client,monkeypatch):
 smtp=FakeSMTP();owner=client.get('/api/me').json()['id']
 monkeypatch.setattr(mail,'config',lambda o:{'username':'mytest@example.test'});monkeypatch.setattr(mail,'smtp_connect',lambda c:smtp)
 result=client.post('/api/mail/self-test',json={});assert result.status_code==200
 assert smtp.sent[0]['To']=='mytest@example.test';assert result.json()['self_seen'] is False
 assert client.get('/api/applications').json()==[]

def test_authorized_pipeline_sends_only_verified_email(client,monkeypatch):
 client.put('/api/profile',json=profile());owner,jid,j=job(client);smtp=FakeSMTP()
 monkeypatch.setattr(mail,'config',lambda o:{'username':'sender@example.test'});monkeypatch.setattr(mail,'smtp_connect',lambda c:smtp)
 tid=core.enqueue(owner,'workflow',{'collect':False,'search':False,'limit':1,'auto_send':True})
 with core.db() as c:t=dict(c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone())
 worker.run_task(t)
 task=client.get('/api/tasks').json()[0];assert task['state']=='done',task
 assert len(smtp.sent)==1;assert task['result']['sent'][0]['state']=='smtp_accepted'

def test_no_model_config_does_not_fake_success(client):
 owner,jid,j=job(client)
 assert client.post('/api/jobs/'+jid+'/advice',json={}).status_code==400
 assert client.post('/api/settings/test-model',json={}).status_code==400

def test_manual_job_cannot_be_sent_without_verified_email(client,monkeypatch):
 owner,jid,rid,aid=prepare(client)
 with core.db() as c:
  r=c.execute('SELECT data FROM jobs WHERE id=?',(jid,)).fetchone();j=core.load(r['data']);j['email_confirmed']=False;c.execute('UPDATE jobs SET data=? WHERE id=?',(core.dump(j),jid))
 monkeypatch.setattr(mail,'config',lambda o:{'username':'sender@example.test'})
 assert client.post(f'/api/applications/{aid}/send',json={'recipient':'hr@example.test','confirm':True}).status_code==400
 assert client.get('/api/applications').json()[0]['state']=='prepared'

def test_changed_jd_and_recipient_invalidate_old_confirmation(client,monkeypatch):
 monkeypatch.setattr(web,'public_url',lambda x:x)
 owner,jid,rid,aid=prepare(client)
 client.patch('/api/jobs/'+jid,json={'description':'改为要求5年以上经验','application_email':'changed@example.test'})
 j=client.get('/api/jobs/'+jid).json()['data']
 assert j['content_hash']!='jobhash' and j['email_confirmed'] is False
 assert client.post(f'/api/applications/{aid}/send',json={'recipient':'changed@example.test','confirm':True}).status_code==400

def test_missing_attachment_keeps_application_prepared(client,monkeypatch):
 owner,jid,rid,aid=prepare(client)
 (core.DATA/'artifacts'/owner/rid/'resume.pdf').unlink()
 monkeypatch.setattr(mail,'config',lambda o:{'username':'sender@example.test'})
 assert client.post(f'/api/applications/{aid}/send',json={'recipient':'hr@example.test','confirm':True}).status_code==400
 assert client.get('/api/applications').json()[0]['state']=='prepared'

def test_imap_correlates_self_and_reply_without_unrelated_mail(client,monkeypatch):
 from email.message import EmailMessage
 smtp=FakeSMTP();owner=client.get('/api/me').json()['id']
 cfg={'username':'mytest@example.test','imap_host':'imap.example.test'}
 monkeypatch.setattr(mail,'config',lambda o:cfg);monkeypatch.setattr(mail,'smtp_connect',lambda c:smtp)
 original=mail.send_self_test(owner);mid=original['message_id']
 reply=EmailMessage();reply['From']='mytest@example.test';reply['To']='mytest@example.test';reply['Message-ID']='<reply@example.test>';reply['In-Reply-To']=mid;reply['Subject']='Re: 测试';reply.set_content('真实服务尚待验证，此为协议测试替身')
 unrelated=EmailMessage();unrelated['From']='unrelated@example.test';unrelated['Message-ID']='<unrelated@example.test>';unrelated.set_content('不得关联此邮件')
 class FakeIMAP:
  def __init__(self):self.searches=[]
  def uid(self,op,*args):
   if op=='search':self.searches.append(args);return 'OK',[b'1 2 3']
   return 'OK',[(b'',{b'1':smtp.sent[0].as_bytes(),b'2':reply.as_bytes(),b'3':unrelated.as_bytes()}[args[0]])]
  def response(self,*a):return 'UIDVALIDITY',[b'1']
  def logout(self):pass
 imap=FakeIMAP();monkeypatch.setattr(mail,'imap_connect',lambda c:imap)
 result=mail.poll_mail(owner);assert result['new']==2;assert result['mail_test']['self_seen'];assert result['mail_test']['reply_seen']
 assert all(x[1]=='HEADER' for x in imap.searches);assert mail.poll_mail(owner)['new']==0
 assert len(client.get('/api/messages').json())==2

def test_working_professional_resume_uses_actual_graduation(client):
 p=profile();p.update(graduation='2020-06',experience_years=6)
 client.put('/api/profile',json=p);owner,jid,j=job(client,description='SQL Python，3年以上工作经验')
 rid=client.post('/api/jobs/'+jid+'/resume',json={}).json()['id']
 body=client.get('/api/resumes/'+rid+'/txt').text
 assert '毕业 2020-06' in body and '预计毕业' not in body

def test_multiple_experience_requirements_do_not_lower_overall_minimum():
 p=profile();p['experience_years']=3
 j={'kind':'job','status':'listed','description':'5 years of industry experience\n2 years of Python experience'}
 assert match(p,j)['constraints']['experience_min']==5
 assert match(p,j)['gates']
