"""Local, deterministic resume extraction. Imported experience is never auto-confirmed."""
from __future__ import annotations
import io,re,zipfile,xml.etree.ElementTree as ET
from pathlib import Path
from .core import uid

MAX_FILE=4_000_000
HEADINGS={
 '工作经历':'work','工作经验':'work','实习经历':'work','工作与实习':'work','实习经验':'work','workexperience':'work','experience':'work',
 '项目经历':'project','项目经验':'project','相关项目':'project','代表项目':'project','projects':'project',
 '校园经历':'leadership','组织与实践':'leadership','社会实践':'leadership','学生工作':'leadership','leadership':'leadership',
 '荣誉奖项':'award','获奖情况':'award','荣誉与资格':'award','荣誉与证书':'award','荣誉':'award','证书':'award','awards':'award','certifications':'award',
 '教育背景':'education','教育经历':'education','education':'education','个人信息':'basic','基本信息':'basic',
 '专业技能':'project','技能':'project','相关能力':'project','skills':'project','语言与到岗安排':'basic','自我评价':'basic'}

def extract_document(filename,content):
 if not content or len(content)>MAX_FILE:raise ValueError('请选择不超过4MB的PDF、DOCX或TXT简历')
 ext=Path(filename).suffix.lower();pages=None
 try:
  if ext=='.txt':
   try:text=content.decode('utf-8-sig')
   except UnicodeDecodeError:text=content.decode('gb18030')
  elif ext=='.docx':
   with zipfile.ZipFile(io.BytesIO(content)) as z:
    if len(z.infolist())>1000 or sum(x.file_size for x in z.infolist())>30_000_000:raise ValueError('Word解压后过大，请另存为精简简历')
    data=z.read('word/document.xml')
    if b'<!DOCTYPE' in data or b'<!ENTITY' in data:raise ValueError('Word文档包含不支持的XML声明')
    root=ET.fromstring(data);ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    text='\n'.join(''.join(t.text or '' for t in p.iter(ns+'t')) for p in root.iter(ns+'p'))
  elif ext=='.pdf':
   from pypdf import PdfReader
   reader=PdfReader(io.BytesIO(content))
   if reader.is_encrypted:raise ValueError('请先用自己的密码打开PDF，并另存为不加密版本后导入')
   pages=len(reader.pages)
   if pages>16:raise ValueError('请导入16页以内的简历，证明材料无需放入简历原文')
   parts=[]
   for page in reader.pages:
    stream=page.get_contents()
    if stream is not None and len(stream.get_data())>2_000_000:raise ValueError('PDF页面内容过于复杂，请改用Word或精简PDF')
    parts.append(page.extract_text() or '')
   text='\n'.join(parts)
  else:raise ValueError('支持PDF、DOCX和TXT；旧版DOC请另存为DOCX')
 except ValueError:raise
 except Exception:raise ValueError('无法解析此文件，请检查文件是否损坏，或另存为DOCX/TXT后重试') from None
 text=text.replace('\x00','').replace('\r\n','\n').strip()
 if len(text)<12:raise ValueError('没有取得足够文字；扫描版或纯图片PDF请改用可复制文字的PDF、Word或TXT')
 if len(text)>40000:raise ValueError('简历文字超过4万字，请先移除证明附件和重复内容')
 return text,pages

def preview_resume(filename,content):
 text,pages=extract_document(filename,content);suggested={};lines=[s.strip() for s in text.splitlines() if s.strip()]
 found=re.search(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}',text)
 if found:suggested['email']=found[0]
 found=re.search(r'(?<!\d)(?:\+86[ -]?)?(1[3-9]\d{9})(?!\d)',text)
 if found:suggested['phone']=found[1]
 found=re.search(r'(?:姓名|Name)\s*[:：]\s*([^\n|｜·]{2,40})',text,re.I)
 if found:suggested['name']=found[1].strip()
 elif re.fullmatch(r'[\u4e00-\u9fff]{2,4}',lines[0]) and not any(x in lines[0] for x in ['简历','求职','姓名','信息']):suggested['name']=lines[0]
 found=re.search(r'([\u4e00-\u9fff]{2,25}(?:大学|学院))',text)
 if found:suggested['school']=found[1]
 for level in ['博士','硕士','本科','大专','中专','高中']:
  if level in text:suggested['education']=level;break
 found=re.search(r'专业\s*[:：]\s*([^\n|｜·]{2,45})',text)
 if found:suggested['major']=found[1].strip()
 found=re.search(r'(?:预计毕业|毕业时间|毕业日期|毕业)\s*[:：]?\s*(20\d{2})[年./-](\d{1,2})',text)
 if found and 1<=int(found[2])<=12:suggested['graduation']=found[1]+'-'+found[2].zfill(2)
 sections=[];current=None
 for line in lines:
  key=re.sub(r'[\s:：|｜·•]','',line).lower()
  if key in HEADINGS:
   current={'kind':HEADINGS[key],'title':line,'lines':[]};sections.append(current)
  elif current is not None:current['lines'].append(line)
 facts=[];warning=['这是本机规则提取结果，请对照原文核对基本信息与经历；未使用模型服务。','导入的经历默认“待确认”，不会直接进入自动生成的简历。']
 for section in sections:
  if section['kind'] in {'basic','education'} or not section['lines']:continue
  block='\n'.join(section['lines'])
  if len(block)>4000:warning.append('部分经历段落超过4000字，已截短；请对照原文拆分补齐。')
  facts.append({'id':uid(),'kind':section['kind'],'title':section['title'],'org':'','dates':'','text':block[:4000],'tags':'','evidence':'导入文件：'+Path(filename).name[:150],'verified':False})
 if not facts:
  facts=[{'id':uid(),'kind':'project','title':'导入原文（待分类）','org':'','dates':'','text':text[:4000],'tags':'','evidence':'导入文件：'+Path(filename).name[:150],'verified':False}]
  warning.append('未识别到常用经历标题，已暂存原文；请拆分为具体工作、项目、荣誉。')
 if len(facts)>20:warning.append('仅展示前20段经历，请对照原文补齐。')
 return {'suggested':suggested,'facts':facts[:20],'text':text,'pages':pages,'warnings':warning,'filename':Path(filename).name[:180]}
