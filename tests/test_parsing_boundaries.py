import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import verify_codes as v


class FamilyBoundaryTests(unittest.TestCase):
    def test_attribute_boundaries_do_not_invent_gloves(self):
        for text in ['双插手，套餐:安全防爆','双插手 套餐:安全防爆','{产品类型:双插手;套餐:保暖}']:
            with self.subTest(text=text):self.assertNotIn('手套',v.extract_families(text))

    def test_normalizer_keeps_its_existing_contract(self):
        self.assertIn('手套',v.norm_text('双插手，套餐'))

    def test_real_family_terms_and_packaging_are_preserved(self):
        for text,family in [('蓝色PVC手套M码50只','手套'),('无纺布鞋套50只（印花）','鞋套'),
                            ('暖火艾草暖贴10片','暖贴'),('发热鞋垫男码10对','发热鞋垫'),
                            ('艾草暖贴外袋 10片','包装材料')]:
            with self.subTest(text=text):self.assertIn(family,v.extract_families(text))


if __name__=='__main__':unittest.main()
