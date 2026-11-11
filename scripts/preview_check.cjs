const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),http=require('http');
(async()=>{
 const root=path.resolve(__dirname,'../site'),qa=path.resolve(__dirname,'../qa/private');fs.mkdirSync(qa,{recursive:true});
 const server=http.createServer((req,res)=>{const name=req.url.split('?')[0]==='/'?'index.html':req.url.split('?')[0].slice(1);const file=path.resolve(root,name);if(!file.startsWith(root+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end()}res.setHeader('Content-Type',({'.html':'text/html','.js':'application/javascript','.css':'text/css','.json':'application/json'})[path.extname(file)]||'text/plain');res.end(fs.readFileSync(file));});
 await new Promise(r=>server.listen(8770,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'msedge'}:{})});const page=await browser.newPage({viewport:{width:1440,height:1000}});let errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto('http://127.0.0.1:8770');await page.locator('.hero').waitFor();
  await page.screenshot({path:path.join(qa,'public-dashboard.png')});
  for(const nav of ['profile','discover','sources','resumes','applications','messages','settings']){await page.locator(`[data-nav="${nav}"]`).click();await page.locator('.pagehead').waitFor();if(await page.locator('.error-block').count())throw new Error('Preview error: '+nav)}
  await page.locator('[data-nav="discover"]').click();await page.locator('[data-action="job-detail"]').first().click();await page.locator('[role="dialog"]').waitFor();await page.locator('[data-action="job-resume"]').click();await page.waitForTimeout(100);if(!(await page.locator('#toast').innerText()).includes('只读'))throw new Error('Demo write protection absent');await page.keyboard.press('Escape');
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(qa,'public-mobile.png'),fullPage:true});const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);if(overflow||errors.length)throw new Error(JSON.stringify({overflow,errors}));
  fs.writeFileSync(path.join(qa,'preview-result.json'),JSON.stringify({pages:8,readOnly:true,mobileOverflow:overflow,errors},null,2));console.log('Preview: 8 pages, read-only write rejection, mobile without overflow; no page errors.');
 }finally{await browser.close();server.close()}
})().catch(e=>{console.error(e);process.exit(1)});
