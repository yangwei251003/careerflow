"""Build a read-only preview. Explicit allowlist; never export personal profiles or credentials."""
import sys,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from careerflow import core
from careerflow.catalog import CATALOG,PLATFORMS
from careerflow.matching import match

def main():
 site=ROOT/'site';site.mkdir(exist_ok=True)
 fixture=site/'demo-data.json'
 profile={'name':'林同学（虚构演示）','email':'demo@example.test','school':'示例大学（虚构）','education':'本科','major':'信息管理','graduation':'2028-06','skills':['Python','SQL','product','data','analysis'],'roles':['数据分析','产品实习'],'locations':['中国','上海'],'languages':['英语：阅读公开技术资料（虚构样例）'],'availability':'虚构档案，仅展示操作流程；不用于实际投递。','experience_years':0,'facts':[{'id':'demo-project','kind':'project','title':'课程数据分析项目（虚构）','org':'示例课程','dates':'2026.03—2026.06','text':'使用Python与SQL整理合成数据，定义产品指标并制作展示报告。','tags':'Python,SQL,product,data,analysis','evidence':'仅为产品演示而创建的虚构事实','verified':True},{'id':'demo-team','kind':'leadership','title':'课程项目协作（虚构）','org':'示例小组','dates':'2026.03—2026.06','text':'拆解小组任务，整理需求文档并组织演示反馈。','tags':'product,team','evidence':'虚构样例','verified':True}]}
 if '--refresh-public-jobs' in sys.argv:
  # Read only public job records from an explicitly named private QA account.
  account=json.loads((ROOT/'qa/private/live-account.json').read_text('utf-8'));owner=account['owner']
  with core.db() as c:
   user=c.execute('SELECT email FROM users WHERE id=?',(owner,)).fetchone()
   assert user and user['email'].endswith('@example.test'),'Only a fictional QA account is accepted'
   rows=c.execute('SELECT data FROM jobs WHERE owner=?',(owner,)).fetchall()
  selected=[];companies={}
  for row in rows:
   j=core.load(row['data']);company=j.get('company','')
   if j.get('kind')!='job' or companies.get(company,0)>=2 or not company:continue
   companies[company]=companies.get(company,0)+1
   keys=['title','company','location','salary','benefits','workplace','employment','published','deadline','url','apply_url','source_url','source_name','source_kind','checked_at','kind','status']
   clean={k:j.get(k,'') for k in keys};clean['evidence_level']='2026-11-11公开接口快照；现状请回原站复核'
   clean['description']='【公开快照摘要，非完整JD；请点原始来源查看完整要求】\n'+j.get('description','')[:160]
   selected.append({'id':'public-'+str(len(selected)+1),'data':clean,'match':match(profile,j)})
   if len(selected)>=12:break
  fixture.write_text(json.dumps({'profile':profile,'jobs':selected,'catalog':{'sources':CATALOG,'platforms':PLATFORMS}},ensure_ascii=False,indent=2),'utf-8')
 if not fixture.exists():raise SystemExit('No reviewed public fixture. Use the committed demo-data.json.')
 for name in ['app.js','style.css']:shutil.copyfile(ROOT/'web'/name,site/name)
 content=(ROOT/'web/index.html').read_text('utf-8').replace('<script src="app.js"','<script src="demo.js" defer></script><script src="app.js"')
 (site/'index.html').write_text(content,'utf-8');(site/'.nojekyll').touch()
 print('Read-only preview built; private files are excluded.')
if __name__=='__main__':main()
