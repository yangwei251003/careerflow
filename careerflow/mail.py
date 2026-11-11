from __future__ import annotations
import email,imaplib,re,smtplib,ssl
from email.message import EmailMessage
from email.policy import default
from email.utils import formatdate,make_msgid,parseaddr
from .core import DATA,db,uid,now,dump,load,get_settings,save_settings,public_host,owned,event,digest

def config(owner):
 cfg=get_settings(owner).get('mail',{})
 if not all(cfg.get(k) for k in ['username','password','smtp_host','imap_host']):raise ValueError('请在API与邮箱中配置测试邮箱的SMTP、IMAP及授权码')
 if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',cfg['username']):raise ValueError('邮箱地址无效')
 public_host(cfg['smtp_host']);public_host(cfg['imap_host'])
 if int(cfg.get('smtp_port',465)) not in {465,587} or int(cfg.get('imap_port',993))!=993:raise ValueError('仅支持加密邮件端口465/587和993')
 return cfg

def smtp_connect(cfg):
 port=int(cfg.get('smtp_port',465));ctx=ssl.create_default_context()
 if port==465:c=smtplib.SMTP_SSL(cfg['smtp_host'],port,timeout=25,context=ctx)
 else:
  c=smtplib.SMTP(cfg['smtp_host'],port,timeout=25);c.ehlo();c.starttls(context=ctx);c.ehlo()
 c.login(cfg['username'],cfg['password']);return c

def imap_connect(cfg):
 c=imaplib.IMAP4_SSL(cfg['imap_host'],int(cfg.get('imap_port',993)),ssl_context=ssl.create_default_context(),timeout=25)
 c.login(cfg['username'],cfg.get('imap_password') or cfg['password']);c.select('INBOX',readonly=True);return c

def send_self_test(owner):
 cfg=config(owner);token='CFTEST-'+uid();msg=EmailMessage();msg['From']=cfg['username'];msg['To']=cfg['username'];msg['Subject']='职航真实邮件链路测试 '+token;msg['Date']=formatdate(localtime=True);msg['Message-ID']=make_msgid(domain=cfg['username'].split('@')[-1]);msg.set_content('这是你授权的职航测试邮件，未发送给招聘企业。\n测试标识：'+token+'\n可以回复这封邮件，再在职航同步收件箱，验证回信关联。')
 settings=get_settings(owner);settings['mail_test']={'token':token,'message_id':msg['Message-ID'],'sent_at':now(),'smtp':'sending','self_seen':False,'reply_seen':False};save_settings(owner,settings)
 c=None;attempted=False
 try:
  c=smtp_connect(cfg);attempted=True;refused=c.send_message(msg)
  if refused:raise ValueError('邮件服务器拒收测试地址')
  settings['mail_test']['smtp']='accepted';save_settings(owner,settings)
 except Exception:
  settings['mail_test']['smtp']='unknown' if attempted else 'failed';save_settings(owner,settings)
  raise ValueError('测试邮件未确认成功；请查看邮箱设置。结果未知时先检查收件箱，勿盲目重发。') from None
 finally:
  if c:
   try:c.quit()
   except Exception:pass
 event(owner,'mail_self_test',token,{'smtp':'accepted'})
 return settings['mail_test']

def prepare_application(owner,job_id,resume_id):
 job=owned('jobs',job_id,owner);resume=owned('resumes',resume_id,owner)
 if resume['job_id']!=job_id:raise ValueError('这份简历不属于当前岗位')
 id=uid();t=now();data={'job_title':job['data']['title'],'company':job['data'].get('company',''),'apply_url':job['data'].get('apply_url',''),'history':[{'state':'prepared','time':t,'source':'platform'}]}
 with db() as c:
  old=c.execute('SELECT id,state FROM applications WHERE owner=? AND job_id=?',(owner,job_id)).fetchone()
  if old:
   if old['state']=='prepared':c.execute('UPDATE applications SET resume_id=?,updated=? WHERE id=?',(resume_id,t,old['id']))
   existing=old['id']
  else:
   c.execute('INSERT INTO applications VALUES(?,?,?,?,?,?,?,?)',(id,owner,job_id,resume_id,'prepared',dump(data),t,t));existing=id
 return owned('applications',existing,owner)

def update_state(owner,id,state,details):
 app=owned('applications',id,owner);data=app['data'];data.update(details);data.setdefault('history',[]).append({'state':state,'time':now(),'source':details.get('source','platform')})
 with db() as c:c.execute('UPDATE applications SET state=?,data=?,updated=? WHERE id=? AND owner=?',(state,dump(data),now(),id,owner))
 event(owner,'application_'+state,id,{'source':details.get('source','platform')})

def send_application(owner,id,recipient,subject,body):
 app=owned('applications',id,owner)
 if app['state']!='prepared':raise ValueError('此申请已处理；为避免重复投递，不再次发送')
 if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',recipient) or '\n' in subject or '\r' in subject:raise ValueError('收件地址或主题格式错误')
 job=owned('jobs',app['job_id'],owner)['data']
 if job.get('status')=='closed' or job.get('kind')!='job':raise ValueError('关闭或尚未核实的线索不能自动发送')
 from .matching import match
 from .core import get_profile
 current_profile=get_profile(owner);resume=owned('resumes',app['resume_id'],owner)
 if resume['data'].get('profile_hash')!=digest(dump(current_profile)):raise ValueError('个人档案已更新，请重新生成并关联最新简历')
 if resume['data'].get('job_hash')!=job.get('content_hash',''):raise ValueError('岗位原文已变化，请重新生成并关联简历')
 m=match(current_profile,job)
 if m['gates']:raise ValueError('硬条件未通过：'+'；'.join(m['gates']))
 if now()-job.get('checked_at',0)>86400:raise ValueError('岗位核验超过24小时，请先重新核验')
 cfg=config(owner)
 if recipient.lower()!=job.get('application_email','').lower() or not job.get('email_confirmed'):raise ValueError('请先在岗位详情核对并登记官方投递邮箱与来源')
 msg=EmailMessage();msg['From']=cfg['username'];msg['To']=recipient;msg['Subject']=subject+' [CF-'+id+']';msg['Date']=formatdate(localtime=True);msg['Message-ID']=make_msgid(domain=cfg['username'].split('@')[-1]);msg.set_content(body)
 f=DATA/'artifacts'/owner/app['resume_id']/'resume.pdf'
 if not f.is_file():raise ValueError('简历附件缺失，请重新生成；尚未发送')
 msg.add_attachment(f.read_bytes(),maintype='application',subtype='pdf',filename='Resume.pdf')
 with db() as c:
  count=c.execute("SELECT COUNT(*) FROM events WHERE owner=? AND kind='application_smtp_accepted' AND created>?",(owner,now()-86400)).fetchone()[0]
  if count>=20:raise ValueError('今日邮件投递已达到20封上限')
  # Atomic claim protects concurrent/repeated clicks.
  changed=c.execute("UPDATE applications SET state='sending',updated=? WHERE id=? AND owner=? AND state='prepared'",(now(),id,owner)).rowcount
  if not changed:raise ValueError('该申请正在处理，请勿重复发送')
 c=None;attempted=False
 try:
  c=smtp_connect(cfg);attempted=True;refused=c.send_message(msg)
  if refused:raise ValueError('收件服务器拒绝邮件')
  update_state(owner,id,'smtp_accepted',{'message_id':msg['Message-ID'],'recipient':recipient,'subject':msg['Subject'],'sent_at':now(),'source':'SMTP','note':'发送服务器已接受；尚不等于企业已收到或HR已阅读'})
 except Exception:
  update_state(owner,id,'send_unknown' if attempted else 'send_failed',{'message_id':msg['Message-ID'],'source':'SMTP','note':'未确认成功，不自动重试'})
  raise ValueError('发送未确认，请检查申请记录和邮箱；不会自动重发') from None
 finally:
  if c:
   try:c.quit()
   except Exception:pass
 return owned('applications',id,owner)

def decode_body(msg):
 part=msg.get_body(preferencelist=('plain','html'))
 try:content=part.get_content() if part else ''
 except Exception:content='正文编码无法解析，请到邮箱查看'
 if part and part.get_content_type()=='text/html':
  from .sources import text
  content=text(content)
 return str(content)[:16000]

def poll_mail(owner):
 cfg=config(owner);settings=get_settings(owner);test=settings.get('mail_test',{});refs={}
 with db() as c:apps=c.execute("SELECT id,data FROM applications WHERE owner=? AND state IN ('smtp_accepted','send_unknown','receipt_received','reply_received')",(owner,)).fetchall()
 for a in apps:
  data=load(a['data'])
  if data.get('message_id'):refs[data['message_id']]=a['id']
 if test.get('message_id'):refs[test['message_id']]='self-test'
 if not refs:return {'new':0,'note':'尚无已发送邮件可关联，未扫描无关私人邮件'}
 c=imap_connect(cfg);count=0
 try:
  found=set()
  for ref in list(refs)[-100:]:
   for header in ['References','In-Reply-To','Message-ID']:
    status,rows=c.uid('search',None,'HEADER',header,'"'+ref+'"')
    if status=='OK' and rows and rows[0]:found.update(rows[0].split())
  validity=c.response('UIDVALIDITY')[1];validity=str(validity)
  for mail_uid in sorted(found,key=int)[-300:]:
   key=digest(cfg['imap_host']+cfg['username']+validity+mail_uid.decode())
   with db() as conn:
    if conn.execute('SELECT 1 FROM messages WHERE owner=? AND mail_key=?',(owner,key)).fetchone():continue
   status,rows=c.uid('fetch',mail_uid,'(BODY.PEEK[])')
   if status!='OK':continue
   raw=next((r[1] for r in rows if isinstance(r,tuple)),None)
   if not raw or len(raw)>3_000_000:continue
   msg=email.message_from_bytes(raw,policy=default);references=str(msg.get('References',''))+' '+str(msg.get('In-Reply-To',''));mid=str(msg.get('Message-ID',''));sender=parseaddr(str(msg.get('From','')))[1]
   linked=next((v for k,v in refs.items() if k in references or k==mid),None)
   if not linked:continue
   auto=str(msg.get('Auto-Submitted','')).lower() not in {'','no'};is_self=sender.lower()==cfg['username'].lower()
   data={'sender':str(msg.get('From','')),'subject':str(msg.get('Subject','')),'date':str(msg.get('Date','')),'body':decode_body(msg),'message_id':mid,'references':references,'classification':'自动回执' if auto else '自发邮件' if is_self and mid in refs else '关联回信','source':'IMAP真实读取'}
   with db() as conn:conn.execute('INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?)',(uid(),owner,key,linked,dump(data),now()))
   count+=1
   if linked=='self-test':
    if mid==test.get('message_id'):test['self_seen']=True
    elif test.get('message_id','!') in references:test['reply_seen']=True
    test['checked_at']=now();settings['mail_test']=test
   elif not is_self:
    update_state(owner,linked,'receipt_received' if auto else 'reply_received',{'last_message_id':mid,'source':'IMAP','note':'已收到关联邮件；是否面试/录用需阅读原文'})
  latest=get_settings(owner)
  if latest.get('mail_test',{}).get('message_id')==test.get('message_id'):
   latest['mail_test']=test
  latest['last_mail_poll']=now();save_settings(owner,latest)
 finally:
  try:c.logout()
  except Exception:pass
 return {'new':count,'mail_test':test,'checked_references':len(refs)}
