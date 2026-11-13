import copy,datetime as dt,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from parsers import dated_amounts,markdoc_rows
from sync_prices import validate,review_reasons,digest,ROOT
class PriceTests(unittest.TestCase):
 def setUp(self):
  self.registry=json.loads((ROOT/'registry.json').read_text(encoding='utf-8'))['models']
  self.catalog=json.loads((ROOT/'data/current.json').read_text(encoding='utf-8'))
 def test_complete_catalog(self):
  self.assertTrue(validate(self.catalog,self.registry));self.assertEqual(len(self.catalog['records']),67)
 def test_promotion_boundaries(self):
  s='$2.00 through November 30, 2026. $4.00 starting December 1, 2026.'
  self.assertEqual(dated_amounts(s,dt.date(2026,11,30)),(2,None))
  self.assertEqual(dated_amounts(s,dt.date(2026,12,1)),(4,None))
 def test_storage_and_audio_not_mistaken_for_reads(self):
  self.assertEqual(dated_amounts('$0.025 (text / image / video) $0.05 (audio) $1.00 per hour (storage price)',dt.date(2026,11,13)),(.025,None))
 def test_long_context_split(self):
  self.assertEqual(dated_amounts('$2.00, prompts <= 200k tokens $4.00, prompts > 200k tokens',dt.date(2026,11,13)),(2,4))
 def test_paid_not_free(self):
  block='{% table %}\n* Feature\n* Free Tier\n* Paid Tier, per 1M tokens in USD\n---\n* Input price\n* Free of charge\n* $2.00\n{% /table %}'
  self.assertEqual(markdoc_rows(block)['Input price'],'$2.00')
 def test_ambiguous_source_stops(self):
  with self.assertRaises(ValueError):dated_amounts('$1 text $2 unknown',dt.date(2026,11,13))
 def test_zero_price_rejected(self):
  bad=copy.deepcopy(self.catalog);bad['records'][0]['prices'][0]=0
  with self.assertRaises(AssertionError):validate(bad,self.registry)
 def test_missing_model_rejected(self):
  bad=copy.deepcopy(self.catalog);bad['records'].pop()
  with self.assertRaises(AssertionError):validate(bad,self.registry)
 def test_unexpected_large_change_needs_review(self):
  new=copy.deepcopy(self.catalog);new['records'][0]['prices'][0]*=3
  self.assertTrue(review_reasons(self.catalog,new,dt.date(2026,11,13)))
 def test_announced_schedule_allowed(self):
  old={'records':[{'name':'x','platform':'gemini','prices':[2,10,.1,None,None],'long_prices':None,'threshold':None,'scheduled_prices':[{'from':'2026-12-01','prices':[4,20,.2,None,None]}]}]}
  new=copy.deepcopy(old);new['records'][0]['prices']=[4,20,.2,None,None]
  self.assertFalse(review_reasons(old,new,dt.date(2026,12,1)))
 def test_source_does_not_change_old_prices(self):
  self.assertEqual(review_reasons(self.catalog,copy.deepcopy(self.catalog),dt.date(2026,11,13)),[])
 def test_hash_is_content_addressed(self):
  self.assertEqual(digest(self.catalog),digest(copy.deepcopy(self.catalog)))
if __name__=='__main__':unittest.main()
