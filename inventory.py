"""Keep historical prices, auto-admit compatible new text models, quarantine ambiguity."""
import copy,re,math
from parsers import PARSERS,SOURCES,apply_gemini_routes
from inventory_sources import INSPECTORS,in_scope,boundary
META=('name','platform','state','restricted','threshold','note')

def valid_record(r,new=False):
 if not in_scope(r['platform'],r['name']):raise ValueError('Unsupported model namespace')
 if r.get('threshold') is not None and (type(r['threshold']) is not int or not 0<r['threshold']<=2000000):raise ValueError('Invalid threshold')
 if bool(r.get('long_prices'))!=bool(r.get('threshold')):raise ValueError('Unresolved context threshold')
 for values in [r['prices']]+([r['long_prices']] if r.get('long_prices') else []):
  if len(values)!=5 or not values[0] or not values[1]:raise ValueError('Missing paid rates')
  if not all(v is None or type(v) in [int,float] and math.isfinite(v) and 0<=v<=1000 for v in values):raise ValueError('Invalid rate')
  if new and (values[0]>100 or values[1]>500 or (values[2] or 0)>values[0]*1.1 or max(values[3] or 0,values[4] or 0)>values[0]*4):raise ValueError('New-model rate needs approval')
 return r

def collect(registry,documents,old,today,loader=None):
 previous={r['name']:r for r in (old or {}).get('records',[])}
 seeds={r['name']:r for r in registry};output=[];pending=[];added=0;fetches=0
 for provider,inspector in INSPECTORS.items():
  docs=documents[provider];info=inspector(docs)
  known={n:r for n,r in previous.items() if r['platform']==provider}
  if not old:known={n:r for n,r in seeds.items() if r['platform']==provider}
  active=[n for n,r in known.items() if r.get('state') not in ['retired','unlisted'] and info['states'].get(n)!='retired']
  missing=[n for n in active if n not in info['priced']]
  if len(missing)>2 and len(missing)>len(active)*0.4:raise ValueError('Unexpected provider inventory loss: '+provider)
  names=sorted(set(known)|{n for n in info['items'] if info['states'].get(n)!='retired'})
  provider_rows=[]
  for name in names:
   prior=known.get(name);item=info['items'].get(name);is_new=name not in previous and old is not None
   if prior and (info['states'].get(name)=='retired' or prior.get('state')=='retired' and info['states'].get(name) not in ['current','preview','deprecated']):
    if name not in previous:continue
    archived=copy.deepcopy(previous[name]);archived.update(state='retired',archive_reason='official_retired',archived_on=previous[name].get('archived_on',today.isoformat()))
    provider_rows.append(archived);continue
   if name not in info['priced']:
    if name in previous:
     archived=copy.deepcopy(previous[name]);archived.update(state='unlisted',archive_reason='official_price_missing',archived_on=previous[name].get('archived_on',today.isoformat()))
     provider_rows.append(archived)
    if item or name in previous:pending.append({'name':name,'platform':provider,'reason':'price_not_listed','source':SOURCES[provider]['pricing']})
    continue
   meta={k:(prior or seeds.get(name) or item).get(k) for k in META}
   meta['note']=meta.get('note') or ''
   if item:
    meta.update(name=name,platform=provider,state=info['states'].get(name,item['state']))
    if item.get('threshold') is not None:meta['threshold']=item['threshold']
    if is_new:meta.update(restricted=item.get('restricted',False),note='')
   if provider=='openai' and name in info['long'] and not meta.get('threshold'):
    link=info['links'].get(name)
    if loader and link and fetches<20:
     try:fetches+=1;meta['threshold']=boundary(loader(link))
     except Exception:pass
    if not meta.get('threshold'):
     pending.append({'name':name,'platform':provider,'reason':'context_threshold_unconfirmed','source':link or SOURCES[provider]['pricing']})
     if name in previous:provider_rows.append(copy.deepcopy(previous[name]))
     continue
   try:
    row=PARSERS[provider](docs,[meta],today)[0];valid_record(row,is_new)
   except Exception:
    if not is_new:raise
    pending.append({'name':name,'platform':provider,'reason':'unsupported_or_incomplete_pricing','source':SOURCES[provider]['pricing']});continue
   if is_new:
    if added>=20:
     pending.append({'name':name,'platform':provider,'reason':'new_model_batch_limit','source':SOURCES[provider]['pricing']});continue
    row.update(admission='official_standard',admitted_on=today.isoformat());added+=1
   elif name in previous:
    for key in ['admission','admitted_on']:
     if key in previous[name]:row[key]=previous[name][key]
   row.pop('archived_on',None);row.pop('archive_reason',None)
   provider_rows.append(row)
  if provider=='gemini':provider_rows=apply_gemini_routes(provider_rows,docs,today)
  output.extend(provider_rows)
 if not output or len(output)>200:raise ValueError('Catalog inventory limit')
 # Never drop old price definitions; archived rows remain available for history and safe rollback.
 if previous and not set(previous).issubset({r['name'] for r in output}):raise ValueError('Historical model was dropped')
 return output,sorted(pending,key=lambda r:(r['platform'],r['name']))[:50]
