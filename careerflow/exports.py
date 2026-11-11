from __future__ import annotations
import io,csv,zipfile,re,json,datetime
from . import core

def resume_archive(owner,ids,formats=None):
 if not isinstance(ids,list) or not ids or len(ids)>30 or not all(isinstance(x,str) for x in ids):raise ValueError('请选择1—30份属于当前账号的简历')
 formats=formats or ['pdf','docx']
 if not isinstance(formats,list) or not formats or any(x not in {'pdf','docx','txt'} for x in formats):raise ValueError('导出格式仅支持PDF、DOCX、TXT')
 files=[];manifest=[];total=0
 for index,id in enumerate(dict.fromkeys(ids),1):
  r=core.owned('resumes',id,owner)
  label=re.sub(r'[^\w\-\u4e00-\u9fff]','_',r['data'].get('company','')+'_'+r['data'].get('job_title','Resume'))[:80]
  for fmt in dict.fromkeys(formats):
   p=core.DATA/'artifacts'/owner/id/('resume.'+fmt)
   if not p.is_file():raise ValueError('所选简历存在缺失附件，请重新生成后再打包')
   total+=p.stat().st_size
   if total>50_000_000:raise ValueError('所选文件超过50MB，请分批下载')
   name=f'{index:02d}_{label}/{"resume."+fmt}';files.append((name,p))
  manifest.append({'company':r['data'].get('company'),'job_title':r['data'].get('job_title'),'resume_id':id,'job_id':r['job_id'],'confirmed_fact_ids':r['data']['fact_ids']})
 result=io.BytesIO()
 with zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED) as z:
  for name,p in files:z.write(p,name)
  z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
 return result.getvalue()

def csv_cell(value):
 text=str(value if value is not None else '')
 return "'"+text if text.lstrip().startswith(('=','+','-','@')) else text

def application_csv(owner):
 with core.db() as c:
  rows=c.execute('SELECT a.*,j.data AS job_data FROM applications a LEFT JOIN jobs j ON j.id=a.job_id AND j.owner=a.owner WHERE a.owner=? ORDER BY a.updated DESC',(owner,)).fetchall()
 out=io.StringIO(newline='');writer=csv.writer(out)
 writer.writerow(['企业','岗位','申请状态','工作地点','薪资原文','福利原文','公开截止日期','原始来源','投递入口','状态记录来源','回执或说明','最后更新时间（北京时间）'])
 labels={'prepared':'材料已备好','smtp_accepted':'发送服务器已接受','reported_submitted':'本人记录已提交','receipt_received':'收到自动回执','reply_received':'收到关联回信','interview':'面试中','offer':'已获Offer','rejected':'已结束','withdrawn':'已撤回','sending':'正在发送','send_failed':'发送未成功','send_unknown':'发送结果未知'}
 for row in rows:
  a=core.load(row['data']);j=core.load(row['job_data'])
  values=[a.get('company'),a.get('job_title'),labels.get(row['state'],row['state']),j.get('location','未披露'),j.get('salary','未披露'),j.get('benefits','未披露'),j.get('deadline') or '未披露',j.get('url'),a.get('apply_url'),a.get('source','平台准备'),a.get('receipt') or a.get('note',''),datetime.datetime.fromtimestamp(row['updated'],datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')]
  writer.writerow([csv_cell(v) for v in values])
 return out.getvalue().encode('utf-8-sig')
