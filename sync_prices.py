"""Publish tiny, content-addressed price snapshots. No provider credentials or model calls."""
import argparse,datetime as dt,hashlib,json,math,re,urllib.request,urllib.error
from pathlib import Path
from parsers import SOURCES,PARSERS
ROOT=Path(__file__).resolve().parent
ALLOWED={'platform.claude.com','developers.openai.com','aistudio.google.com','ai.google.dev'}
from urllib.parse import urlparse
class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  if urlparse(newurl).hostname not in ALLOWED or not newurl.startswith('https://'):raise ValueError('Unapproved source redirect')
  return super().redirect_request(req,fp,code,msg,headers,newurl)

def encoded(obj):return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
def digest(obj):return hashlib.sha256(encoded(obj)).hexdigest()
def write(path,obj):
 path.parent.mkdir(parents=True,exist_ok=True)
 key='records' if isinstance(obj,dict) and 'records' in obj else 'models' if isinstance(obj,dict) and 'models' in obj else None
 if key:
  head={k:v for k,v in obj.items() if k!=key}
  text=json.dumps(head,ensure_ascii=False,separators=(',',':'))[:-1]+',"'+key+'":[\n'+',\n'.join(json.dumps(r,ensure_ascii=False,separators=(',',':')) for r in obj[key])+'\n]}\n'
 else:text=json.dumps(obj,ensure_ascii=False,indent=2)+'\n'
 with path.open('w',encoding='utf-8',newline='\n') as f:
  for line in text.splitlines(keepends=True):
   for i in range(0,len(line),8000):f.write(line[i:i+8000])

def fetch(url):
 if urlparse(url).hostname not in ALLOWED or not url.startswith('https://'):raise ValueError('Source not allowed')
 req=urllib.request.Request(url,headers={'User-Agent':'OfficialPriceSync/1.0 (+https://github.com/von8899/official-ai-prices)','Accept':'text/markdown,text/plain;q=0.9'})
 with urllib.request.build_opener(RestrictedRedirect).open(req,timeout=25) as response:
  b=response.read(1_000_001)
  if len(b)>1_000_000:raise ValueError('Source exceeded byte budget')
  return b.decode('utf-8')

def validate(catalog,registry):
 rows=catalog['records'];expected={m['name'] for m in registry}
 assert len(rows)==len(expected) and {r['name'] for r in rows}==expected,'Registry coverage changed'
 for r in rows:
  assert re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,100}',r['name'])
  assert r['platform'] in SOURCES and r['state'] in ['current','preview','deprecated','retired']
  assert catalog['sources'][r['platform']]==SOURCES[r['platform']]['pricing']
  assert r.get('threshold') in [None,100000,200000,272000]
  assert bool(r.get('long_prices'))==bool(r.get('threshold'))
  for values in [r['prices']]+([r['long_prices']] if r.get('long_prices') else []):
   assert len(values)==5
   for v in values:assert v is None or type(v) in [int,float] and math.isfinite(v) and 0<=v<=1000
   assert values[0] is not None and values[0]>0 and values[1] is not None and values[1]>0
 return True

def review_reasons(old,new,today):
 before={r['name']:r for r in old['records']};reasons=[]
 for row in new['records']:
  previous=before[row['name']];scheduled=any(e['from']<=today.isoformat() and e['prices']==row['prices'] for e in previous.get('scheduled_prices',[]))
  routed=row['platform']=='gemini' and row.get('billed_as') in ['gemini-3.8-flash','gemini-3.5-flash-lite'] and today>=dt.date(2026,12,1)
  for field in ['threshold','scheduled_prices','billed_as']:
   if previous.get(field)!=row.get(field) and not routed:reasons.append(row['name']+': structural '+field)
  for field in ['prices','long_prices']:
   a,b=previous.get(field),row.get(field)
   if a is None or b is None:
    if a!=b and not routed:reasons.append(row['name']+': tier shape')
    continue
   for i,(x,y) in enumerate(zip(a,b)):
    if x==y:continue
    if x is None or y is None:
     reasons.append(row['name']+': component availability');continue
    if not scheduled and not routed and (x==0 or abs(y-x)/x>0.20):reasons.append(row['name']+': >20% '+field+'['+str(i)+']')
 return sorted(set(reasons))

def build(registry,sources,today):
 rows=[]
 for provider in SOURCES:
  rows.extend(PARSERS[provider](sources[provider],[m for m in registry if m['platform']==provider],today))
 for row in rows:
  for key in ['long_prices','threshold']:
   if row.get(key) is None:row.pop(key,None)
  if row.get('note') in ['公开','官网当前列售'] or row['platform']=='gemini':row.pop('note',None)
 result={'schema':1,'currency':'USD','unit':'per_1m_tokens','mode':'standard_text_api_equivalent','sources':{p:v['pricing'] for p,v in SOURCES.items()},'records':sorted(rows,key=lambda r:(r['platform'],r['name']))}
 validate(result,registry);return result

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source-dir');ap.add_argument('--bootstrap',action='store_true');ap.add_argument('--as-of');args=ap.parse_args()
 now=dt.datetime.now(dt.timezone.utc);today=dt.date.fromisoformat(args.as_of) if args.as_of else now.date()
 registry=json.loads((ROOT/'registry.json').read_text(encoding='utf-8'))['models'];data=ROOT/'data';data.mkdir(exist_ok=True)
 old=json.loads((data/'current.json').read_text(encoding='utf-8')) if (data/'current.json').exists() else None
 previous=json.loads((data/'manifest.json').read_text(encoding='utf-8')) if (data/'manifest.json').exists() else {}
 manifest={'schema':1,'checked_at':now.isoformat(),'verified_at':previous.get('verified_at'),'status':'checking',
           'catalog_path':previous.get('catalog_path'),'sha256':previous.get('sha256'),'model_count':len(registry),'pending_count':0}
 try:
  documents={}
  filenames={'anthropic':{'pricing':'claude-pricing.txt','lifecycle':'claude-lifecycle.txt'},
             'openai':{'pricing':'openai-pricing.md','lifecycle':'openai-models-all.md'},
             'gemini':{'pricing':'gemini-pricing.md','lifecycle':'gemini-deprecations.md'}}
  for provider,urls in SOURCES.items():
   documents[provider]={key:(Path(args.source_dir)/filenames[provider][key]).read_text(encoding='utf-8') if args.source_dir else fetch(url) for key,url in urls.items()}
  candidate=build(registry,documents,today);sha=digest(candidate)
  reasons=review_reasons(old,candidate,today) if old else []
  policy=json.loads((ROOT/'policy.json').read_text(encoding='utf-8'))
  if reasons and sha not in policy['approved_catalog_hashes']:
   write(data/'pending.json',{'candidate_hash':sha,'checked_at':now.isoformat(),'reasons':reasons,'candidate':candidate})
   manifest.update(status='review_required',pending_count=len(reasons));write(data/'manifest.json',manifest)
   print('REVIEW_REQUIRED',len(reasons));return 0
  if old is None and not args.bootstrap:raise ValueError('Initial catalog requires reviewed bootstrap')
  path='catalog.'+sha+'.json';payload=encoded(candidate)
  with (data/path).open('wb') as f:
   for i in range(0,len(payload),8000):f.write(payload[i:i+8000])
  write(data/'current.json',candidate)
  write(data/'pending.json',{'pending_count':0})
  manifest.update(status='ok',verified_at=now.isoformat(),catalog_path=path,sha256=sha)
  write(data/'manifest.json',manifest)
  print('VERIFIED',len(registry),'models',len(payload),'bytes',sha)
  return 0
 except Exception as e:
  manifest.update(status='source_error',error=type(e).__name__+': '+str(e)[:200]);write(data/'manifest.json',manifest)
  print('SOURCE_ERROR',type(e).__name__,str(e)[:160]);return 1
if __name__=='__main__':raise SystemExit(main())
