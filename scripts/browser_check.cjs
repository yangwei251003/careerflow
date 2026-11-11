const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),crypto=require('crypto');
(async()=>{
 const qa=path.resolve(__dirname,'../qa/private');fs.mkdirSync(qa,{recursive:true});
 const b=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});const p=await b.newPage({viewport:{width:1440,height:1000}});let errors=[];p.on('pageerror',e=>errors.push(e.message));
 try{
  for(let n=0;n<20;n++){try{const h=await fetch('http://127.0.0.1:8769/api/health');if(h.ok)break}catch{}await new Promise(r=>setTimeout(r,1000))}
  await p.goto('http://127.0.0.1:8769');await p.getByText('第一次使用？创建账号').click();
  const email='qa-'+Date.now()+'@example.test',password=crypto.randomBytes(18).toString('hex');
  await p.locator('[name="name"]').fill('验收样例（虚构）');await p.locator('[name="email"]').fill(email);await p.locator('[name="password"]').fill(password);await p.locator('#auth-form button[type=submit]').click();
  await p.locator('[data-nav="profile"]').waitFor();await p.screenshot({path:path.join(qa,'dashboard.png')});
  await p.locator('[data-nav="settings"]').click();await p.locator('#settings-form').waitFor();
  if(await p.locator('[name="mail.username"]').inputValue()!==email)throw new Error('profile isolation form');
  await p.screenshot({path:path.join(qa,'settings.png'),fullPage:true});
  await p.locator('[data-nav="profile"]').click();await p.locator('[name="headline"]').fill('产品与数据分析实习');await p.locator('[name="education"]').selectOption('本科');await p.locator('[name="school"]').fill('示例大学（虚构测试）');await p.locator('[name="major"]').fill('计算机科学');await p.locator('[name="graduation"]').fill('2028-06');await p.locator('[name="skills"]').fill('Python,SQL,数据分析,product');await p.locator('[name="availability"]').fill('虚构验收档案，不用于真实企业投递');await p.locator('#profile-form button[type=submit]').click();
  await p.locator('[data-action="fact-add"]').click();await p.locator('[name="title"]').fill('课程数据分析项目（虚构测试）');await p.locator('[name="text"]').fill('使用Python与SQL整理课程样例数据，完成产品指标分析和展示文档。');await p.locator('[name="tags"]').fill('Python,SQL,product,data,analysis');await p.locator('[name="evidence"]').fill('验收专用虚构资料');await p.locator('[name="verified"]').check();await p.locator('#fact-form button').click();await p.locator('#fact-form').waitFor({state:'detached'});
  await p.locator('[data-nav="sources"]').click();await p.getByText('来源目录',{exact:true}).waitFor();await p.screenshot({path:path.join(qa,'sources.png'),fullPage:true});
  await p.locator('[data-action="catalog-add"][data-id="4"]').click();await p.locator('[data-action="source-pull"]').first().waitFor();await p.locator('[data-action="source-pull"]').first().click();
  let tasks=[];for(let i=0;i<45;i++){tasks=await p.evaluate(()=>fetch('/api/tasks').then(r=>r.json()));if(tasks.some(t=>t.state==='done'||t.state==='failed'))break;await p.waitForTimeout(1000)}
  if(!tasks.some(t=>t.state==='done'))throw new Error('live collection failed '+JSON.stringify(tasks));
  await p.locator('[data-nav="discover"]').click();await p.locator('[data-action="job-detail"]').first().waitFor();await p.screenshot({path:path.join(qa,'jobs.png'),fullPage:true});
  await p.locator('[data-action="job-detail"]').first().click();await p.locator('[data-action="job-resume"]').waitFor();await p.screenshot({path:path.join(qa,'job-detail.png')});await p.locator('[data-action="job-resume"]').click();await p.locator('[data-action="application-prepare"]').first().waitFor();await p.screenshot({path:path.join(qa,'resumes.png')});
  await p.locator('[data-action="application-prepare"]').first().click();await p.locator('[data-action="application-record"]').first().waitFor();await p.screenshot({path:path.join(qa,'applications.png')});
  const data=await p.evaluate(async()=>({me:await fetch('/api/me').then(r=>r.json()),jobs:await fetch('/api/jobs?limit=100').then(r=>r.json()),resumes:await fetch('/api/resumes').then(r=>r.json()),applications:await fetch('/api/applications').then(r=>r.json())}));
  await p.setViewportSize({width:390,height:844});await p.screenshot({path:path.join(qa,'mobile.png'),fullPage:true});
  const overflow=await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth);if(overflow)throw new Error('mobile horizontal overflow');
  if(errors.length)throw new Error(errors.join(';'));
  fs.writeFileSync(path.join(qa,'browser-result.json'),JSON.stringify({email,owner:data.me.id,jobCount:data.jobs.total,resumeCount:data.resumes.length,applicationCount:data.applications.length,applicationStates:data.applications.map(a=>a.state),errors,mobileOverflow:overflow},null,2));
  fs.writeFileSync(path.join(qa,'live-snapshot.json'),JSON.stringify(data,null,2));console.log(JSON.stringify({jobCount:data.jobs.total,resumeCount:data.resumes.length,applicationStates:data.applications.map(a=>a.state),errors,mobileOverflow:overflow}));
 }catch(e){await p.screenshot({path:path.join(qa,'failure.png'),fullPage:true});console.log('TOAST',await p.locator('#toast').innerText());console.log('PAGE ERRORS',errors);throw e}finally{await b.close()}
})().catch(e=>{console.error(e);process.exit(1)});
