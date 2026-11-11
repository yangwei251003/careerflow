// Synthetic account only. Does not send email or submit to an employer.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),crypto=require('crypto');
(async()=>{
 const qa=path.resolve(__dirname,'../qa/private');fs.mkdirSync(qa,{recursive:true});
 const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});
 const p=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];p.on('pageerror',e=>errors.push(e.message));
 const result={syntheticAccount:true,employerSubmissions:0,emailSends:0};
 try{
  await p.goto('http://127.0.0.1:8769');await p.getByText('第一次使用？创建账号').click();
  await p.locator('[name=name]').fill('导入验收（虚构）');await p.locator('[name=email]').fill('features-'+Date.now()+'@example.test');await p.locator('[name=password]').fill(crypto.randomBytes(18).toString('hex'));await p.locator('#auth-form button[type=submit]').click();
  await p.locator('[data-nav=profile]').click();await p.locator('[data-action=profile-import]').click();
  await p.locator('[name=resume_file]').setInputFiles({name:'synthetic-resume.txt',mimeType:'text/plain',buffer:Buffer.from('姓名：测试甲\n邮箱：sample@example.test\n测试大学 本科\n专业：信息管理\n预计毕业：2028年6月\n项目经历\n使用Python和SQL处理合成数据，整理分析报告。\n荣誉与证书\n课程演示优秀（虚构验收）')});
  await p.locator('#import-upload-form button[type=submit]').click();await p.locator('#import-confirm-form').waitFor();
  if(await p.locator('[name=use-email]').isChecked())throw Error('Import overwrites existing email by default');
  await p.screenshot({path:path.join(qa,'import-preview.png'),fullPage:true});await p.locator('#import-confirm-form button[type=submit]').click();await p.locator('#import-confirm-form').waitFor({state:'detached'});
  const before=await p.evaluate(()=>fetch('/api/profile').then(r=>r.json()));if(before.facts.length!==2||before.facts.some(f=>f.verified))throw Error('Imported facts must be drafts');result.importDrafts=2;
  await p.locator('[data-action=fact-edit]').first().click();await p.locator('[name=verified]').check();await p.locator('#fact-form button').click();await p.locator('#fact-form').waitFor({state:'detached'});
  const j=await p.evaluate(async()=>{const r=await fetch('/api/jobs/import',{method:'POST',headers:{'Content-Type':'application/json','X-CareerFlow':'1'},body:JSON.stringify({title:'数据分析实习（虚构验收）',company:'虚构验收公司',url:'https://example.com/careerflow-synthetic-test',description:'使用Python和SQL分析课程数据，需要解释实际项目职责及分析结果。',apply_url:'https://example.com/careerflow-synthetic-test'})});return r.json()});if(!j.id)throw Error(JSON.stringify(j));
  await p.locator('[data-nav=discover]').click();await p.locator('[data-action=job-detail]').first().click();await p.locator('[data-action=job-resume]').click();await p.locator('[name=export-resume]').first().check();
  const [zip]=await Promise.all([p.waitForEvent('download'),p.locator('[data-action=resumes-export]').click()]);await zip.saveAs(path.join(qa,'features-resumes.zip'));result.zipDownloaded=true;
  await p.locator('[data-action=application-prepare]').first().click();const [csv]=await Promise.all([p.waitForEvent('download'),p.locator('[data-action=applications-export]').click()]);await csv.saveAs(path.join(qa,'features-applications.csv'));result.csvDownloaded=true;
  if(process.argv.includes('--local-ai')){
   await p.locator('[data-nav=settings]').click();await p.locator('[name="llm.provider"]').selectOption('ollama');
   if(!(await p.locator('[name="llm.key"]').isDisabled()))throw Error('Local key field not disabled');
   await p.locator('[data-action=test-model]').click();await p.locator('#model-status').filter({hasText:'已真实响应'}).waitFor({timeout:180000});
   await p.locator('[data-action=local-models]').click();await p.locator('#model-status').filter({hasText:'qwen3.5:4b'}).waitFor();
   await p.screenshot({path:path.join(qa,'local-ai-settings.png'),fullPage:true});
   await p.locator('[data-nav=discover]').click();await p.locator('[data-action=job-detail]').first().click();await p.locator('[data-action=job-advice]').click();
   await p.locator('[data-action=advice-resume]').waitFor({timeout:180000});await p.screenshot({path:path.join(qa,'local-ai-advice.png'),fullPage:true});
   result.localAdviceText=await p.locator('[role=dialog]').innerText();await p.locator('[data-action=advice-resume]').click();await p.locator('[name=export-resume]').first().waitFor();result.localModelActual=true;
  }
  // This section exercises UI polling only. The QQ provider evidence is independent.
  await p.route('**/api/settings',route=>route.request().method()==='GET'?route.fulfill({json:{llm:{provider:'ollama',base_url:'http://127.0.0.1:11434',model:'qwen3.5:4b'},mail:{},mail_test:{smtp:'accepted',self_seen:true,reply_seen:true}}}):route.continue());
  await p.route('**/api/mail/poll',route=>route.fulfill({json:{task_id:'ui-stub-only'}}));
  await p.route('**/api/tasks/ui-stub-only',route=>route.fulfill({json:{state:'done',result:{new:0}}}));
  await p.locator('[data-nav=settings]').click();await p.locator('[name="search.key"]').fill('unsaved-test-text');await p.locator('[data-action=mail-poll]').click();await p.locator('#toast').filter({hasText:'同步完成'}).waitFor();
  if(await p.locator('[name="search.key"]').inputValue()!=='unsaved-test-text')throw Error('Sync erased unsaved fields');result.mailPollingUiStub=true;
  await p.setViewportSize({width:390,height:844});await p.screenshot({path:path.join(qa,'features-mobile.png'),fullPage:true});result.mobileOverflow=await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth);result.errors=errors;
  if(result.mobileOverflow||errors.length)throw Error('UI regression '+JSON.stringify({overflow:result.mobileOverflow,errors}));
  fs.writeFileSync(path.join(qa,'features-browser-result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({...result,localAdviceText:result.localAdviceText?'captured in private QA':undefined}));
 }catch(e){await p.screenshot({path:path.join(qa,'features-failure.png'),fullPage:true});console.log('TOAST',await p.locator('#toast').innerText());throw e}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
