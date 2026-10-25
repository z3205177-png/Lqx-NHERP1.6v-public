import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import confirmed_mappings as cm
import verify_codes as v
from test_matching import erp_record


class AcceptedCodesTest(unittest.TestCase):
    def setUp(self):
        self.row={'平台':'快手','店铺':'测试店','商品 ID':'001','SKU ID':'002',
                  '商品标题':'足贴','SKU':'艾草升级暖足【8小时】20片','原编码':'B'}
        self.records=[{**erp_record(code,'足贴艾草10对',item_id=''),'erp_fingerprint':'record-'+code} for code in ('A','B')]
        self.entry={'platform_fingerprint':cm.platform_fingerprint(self.row),'erp_code':'A','erp_fingerprint':'record-A',
                    'confirmed_by':'用户','basis':'已确认同款20片可使用两个编码',
                    'accepted_erp_records':{'A':'record-A','B':'record-B'}}
        self.entries={cm.platform_key(self.row):self.entry}

    def test_either_accepted_current_code_is_correct(self):
        for code in ('A','B'):
            with self.subTest(code=code):
                self.row['原编码']=code
                approved,issue=cm.lookup_confirmation(self.row,self.records,self.entries)
                self.assertEqual(issue,'')
                self.assertEqual(approved['record']['code'],code)
                pf=v.build_features('足贴',self.row['SKU'])
                pf['confirmation']=approved
                result=v.classify_row(code,pf,{r['code']:[r] for r in self.records},self.records)
                self.assertEqual(result['核验状态'],'编码正确')
                self.assertEqual(result['应改为编码'],'')

    def test_blank_code_does_not_choose_between_accepted_codes(self):
        self.row['原编码']=''
        approved,issue=cm.lookup_confirmation(self.row,self.records,self.entries)
        self.assertIsNone(approved)
        self.assertIn('多个',issue)

    def test_other_current_code_does_not_choose_a_replacement(self):
        self.row['原编码']='C'
        approved,issue=cm.lookup_confirmation(self.row,self.records,self.entries)
        self.assertIsNone(approved)
        self.assertIn('多个',issue)

    def test_accepted_alternative_changed_requires_reconfirmation(self):
        self.records[1]['erp_fingerprint']='changed'
        approved,issue=cm.lookup_confirmation(self.row,self.records,self.entries)
        self.assertIsNone(approved)
        self.assertIn('变化',issue)

    def test_duplicate_accepted_code_requires_reconfirmation(self):
        approved,issue=cm.lookup_confirmation(self.row,[*self.records,self.records[1]],self.entries)
        self.assertIsNone(approved)
        self.assertIn('重复',issue)

    def test_changed_sku_still_invalidates_confirmation(self):
        self.row['SKU']='艾草升级暖足【8小时】40片'
        approved,issue=cm.lookup_confirmation(self.row,self.records,self.entries)
        self.assertIsNone(approved)
        self.assertIn('变化',issue)

    def test_literal_wrapper_on_accepted_current_code(self):
        self.row['原编码']='="B"'
        approved,issue=cm.lookup_confirmation(self.row,self.records,self.entries)
        self.assertEqual(issue,'')
        self.assertEqual(approved['record']['code'],'B')


if __name__=='__main__':
    unittest.main()
