"""Guard the public file list. Reports paths/categories, never matched credential values."""
import argparse,json,re,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--git',default='git');args=p.parse_args()
ROOT=Path(__file__).resolve().parents[1]
files=subprocess.check_output([args.git,'ls-files','-z'],cwd=ROOT).decode('utf-8').split('\0');files=[f for f in files if f]
issues=[]
for name in files:
 path=ROOT/name
 if name.startswith(('data/','qa/','private/','.venv/','node_modules/')) or path.suffix in {'.key','.pem','.sqlite','.log'}:issues.append((name,'private runtime path'))
 if path.suffix.lower()=='.png':continue
 text=path.read_text('utf-8-sig')
 for pattern,label in [(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY','private key'),(r'\b(?:ghp_|github_pat_|sk-proj-)[A-Za-z0-9_\-]{20,}','credential pattern'),(r'(?i)\b(?:password|api_key|token)\s*=\s*[\"\x27][A-Za-z0-9_\-]{30,}[\"\x27]','hardcoded credential'),(r'C:[/\\]Users[/\\]','machine-specific user path')]:
  if re.search(pattern,text):issues.append((name,label))
 if name=='site/demo-data.json':
  d=json.loads(text);assert d['profile']['email'].endswith('@example.test')
  assert '虚构' in d['profile']['name']
  assert all(len(j['data']['description'])<240 and j['data']['url'].startswith('https://') for j in d['jobs'])
  assert not any(k in text for k in ['mail_test','smtp_host','imap_password','api_key'])
if issues:
 print(json.dumps({'issues':issues},ensure_ascii=False));sys.exit(1)
print(json.dumps({'tracked_files':len(files),'private_paths_or_credential_patterns':0,'public_demo':'fictional profile and bounded public excerpts'},ensure_ascii=False))
