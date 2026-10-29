import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import verify_codes as v


class PackagingQuantityTests(unittest.TestCase):
    def test_descriptions_do_not_break_pack_multiplier(self):
        for text,n in [('眼罩5片袋装 玫瑰香*5',25),('眼罩5片袋装 洋甘菊香*3',15),
                       ('暖膝贴5片盒装（蓝色）*2',10),('暖颈贴5片盒装（红色）*2',10)]:
            with self.subTest(text=text):self.assertEqual(v.quantity_details(text)[0],(n,'片'))

    def test_already_parsed_and_bare_multipliers_are_not_multiplied_twice(self):
        for text,n in [('5片*5',25),('10片*2盒',20),('5片×10包',50),('暖贴100片盒装',100)]:
            with self.subTest(text=text):self.assertEqual(v.quantity_details(text)[0],(n,'片'))

    def test_models_and_bare_codes_are_not_pack_multipliers(self):
        self.assertEqual(v.quantity_details('眼罩5片 型号x3')[0],(5,'片'))
        self.assertIsNone(v.quantity_details('NH00720')[0])

    def test_unsupported_multiplier_is_not_silently_ignored(self):
        qty,issues=v.quantity_details('眼罩5片*9999')
        self.assertIsNone(qty)
        self.assertTrue(any('倍数' in x for x in issues))

    def test_multiplier_with_count_unit_is_not_packaging(self):
        parsed=v.quantity_structure('眼罩5片*2片')
        self.assertIsNone(parsed['qty'])
        self.assertTrue(parsed['incomplete'])

    def test_explicit_total_is_separate_from_per_box_rate(self):
        f=v.build_features('眼罩','【40片】；玫瑰香【10片/盒】')
        self.assertEqual(v.audit_quantity(f),(40,'片'))
        self.assertIsNone(v.audit_quantity(v.build_features('眼罩','玫瑰香10片/盒')))


if __name__=='__main__':unittest.main()
