import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import verify_codes as v
from test_matching import erp_record


class ProductPackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records,cls.index=v.build_erp_records(v.load_erp(str(Path(v.__file__).parents[1]/'data/组合装.csv'),str(Path(v.__file__).parents[1]/'data/单品.csv')))

    def test_strong_packaging_terms_still_mean_material(self):
        self.assertEqual(v.extract_families('艾草暖贴外袋10片'),{'包装材料'})
        self.assertEqual(v.extract_families('暖贴内袋 卷材'),{'包装材料'})

    def test_unconfirmed_soft_packaging_is_pending(self):
        r=erp_record('NEW','艾草暖贴彩盒30片')
        result=v.audit_current_code('NEW',v.build_features('暖贴','艾草暖贴30片'),{'NEW':[r]},[r])
        self.assertEqual(result['核验状态'],'待人工确认')
        self.assertIn('成品/包材',result['核验说明'])

    def test_confirmed_finished_record_is_shared_across_new_platform_skus(self):
        r=self.index['CH03701'][0]
        self.assertEqual(r['features']['families'],{'暖贴'})
        for sku in ['卡通艾草暖贴30片盒装','卡通艾草暖贴30片彩盒装']:
            self.assertEqual(v.audit_current_code('CH03701',v.build_features('暖贴',sku),self.index,self.records)['核验状态'],'核对通过')

    def test_finished_record_confirmation_does_not_hide_wrong_quantity(self):
        result=v.audit_current_code('CH03701',v.build_features('暖贴','艾草暖贴40片'),self.index,self.records)
        self.assertEqual(result['核验状态'],'异常（商品/规格不一致）')

    def test_name_without_product_evidence_is_not_guessed_as_a_mask(self):
        self.assertNotIn('口罩',v.extract_families('鱼型黑色独立30片国潮彩盒'))

    def test_packaging_classification_keeps_raw_erp_name_and_category(self):
        r=self.index['CH03701'][0]
        self.assertEqual(r['name'],'KT艾草暖贴彩盒 30片（新包装2025）')
        self.assertIn('erp_fingerprint',r)


if __name__=='__main__':unittest.main()
