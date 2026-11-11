'use strict';
window.CAREERFLOW_DEMO=true;
const demoData=fetch('demo-data.json').then(r=>r.json());
window.demoApi=async function(path,method='GET'){
 if(method!=='GET')throw new Error('这是公开只读演示，不保存信息或调用外部服务。请下载并运行本机版。');
 const d=await demoData,p=d.profile,first=d.jobs[0],stamp=first?.data.checked_at||0;
 const resumes=first?[{id:'demo-resume',job_id:first.id,created:stamp,data:{company:first.data.company,job_title:first.data.title+' · 材料演示',fact_ids:p.facts.map(f=>f.id),analysis:first.match}}]:[];
 const applications=first?[{id:'demo-application',job_id:first.id,resume_id:'demo-resume',state:'prepared',updated:stamp,data:{company:first.data.company,job_title:first.data.title,apply_url:first.data.apply_url,source:'虚构演示，未投递',note:'此条仅展示工作台布局，没有发送申请或代表企业回执。'}}]:[];
 if(path==='/me')return {id:'demo-only',name:p.name,email:p.email};
 if(path==='/profile')return p;
 if(path==='/dashboard')return {counts:{jobs:d.jobs.length,resumes:resumes.length,applications:applications.length,messages:0,submitted:0,sources:0},events:[]};
 if(path==='/tasks')return [];
 if(path==='/sources')return [];
 if(path==='/catalog')return d.catalog;
 if(path==='/resumes')return resumes;
 if(path==='/applications')return applications;
 if(path==='/messages')return [];
 if(path==='/settings')return {llm:{},search:{},mail:{}};
 if(path.startsWith('/jobs?')){
  const q=new URLSearchParams(path.split('?')[1]),query=(q.get('q')||'').toLowerCase();
  const all=d.jobs.filter(r=>(!q.get('kind')||r.data.kind===q.get('kind'))&&(!q.get('verdict')||r.match.verdict===q.get('verdict'))&&JSON.stringify(r.data).toLowerCase().includes(query));
  const offset=Number(q.get('offset')||0);return {total:all.length,items:all.slice(offset,offset+40).map(r=>({...r,data:{...r.data,excerpt:r.data.description}}))};
 }
 if(path.startsWith('/jobs/')){
  const j=d.jobs.find(r=>r.id===path.split('/')[2]);if(!j)throw new Error('演示岗位不存在');
  if(path.endsWith('/interview'))return {job_title:j.data.title,company:j.data.company,questions:['结合本人真实经历说明如何理解岗位职责。','准备一个能说明个人贡献的项目，清楚区分团队和个人工作。'],ask_employer:['核对工作地点、到岗时间、薪酬构成和考核要求。'],note:'虚构档案的演示提纲，不是已发生的面试。'};
  return j;
 }
 throw new Error('此功能需在本机完整应用中使用。');
};
