import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import verify_codes as v
from test_matching import erp_record


class TitleCategoryEvidenceTests(unittest.TestCase):
    def test_seo_title_does_not_supply_conflicting_categories(self):
        f=v.build_features('艾草暖足贴暖脚宝热敷贴足底暖贴','女码36-39码 40片')
        self.assertEqual(f['families'],set())
        r=erp_record('A','鞋垫黄艾草女码20对')
        self.assertEqual(v.audit_current_code('A',f,{'A':[r]},[r])['核验状态'],'核对通过')

    def test_quantity_conflict_remains_even_when_title_is_ambiguous(self):
        f=v.build_features('暖足贴暖身贴暖贴','女码36-39码 38片')
        r=erp_record('A','鞋垫黄艾草女码20对')
        self.assertIn('数量不一致',v.audit_current_code('A',f,{'A':[r]},[r])['冲突项目'])

    def test_explicit_sku_category_has_priority(self):
        self.assertEqual(v.build_features('暖贴足贴热水袋','发热鞋垫40片')['families'],{'发热鞋垫'})

    def test_single_clear_title_category_is_still_available(self):
        self.assertEqual(v.build_features('电热水袋','粉色1200ml')['families'],{'热水袋'})

    def test_patch_names_do_not_turn_wearable_supports_into_patches(self):
        a=v.build_features('膝盖热敷贴','护膝热敷贴2片')
        b=v.build_features('','',erp_name='暖膝热敷贴2片')
        self.assertFalse(any('主品部位' in x for x in v.current_code_conflicts(a,b)))
        support=v.build_features('保暖护膝','灰色护膝L')
        self.assertTrue(any('商品类型不一致' in x for x in v.current_code_conflicts(support,b)))


if __name__=='__main__':unittest.main()
