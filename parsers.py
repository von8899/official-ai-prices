"""Deterministic official-document parsers. Prices are USD per 1M tokens."""
import copy
import datetime as dt
import re

SOURCES = {
 'anthropic': {'pricing':'https://platform.claude.com/docs/en/about-claude/pricing.md',
               'lifecycle':'https://platform.claude.com/docs/en/about-claude/model-deprecations.md'},
 'openai': {'pricing':'https://developers.openai.com/api/docs/pricing.md',
            'lifecycle':'https://developers.openai.com/api/docs/models/all.md'},
 'gemini': {'pricing':'https://aistudio.google.com/docs/pricing',
            'lifecycle':'https://aistudio.google.com/docs/deprecations'},
}

def dollars(s):
 return [float(x.replace(',','')) for x in re.findall(r'\$([0-9]+(?:\.[0-9]+)?)',s)]

def cell(s):
 if s.strip()=='-':return None
 v=dollars(s)
 if len(v)!=1:raise ValueError('Unexpected monetary cell: '+s[:80])
 return v[0]

def record(meta,values,long=None,threshold=None):
 r=copy.deepcopy(meta);r.update(prices=values,long_prices=long,threshold=threshold)
 return r

def claude(docs,metas,today):
 s=docs['pricing'].split('## Model pricing',1)[1].split('\n## ',1)[0]
 assert 'Base input tokens' in s and '1h cache writes' in s and 'Output tokens' in s
 rows=[]
 for line in s.splitlines():
  if line.startswith('| Claude '):
   c=[x.strip() for x in line.strip('|').split('|')]
   if len(c)!=6:raise ValueError('Claude column count changed')
   rows.append((c[0],[cell(c[i]) for i in [1,5,4,2,3]]))
 states={}
 for line in docs['lifecycle'].splitlines():
  if line.lstrip().startswith('| claude-'):
   c=[x.strip() for x in line.strip('|').split('|')];states[c[0]]=c[1].lower()
 output=[]
 for meta in metas:
  parts=re.sub(r'-\d{8}$','',meta['name']).split('-')
  label='Claude '+parts[1].title()+' '+'.'.join(parts[2:])
  matches=[(title,v) for title,v in rows if title==label or title.startswith(label+' (')]
  if not matches:raise ValueError('Missing Claude price '+meta['name'])
  low=[v for title,v in matches if 'over ' not in title]
  high=[v for title,v in matches if 'over ' in title]
  if len(low)!=1 or len(high)>1:raise ValueError('Ambiguous Claude tiers '+label)
  r=record(meta,low[0],high[0] if high else None,100000 if high else None)
  state=states.get(meta['name'])
  if state:r['state']={'active':'current','deprecated':'deprecated','retired':'retired','legacy':'current'}.get(state,r['state'])
  output.append(r)
 return output

def openai(docs,metas,today):
 s=docs['pricing'];assert 'Prices per 1M tokens.' in s
 standard=s.split('### Standard pricing data',1)[1].split('### Batch pricing data',1)[0]
 parsed={}
 for line in standard.splitlines():
  c=[x.strip() for x in line.strip('|').split('|')]
  if not c[0].startswith(('gpt-','o3')):continue
  name=c[0].split(' ')[0]
  if len(c) not in [4,11]:raise ValueError('OpenAI standard columns changed')
  p=[cell(x) for x in c[1:]]
  parsed[name]=[p[:5] if len(p)==10 else p+[None,None],p[5:] if len(p)==10 else None]
 special=s.split('Specialized models',1)[1].split('### Grouped Pricing Table data',1)[1].split('### Grouped Pricing Table data',1)[0]
 for line in special.splitlines():
  c=[x.strip() for x in line.strip('|').split('|')]
  if len(c)!=7 or not c[1].startswith(('gpt-','chat-')):continue
  name=c[1].split(' ')[0];v=[cell(x) for x in c[2:]]
  if 'long context' in c[1]:
   if any(x is not None for x in v):parsed[name][1]=v
  else:parsed[name]=[v,None]
 output=[]
 for meta in metas:
  if meta['name'] not in parsed:raise ValueError('Missing OpenAI price '+meta['name'])
  low,high=parsed[meta['name']]
  if high and not meta.get('threshold'):raise ValueError('New unapproved context threshold '+meta['name'])
  r=record(meta,low,high,meta.get('threshold') if high else None)
  for line in docs['lifecycle'].splitlines():
   if '/'+meta['name']+'.md)' in line:
    if 'Shut down.' in line:r['state']='retired'
    elif 'Deprecated.' in line:r['state']='deprecated'
  output.append(r)
 return output

def dated_amounts(text,today):
 """Select text/normal-context amounts; never confuse hourly storage with cache reads."""
 choices=[]
 for match in re.finditer(r'\$([0-9]+(?:\.[0-9]+)?)([^$]*)',text):
  suffix=match.group(2);lower=suffix.lower()
  if 'storage' in lower or 'per hour' in lower:continue
  if '(audio)' in lower and 'text' not in lower:continue
  start=re.search(r'starting ([A-Z][a-z]+ \d{1,2}, \d{4})',suffix)
  end=re.search(r'through ([A-Z][a-z]+ \d{1,2}, \d{4})',suffix)
  parse=lambda m:dt.datetime.strptime(m.group(1),'%B %d, %Y').date() if m else None
  begin,until=parse(start),parse(end)
  if begin and today<begin or until and today>until:continue
  high=bool(re.search(r'prompts\s*>\s*200k',lower))
  choices.append((high,float(match.group(1))))
 low=[v for high,v in choices if not high];high=[v for high,v in choices if high]
 if len(low)!=1 or len(high)>1:raise ValueError('Ambiguous Gemini amount: '+text[:160])
 return low[0],high[0] if high else None

def markdoc_rows(block):
 table=block.split('{% table %}',1)[1].split('{% /table %}',1)[0]
 assert 'Paid Tier, per 1M tokens in USD' in table
 rows={}
 for row in re.split(r'\n\s*---\s*\n',table)[1:]:
  cells=re.split(r'(?m)^\s*\* ',row)[1:]
  if len(cells)!=3:raise ValueError('Gemini table shape changed')
  rows[cells[0].strip()]=re.sub(r'\s+',' ',cells[2]).strip()
 return rows

def gemini(docs,metas,today):
 sections={}
 for section in re.split(r'(?m)^## ',docs['pricing'])[1:]:
  m=re.search(r'\*\[\x60([^\x60]+)\x60\]',section)
  if m:sections[m.group(1)]=section
 output=[]
 for meta in metas:
  section=sections[meta['name']]
  block=section.split('{% tab title="Standard" %}',1)[1].split('{% /tab %}',1)[0]
  rows=markdoc_rows(block)
  fields=[]
  for label in ['Input price','Output price','Context caching price']:
   candidates=[v for k,v in rows.items() if k.startswith(label)]
   if len(candidates)!=1:raise ValueError('Missing Gemini '+label+' '+meta['name'])
   fields.append(candidates[0])
  pairs=[dated_amounts(v,today) for v in fields]
  low=[v[0] for v in pairs]+[None,None]
  high=[v[1] if v[1] is not None else v[0] for v in pairs]+[None,None] if any(v[1] is not None for v in pairs) else None
  r=record(meta,low,high,200000 if high else None)
  future=sorted(set(dt.datetime.strptime(x,'%B %d, %Y').date() for field in fields for x in re.findall(r'starting ([A-Z][a-z]+ \d{1,2}, \d{4})',field)))
  r['scheduled_prices']=[{'from':day.isoformat(),'prices':[dated_amounts(v,day)[0] for v in fields]+[None,None]} for day in future]
  if re.search(r'\x60'+re.escape(meta['name'])+r'\x60 is deprecated',docs['lifecycle']):r['state']='deprecated'
  output.append(r)
 # Officially announced December routing changes; retain ID, value it at the documented target's rate.
 by_name={x['name']:x for x in output}
 for name,target in [('gemini-2.5-pro','gemini-3.8-flash'),('gemini-2.5-flash','gemini-3.5-flash-lite')]:
  text=docs['lifecycle'];phrase='Effective December 1, 2026'
  if name in by_name and target in by_name and phrase in text and today>=dt.date(2026,12,1):
   # Both exact slugs must occur in the same published caution block.
   valid=any(name in b and target in b and phrase in b for b in text.split('{% callout'))
   if not valid:raise ValueError('Gemini migration source changed')
   r=by_name[name];other=by_name[target]
   r.update(prices=other['prices'],long_prices=other['long_prices'],threshold=other['threshold'],billed_as=target)
 return output

PARSERS={'anthropic':claude,'openai':openai,'gemini':gemini}
