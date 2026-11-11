from __future__ import annotations
import datetime as dt,re
from .core import now

def tokens(s):
 words=re.findall(r'[a-zA-Z][a-zA-Z0-9+#.-]{1,}|[\u4e00-\u9fff]{2,}',str(s).lower())
 out=set()
 for w in words:
  out.add(w)
  if re.fullmatch(r'[\u4e00-\u9fff]+',w) and len(w)>3:
   out.update(w[n:n+2] for n in range(len(w)-1))
 return out

def constraints(job):
 s=job.get('title','')+'\n'+job.get('description','')
 years=set(int(x) for x in re.findall(r'(20\d{2})\s*届',s))
 years.update(2000+int(x) for x in re.findall(r'(?<!\d)(2[0-9])届',job.get('title','')))
 # Graduation month windows remain quoted evidence; never reduce them to a year-only pass.
 graduation_windows=[]
 for line in s.splitlines():
  if not re.search(r'graduat|毕业|class of',line,re.I):continue
  gy=set(int(x) for x in re.findall(r'20\d{2}',line))
  if not gy:continue
  if len(gy)==1 and re.search(r'graduat|class of',line,re.I):years.update(gy)
  if len(gy)>1 or re.search(r'\d+月|20\d{2}[-/]\d|January|February|March|April|May|June|July|August|September|October|November|December|between',line,re.I):graduation_windows.append(line.strip())
 graduation_windows=graduation_windows[:5]
 required_exp=[]
 for line in s.splitlines():
  if re.search(r'preferred|nice to have|bonus|优先|加分',line,re.I):continue
  for pattern in [r'(\d+)\s*(?:[-–~至]\s*\d+)?\s*年(?:及以上|以上)?(?:相关)?(?:工作|行业|岗位)?经验',r'(?:at least|minimum of)\s*(\d+)\s*(?:years?|yrs?)',r'(\d+)\+?\s*(?:[-–]|to)?\s*\d*\s*years?(?:\s+of)?(?:\s+[a-z/-]+){0,5}\s+experience']:
   required_exp.extend(int(x) for x in re.findall(pattern,line,re.I))
 degree=None
 if re.search(r'博士(?:及以上|学历|学位)|(?:Ph\.?D\.?|doctorate)\s+(?:required|degree required)',s,re.I):degree='博士'
 elif re.search(r'硕士(?:及以上|学历)|master.?s? degree required',s,re.I):degree='硕士'
 elif re.search(r'本科(?:及以上|学历)|bachelor.?s? degree (?:is )?required',s,re.I):degree='本科'
 return {'graduation_years':sorted(years),'graduation_windows':graduation_windows,'experience_min':max(required_exp) if required_exp else None,'degree_min':degree}

def match(profile,job):
 gates=[];warnings=[];c=constraints(job)
 if job.get('status')=='closed':gates.append('来源已关闭或完整列表已移除该岗位')
 deadline=job.get('deadline','')
 if deadline:
  try:
   if dt.date.fromisoformat(str(deadline)[:10])<dt.datetime.now(dt.timezone.utc).date():gates.append('公开截止日期已过')
  except ValueError:warnings.append('截止时间需按来源原文确认')
 grad=re.match(r'20\d{2}',profile.get('graduation',''))
 if c['graduation_years']:
  if grad and int(grad[0]) not in c['graduation_years']:gates.append('毕业届别不符：岗位要求'+','.join(map(str,c['graduation_years'])))
  elif not grad:warnings.append('岗位限定毕业届别，档案未填写毕业年份')
 if c['graduation_windows']:warnings.append('存在毕业日期原文要求，请核对月份与范围')
 levels={'高中':1,'中专':1,'大专':2,'本科':3,'硕士':4,'博士':5}
 if c['degree_min']:
  value=profile.get('education','')
  if value in levels and levels[value]<levels[c['degree_min']]:gates.append('学历低于岗位明确要求：'+c['degree_min'])
  elif value not in levels:warnings.append('请补充学历以核对岗位要求')
 if c['experience_min'] is not None and profile.get('experience_years',0)<c['experience_min']:gates.append(f"正式相关经验低于原文要求：{c['experience_min']}年")
 if job.get('kind')!='job':warnings.append('目前是网页/搜索线索，单岗与申请入口尚未核实')
 if job.get('status')=='needs_review':warnings.append('职位当前状态仍待核验')
 if not job.get('apply_url'):warnings.append('尚无已核对的单岗申请入口')
 if now()-float(job.get('checked_at',0))>86400:warnings.append('已超过24小时，提交前需要重新核验')
 if not profile.get('availability'):warnings.append('可到岗时间与出勤尚未填写')
 locations=profile.get('locations',[]);where=job.get('location','').lower()
 if locations and not any(x.lower() in {'不限','全国','全球','anywhere','worldwide','remote','远程'} for x in locations):
  aliases={'上海':['shanghai'],'北京':['beijing'],'深圳':['shenzhen'],'广州':['guangzhou'],'中国':['china','shanghai','beijing','shenzhen','guangzhou','上海','北京','深圳','广州','中国']}
  accepted=[v.lower() for loc in locations for v in [loc]+aliases.get(loc,[])]
  if not any(v in where for v in accepted):warnings.append('地点未与已填写的意向匹配；请确认异地/远程及工作资格')
 description=job.get('description','')
 if re.search(r'visa|sponsorship|work authori[sz]|citizenship|工作许可|国籍要求',description,re.I):warnings.append('原文包含工作许可/签证要求，需要按本人资格核对')
 if re.search(r'执照|资格证|职业资格|license required|certification required',description,re.I):warnings.append('原文包含证照要求，请逐项核对有效证书')
 if c['experience_min'] is None and re.search(r'years? (?:of )?(?:relevant )?experience|工作经验',description,re.I):warnings.append('经验细则需核对原文，尚未解析为确定门槛')
 if re.search(r'(?:fluent|proficien\w*|excellent).{0,30}(?:English|Mandarin|German|French)|英语.{0,12}(?:流利|熟练)|CET[- ]?6|IELTS',description,re.I):warnings.append('原文包含语言水平要求，不能仅凭技能关键词判定满足')
 jt=tokens(job.get('title','')+' '+job.get('description',''))
 facts=[]
 for f in profile.get('facts',[]):
  if not f.get('verified'):continue
  overlap=tokens(f.get('title','')+' '+f.get('tags','')+' '+f.get('text','')) & jt
  facts.append({'id':f['id'],'title':f.get('title',''),'terms':sorted(overlap)[:12],'overlap':len(overlap)})
 facts.sort(key=lambda f:f['overlap'],reverse=True)
 skillhits=[s for s in profile.get('skills',[]) if s.lower() in job.get('description','').lower() or s.lower() in job.get('title','').lower()]
 missing=[s for s in profile.get('skills',[]) if s not in skillhits]
 relevance=min(100,len(skillhits)*12+sum(min(f['overlap'],10) for f in facts[:4])*2)
 if not facts:warnings.append('尚无本人确认的经历事实，不能生成有依据的简历')
 return {'verdict':'blocked' if gates else 'review' if warnings else 'candidate','gates':gates,'warnings':warnings,'constraints':c,'evidence':facts,'skill_hits':skillhits,'profile_skills_not_seen':missing,'relevance':relevance,'note':'覆盖度只衡量已确认事实与文字关联，不是录用概率；签证、语言、专业细则仍需核对原文。'}
