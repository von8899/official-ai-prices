"""Official text-model inventory; dates alone never prove retirement."""
import re
from parsers import SOURCES
MEDIA=('image','audio','realtime','live','tts','transcribe','embedding','video','omni','robotics','decision','banana','computer-use')
def in_scope(provider,name):
 if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,100}',name):return False
 if provider=='anthropic':return name.startswith('claude-')
 if provider=='openai':return not name.startswith('gpt-oss-') and bool(re.match(r'^(gpt-|o\d|chat-)',name)) and not any(x in name for x in MEDIA)
 return bool(re.match(r'^gemini-\d+(?:\.\d+)?-',name)) and not any(x in name for x in MEDIA)
def boundary(text):
 values=set()
 for n,unit in re.findall(r'(?:prompts?\s*(?:<=|≤|>|<)|more than|exceed(?:ing|s)?)\s*([0-9]+(?:\.[0-9]+)?)\s*([kKmM])',text,re.I):
  value=float(n)*(1000 if unit.lower()=='k' else 1000000)
  if value.is_integer() and 0<value<=2000000:values.add(int(value))
 return next(iter(values)) if len(values)==1 else None

def claude_inventory(docs):
 section=docs['lifecycle'].split('## Model status',1)[1].split('\n## ',1)[0]
 states={}
 for line in section.splitlines():
  if line.lstrip().startswith('| claude-'):
   c=[x.strip() for x in line.strip('|').split('|')]
   state={'active':'current','legacy':'current','deprecated':'deprecated','retired':'retired'}.get(c[1].lower())
   if state:states[c[0]]=state
 block=docs['pricing'].split('## Model pricing',1)[1].split('\n## ',1)[0]
 rows=[line.split('|')[1].strip() for line in block.splitlines() if line.startswith('| Claude ')]
 items={};priced=set()
 for name,state in states.items():
  parts=re.sub(r'-\d{8}$','',name).split('-');label='Claude '+parts[1]+' '+'.'.join(parts[2:])
  match=[r for r in rows if r.lower()==label.lower() or r.lower().startswith(label.lower()+' (')]
  if match:priced.add(name)
  if state=='retired':continue
  if not match and state!='current':continue
  threshold=None
  for title in match:
   m=re.search(r'up to\s+([\d,]+)\s+tokens',title,re.I)
   if m:threshold=int(m.group(1).replace(',',''))
  items[name]={'name':name,'platform':'anthropic','state':state,'restricted':any('limited availability' in r for r in match),'threshold':threshold,'note':''}
 return {'items':items,'priced':priced,'states':states,'links':{},'long':set(n for n,m in items.items() if m['threshold'])}

def openai_inventory(docs):
 s=docs['pricing'];standard=s.split('### Standard pricing data',1)[1].split('### Batch pricing data',1)[0]
 items={};priced=set();long=set();states={};links={}
 for line in docs['lifecycle'].splitlines():
  m=re.search(r'\]\((/api/docs/models/([^/)]+)\.md)\)',line)
  if m and in_scope('openai',m.group(2)):
   name=m.group(2);links[name]='https://developers.openai.com'+m.group(1)
   states[name]='retired' if 'Shut down.' in line else 'deprecated' if 'Deprecated.' in line else 'preview' if 'preview' in name else 'current'
 for line in standard.splitlines():
  c=[x.strip() for x in line.strip('|').split('|')];name=c[0].split(' ')[0]
  if not in_scope('openai',name):continue
  if len(c) not in [4,11]:continue
  priced.add(name)
  if len(c)==11:long.add(name)
  match=re.search(r'([\d.]+)\s*([kKmM])\s+context',c[0])
  threshold=int(float(match.group(1))*(1000 if match.group(2).lower()=='k' else 1000000)) if match else None
  items[name]={'name':name,'platform':'openai','state':states.get(name,'preview' if 'preview' in name else 'current'),'restricted':False,'threshold':threshold,'note':''}
 special=s.split('Specialized models',1)[1].split('### Grouped Pricing Table data',1)[1].split('### Grouped Pricing Table data',1)[0]
 for line in special.splitlines():
  c=[x.strip() for x in line.strip('|').split('|')]
  if len(c)!=7:continue
  name=c[1].split(' ')[0]
  if not in_scope('openai',name):continue
  if 'long context' in c[1]:
   if any('$' in x for x in c[2:]):long.add(name)
   continue
  priced.add(name);items[name]={'name':name,'platform':'openai','state':states.get(name,'preview' if 'preview' in name else 'current'),'restricted':'Trusted Access' in c[0],'threshold':None,'note':''}
 for name,state in states.items():
  if state!='retired' and name not in items:items[name]={'name':name,'platform':'openai','state':state,'restricted':False,'threshold':None,'note':''}
 return {'items':items,'priced':priced,'states':states,'links':links,'long':long}

def gemini_inventory(docs):
 states={};items={};priced=set();long=set()
 # In Google's documented "Deprecated models" subtables, only the first cell is the retired ID.
 for section in re.split(r'(?m)^(?=###? )',docs['lifecycle']):
  retired_section=section.startswith('### Deprecated models')
  for table in re.findall(r'{% table[^%]*%}(.*?){% /table %}',section,re.S):
   for row in re.split(r'\n\s*---\s*\n',table)[1:]:
    cells=re.split(r'(?m)^\s*\* ',row)[1:]
    if cells:
     m=re.search(r'\x60(gemini-[^\x60]+)\x60',cells[0])
     if m:states[m.group(1)]='retired' if retired_section else 'preview' if 'preview' in m.group(1) else 'current'
 for name in re.findall(r'\x60(gemini-[^\x60]+)\x60 is deprecated',docs['lifecycle']):
  if states.get(name)!='retired':states[name]='deprecated'
 for section in re.split(r'(?m)^## ',docs['pricing'])[1:]:
  m=re.search(r'\*\[\x60([^\x60]+)\x60\]',section)
  if not m or not in_scope('gemini',m.group(1)):continue
  name=m.group(1);priced.add(name);block=section.split('{% tab title="Standard" %}',1)[-1].split('{% /tab %}',1)[0]
  threshold=boundary(block)
  if threshold:long.add(name)
  items[name]={'name':name,'platform':'gemini','state':states.get(name,'preview' if 'preview' in name else 'current'),'restricted':False,'threshold':threshold,'note':''}
 names=set(re.findall(r'/docs/models/(gemini-[a-z0-9._-]+)',docs.get('models','')))
 for name in names:
  if in_scope('gemini',name) and states.get(name)!='retired' and name not in items:
   items[name]={'name':name,'platform':'gemini','state':states.get(name,'preview' if 'preview' in name else 'current'),'restricted':False,'threshold':None,'note':''}
 return {'items':items,'priced':priced,'states':states,'links':{},'long':long}
INSPECTORS={'anthropic':claude_inventory,'openai':openai_inventory,'gemini':gemini_inventory}
