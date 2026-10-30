import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import verify_codes as v
from test_matching import erp_record


class ThreeInOneTotalTest(unittest.TestCase):
    def run_row(self,spec='三合一暖贴20片',name='三合一暖贴20片（艾草5+益母草5+生姜10）',current='MIX',extra=(),changes=None):
        record=erp_record('MIX',name,item_id='')
        records=[record,*extra]
        index={}
        for item in records:index.setdefault(item['code'],[]).append(item)
        pf=v.build_features('暖贴',spec)
        pf.update(changes or {})
        return v.classify_row(current,pf,index,records)

    def test_total_known_without_recipe_is_correct(self):
        result=self.run_row()
        self.assertEqual(result['核验状态'],'编码正确')
        self.assertIn('配比不参与',result['匹配依据'])

    def test_different_recipes_same_total_are_correct(self):
        result=self.run_row(spec='三合一暖贴20片（艾草10+益母草5+生姜5）')
        self.assertEqual(result['核验状态'],'编码正确')

    def test_existing_mixed_code_checks_quantity_despite_other_same_total_codes(self):
        other=erp_record('OTHER','KT三合一暖贴20片',item_id='')
        self.assertEqual(self.run_row(extra=[other])['核验状态'],'编码正确')

    def test_quantity_mismatch_remains_manual(self):
        result=self.run_row(spec='三合一暖贴30片')
        self.assertEqual(result['核验状态'],'待人工确认')
        self.assertEqual(result['应改为编码'],'')

    def test_non_mixed_erp_is_not_a_matching_mixed_pack(self):
        result=self.run_row(name='艾草暖贴20片')
        self.assertEqual(result['核验状态'],'待人工确认')
        self.assertIn('非三合一',result['匹配依据'])

    def test_each_twenty_is_sixty_not_twenty(self):
        self.assertEqual(self.run_row(name='艾草/益母草/生姜暖贴各20片')['核验状态'],'待人工确认')

    def test_no_total_still_needs_confirmation(self):
        self.assertEqual(self.run_row(spec='三合一暖贴')['核验状态'],'待人工确认')

    def test_explicit_received_total_allows_buy_and_gift(self):
        result=self.run_row(spec='三合一暖贴买15送5【到手20片】')
        self.assertEqual(result['核验状态'],'编码正确')
        self.assertEqual(result['规格问题'],'')

    def test_other_product_gift_remains_manual(self):
        self.assertEqual(self.run_row(spec='三合一暖贴20片送暖蛋')['核验状态'],'待人工确认')

    def test_buy_gift_sum_must_agree_with_received_total(self):
        self.assertEqual(self.run_row(spec='三合一暖贴买10送5【到手20片】')['核验状态'],'待人工确认')

    def test_numeric_offer_does_not_hide_an_additional_gift(self):
        self.assertEqual(self.run_row(spec='三合一暖贴买15送5【到手20片】送暖蛋')['核验状态'],'待人工确认')

    def test_title_offer_cannot_override_sku_quantity(self):
        record=erp_record('MIX','三合一暖贴20片',item_id='')
        pf=v.build_features('三合一暖贴买1送1到手2片','三合一暖贴买15送5到手20片')
        self.assertEqual(v.classify_row('MIX',pf,{'MIX':[record]},[record])['核验状态'],'编码正确')

    def test_unknown_code_keeps_exception(self):
        result=self.run_row(current='OLD')
        self.assertEqual(result['核验状态'],'异常（ERP未找到）')
        self.assertEqual(result['应改为编码'],'')

    def test_duplicate_erp_code_blocks_correct_status(self):
        other=erp_record('MIX','三合一暖贴20片',source='单品',item_id='')
        self.assertEqual(self.run_row(extra=[other])['核验状态'],'待人工确认')

    def test_duplicate_platform_sku_blocks_correct_status(self):
        self.assertEqual(self.run_row(changes={'duplicate_sku':True})['核验状态'],'待人工确认')

    def test_blank_code_and_multiple_targets_remain_manual(self):
        other=erp_record('OTHER','三合一暖贴20片',item_id='')
        self.assertEqual(self.run_row(current='',extra=[other])['核验状态'],'待人工确认')

    def test_blank_code_unique_target_is_supplement_only(self):
        result=self.run_row(current='')
        self.assertEqual(result['核验状态'],'编码缺失（待补录）')
        self.assertEqual(result['ERP唯一对应编码'],'MIX')
        self.assertEqual(result['应改为编码'],'')

    def test_packaging_material_does_not_use_mixed_product_rule(self):
        self.assertEqual(self.run_row(spec='三合一暖贴彩盒20片',name='三合一暖贴彩盒20片')['核验状态'],'待人工确认')

    def test_mixed_product_family_must_be_same(self):
        self.assertEqual(self.run_row(name='三合一足贴20片')['核验状态'],'待人工确认')


if __name__=='__main__':
    unittest.main()
