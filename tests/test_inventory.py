import copy,datetime as dt,unittest
from unittest.mock import patch
from inventory import collect
from inventory_sources import claude_inventory,gemini_inventory
from sync_prices import review_reasons
DAY=dt.date(2026,11,13)
def model(i,state='current'):
 return {'name':'claude-fixture-'+str(i),'platform':'anthropic','prices':[1,5,.1,1.25,2],'state':state,'restricted':False,'note':''}
def documents(total,retired=(),missing=(),bad=()):
 life='## Model status\n| API model name | Current state |\n'
 prices='## Model pricing\n| Model | Base input tokens | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens |\n'
 for i in range(1,total+1):
  life+='| claude-fixture-'+str(i)+' | '+('Retired' if i in retired else 'Active')+' |\n'
  if i not in missing:
   prices+='| Claude Fixture '+str(i)+' | '+('$1 and $2' if i in bad else '$1')+' / MTok | $1.25 / MTok | $2 / MTok | $0.1 / MTok | $5 / MTok |\n'
 return {'anthropic':{'pricing':prices,'lifecycle':life},'openai':{'pricing':'','lifecycle':''},'gemini':{'pricing':'','lifecycle':''}}
def empty(_):return {'items':{},'priced':set(),'states':{},'links':{},'long':set()}
def reconcile(docs,old):
 registry=[{k:v for k,v in r.items() if k!='prices'} for r in old['records']]
 with patch.dict('inventory.INSPECTORS',{'anthropic':claude_inventory,'openai':empty,'gemini':empty}):return collect(registry,docs,old,DAY)
class LifecycleTests(unittest.TestCase):
 def setUp(self):self.old={'records':[model(i) for i in range(1,11)]}
 def test_ten_retire_three_keeps_seven_live_and_three_history(self):
  rows,pending=reconcile(documents(10,retired=(1,2,3),missing=(1,2,3)),self.old)
  self.assertEqual(len(rows),10);self.assertEqual(sum(r['state']=='current' for r in rows),7)
  self.assertEqual(sum(r['state']=='retired' for r in rows),3);self.assertFalse(pending)
  self.assertEqual(next(r for r in rows if r['name']=='claude-fixture-1')['prices'],self.old['records'][0]['prices'])
 def test_ten_add_three_becomes_thirteen_without_slots(self):
  rows,pending=reconcile(documents(13),self.old)
  self.assertEqual(len(rows),13);self.assertFalse(pending)
  self.assertEqual(sum(r.get('admission')=='official_standard' for r in rows),3)
  self.assertFalse(review_reasons(self.old,{'records':rows},DAY))
 def test_retire_and_add_in_one_pass(self):
  rows,_=reconcile(documents(13,retired=(1,2,3),missing=(1,2,3)),self.old)
  self.assertEqual(sum(r['state'] not in ['retired','unlisted'] for r in rows),10)
 def test_unpriceable_new_model_is_pending_not_empty_billing_row(self):
  rows,pending=reconcile(documents(11,bad=(11,)),self.old)
  self.assertEqual(len(rows),10);self.assertEqual(pending[0]['name'],'claude-fixture-11')
 def test_missing_single_price_is_unlisted_not_claimed_retired(self):
  rows,pending=reconcile(documents(10,missing=(1,)),self.old)
  self.assertEqual(next(r for r in rows if r['name']=='claude-fixture-1')['state'],'unlisted')
  self.assertEqual(len(pending),1)
 def test_mass_missing_prices_cannot_archive_whole_provider(self):
  with self.assertRaises(ValueError):reconcile(documents(10,missing=tuple(range(1,11))),self.old)
 def test_retired_source_row_can_disappear_later_without_resurrection(self):
  old=copy.deepcopy(self.old);old['records'][0]['state']='retired'
  docs=documents(10,missing=(1,));docs['anthropic']['lifecycle']=docs['anthropic']['lifecycle'].replace('| claude-fixture-1 | Active |\n','')
  rows,_=reconcile(docs,old)
  self.assertEqual(next(r for r in rows if r['name']=='claude-fixture-1')['state'],'retired')
 def test_google_replacement_is_not_the_retired_model(self):
  life='### Deprecated models\n{% table %}\n* Model\n* Release\n* Shutdown\n* Replacement\n---\n* \x60gemini-3-pro-preview\x60\n* 2025\n* 2026\n* \x60gemini-3.1-pro-preview\x60\n{% /table %}\n'
  info=gemini_inventory({'pricing':'','lifecycle':life,'models':''})
  self.assertEqual(info['states']['gemini-3-pro-preview'],'retired')
  self.assertNotIn('gemini-3.1-pro-preview',info['states'])
 def test_old_input_is_not_mutated(self):
  before=copy.deepcopy(self.old);reconcile(documents(13),self.old);self.assertEqual(before,self.old)
if __name__=='__main__':unittest.main()
