import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import verify_codes as v
from test_matching import erp_record


class CompositionQuantityTests(unittest.TestCase):
    def audit(self,platform,erp):
        record=erp_record('A',erp)
        return v.audit_current_code('A',v.build_features('暖贴',platform),{'A':[record]},[record])

    def test_parallel_counts_are_not_deduplicated(self):
        for n in [10,20,30]:
            self.assertEqual(v.quantity_details(f'暖贴艾草{n}片+暖贴生姜{n}片')[0],(2*n,'片'))
        self.assertEqual(v.quantity_details('暖贴10片+暖贴10片+暖贴10片')[0],(30,'片'))

    def test_recipe_in_parentheses_is_not_added_to_main_total(self):
        self.assertEqual(v.quantity_details('暖贴10片（艾草5+益母草5）')[0],(10,'片'))

    def test_each_component_keeps_its_own_multiplier(self):
        self.assertEqual(v.quantity_details('暖贴艾草10片+暖贴生姜10片*2')[0],(30,'片'))

    def test_equal_totals_do_not_hide_different_formula_composition(self):
        r=self.audit('暖贴艾草10片+暖贴生姜30片','暖贴艾草20片+暖贴生姜20片')
        self.assertEqual(r['核验状态'],'异常（商品/规格不一致）')

    def test_component_unit_conversion_is_family_scoped(self):
        self.assertEqual(self.audit('暖贴20片+足贴40片','暖贴20片+足贴20对')['核验状态'],'核对通过')
        self.assertNotEqual(self.audit('暖贴20片+足贴40片','暖贴40片+足贴10对')['核验状态'],'核对通过')
        self.assertEqual(self.audit('暖贴20片+暖贴20对','暖贴60片')['核验状态'],'待人工确认')

    def test_explicit_incomplete_bundle_cannot_pass(self):
        for spec in ['暖贴10片+足贴','暖贴10片+未知赠品','暖贴10片+未知赠品10片',
                     '暖贴10片送未知赠品10片','暖贴10片送足贴','暖贴艾草+暖贴生姜共20片']:
            with self.subTest(spec=spec):
                self.assertEqual(self.audit(spec,'暖贴20片')['核验状态'],'待人工确认')

    def test_unsupported_gift_preserves_main_count_as_diagnostic_only(self):
        parsed=v.quantity_structure('暖颈贴5片盒装（红色）*2送精油')
        self.assertEqual(parsed['parsed_total'],(10,'片'))
        self.assertIsNone(parsed['qty'])
        self.assertTrue(parsed['incomplete'])

    def test_different_known_components_compare_without_cross_unit_total(self):
        spec='暖贴20片+眼罩1个'
        self.assertIsNone(v.quantity_details(spec)[0])
        self.assertEqual(self.audit(spec,spec)['核验状态'],'核对通过')
        self.assertEqual(self.audit(spec,'暖贴20片+眼罩2个')['核验状态'],'异常（商品/规格不一致）')

    def test_omitted_product_name_can_inherit_but_unknown_gift_cannot(self):
        self.assertEqual(v.quantity_details('暖贴20片+20片')[0],(40,'片'))
        detail=v.quantity_structure('暖贴20片+未知赠品20片')
        self.assertTrue(detail['incomplete'])
        self.assertEqual(detail['parts'][1]['families'],[])

    def test_unknown_ordinary_description_keeps_old_policy(self):
        self.assertEqual(self.audit('优惠装','暖贴20片')['核验状态'],'核对通过')

    def test_quantity_offer_marketing_tail_does_not_invent_a_gift_product(self):
        for spec in ['暖贴买25送5【到手30片】热销款','暖贴买25送5同款【到手30片】经济装',
                     '暖贴买25送5【到手30片】更划算}']:
            self.assertEqual(self.audit(spec,'暖贴30片')['核验状态'],'核对通过')

    def test_platform_and_erp_use_the_same_structure_parser(self):
        a=v.build_features('','暖贴艾草10片+暖贴生姜10片')['quantity_structure']
        b=v.build_features('','',erp_name='暖贴艾草10片+暖贴生姜10片')['quantity_structure']
        self.assertEqual(a,b)
        self.assertEqual(len(a['parts']),2)

    def test_three_in_one_still_ignores_recipe_ratio(self):
        self.assertEqual(self.audit('三合一暖贴20片（艾草10+益母草5+生姜5）','三合一暖贴20片（艾草5+益母草5+生姜10）')['核验状态'],'核对通过')

    def test_three_in_one_recipe_is_recorded_but_not_compared(self):
        detail=v.quantity_structure('三合一暖贴20片（艾草10+益母草5+生姜5）')
        self.assertEqual(detail['comparison_scope'],'total_only')
        self.assertEqual(len(detail['recipe_details']),3)
        self.assertEqual(detail['qty'],(20,'片'))


if __name__=='__main__':unittest.main()
