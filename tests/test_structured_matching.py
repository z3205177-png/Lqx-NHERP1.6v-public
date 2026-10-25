import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import verify_codes as v
from test_matching import erp_record


class StructuredMatchingTest(unittest.TestCase):
    def record(self, code='GLOVE-L', name='PVC手套蓝色L码100只盒装'):
        return erp_record(code, name, source='单品', item_id='')

    def features(self, spec='蓝色PVC手套L码100只盒装'):
        return v.build_features('一次性PVC手套', spec)

    def test_complete_structured_identity_does_not_require_erp_id(self):
        record = self.record()
        result = v.classify_row('GLOVE-L', self.features(), {'GLOVE-L':[record]}, [record])
        self.assertEqual(result['核验状态'], '编码正确')
        self.assertEqual(result['判定路径'], '完整结构化身份与规格')

    def test_structured_match_can_correct_an_existing_wrong_code(self):
        correct = self.record()
        other = self.record('GLOVE-M', 'PVC手套蓝色M码100只盒装')
        result = v.classify_row('GLOVE-M', self.features(), {'GLOVE-L':[correct],'GLOVE-M':[other]}, [correct,other])
        self.assertEqual(result['核验状态'], '编码错误（建议修改）')
        self.assertEqual(result['应改为编码'], 'GLOVE-L')

    def test_duplicate_full_signature_remains_manual(self):
        records = [self.record(), self.record('OTHER')]
        result = v.classify_row('GLOVE-L', self.features(), {r['code']:[r] for r in records}, records)
        self.assertEqual(result['核验状态'], '待人工确认')

    def test_missing_size_remains_manual(self):
        record = self.record()
        result = v.classify_row('GLOVE-L', self.features('蓝色PVC手套100只盒装'), {'GLOVE-L':[record]}, [record])
        self.assertEqual(result['核验状态'], '待人工确认')

    def test_missing_packaging_in_same_identity_cannot_be_ignored(self):
        record = self.record()
        weaker = self.record('INCOMPLETE', 'PVC手套蓝色L码100只')
        result = v.classify_row('GLOVE-L', self.features(), {'GLOVE-L':[record],'INCOMPLETE':[weaker]}, [record,weaker])
        self.assertEqual(result['核验状态'], '待人工确认')

    def test_missing_erp_quantity_blocks_uniqueness(self):
        record = self.record()
        weaker = self.record('BASIC-L', 'PVC手套蓝色L码盒装')
        result = v.classify_row('GLOVE-L', self.features(), {'GLOVE-L':[record],'BASIC-L':[weaker]}, [record,weaker])
        self.assertEqual(result['核验状态'], '待人工确认')

    def test_missing_erp_identity_attribute_blocks_uniqueness(self):
        record = self.record()
        weaker = self.record('UNKNOWN-SIZE', 'PVC手套蓝色100只盒装')
        result = v.classify_row('GLOVE-L', self.features(), {'GLOVE-L':[record],'UNKNOWN-SIZE':[weaker]}, [record,weaker])
        self.assertEqual(result['核验状态'], '待人工确认')

    def test_unknown_erp_material_is_not_a_proven_different_product(self):
        record = self.record()
        weaker = self.record('UNKNOWN-MATERIAL', '手套蓝色L码100只盒装')
        result = v.classify_row('GLOVE-L', self.features(), {'GLOVE-L':[record],'UNKNOWN-MATERIAL':[weaker]}, [record,weaker])
        self.assertEqual(result['核验状态'], '待人工确认')

    def test_packaging_conflict_not_automatic(self):
        record = self.record()
        result = v.classify_row('GLOVE-L', self.features('蓝色PVC手套L码100只袋装'), {'GLOVE-L':[record]}, [record])
        self.assertEqual(result['核验状态'], '待人工确认')

    def test_title_does_not_supply_ambiguous_sku_color(self):
        record = self.record()
        pf = v.build_features('透明蓝色PVC手套', 'PVC手套L码100只盒装')
        result = v.classify_row('GLOVE-L', pf, {'GLOVE-L':[record]}, [record])
        self.assertEqual(result['核验状态'], '待人工确认')

    def test_changed_approved_mapping_does_not_fall_back_to_automatic(self):
        record = self.record()
        pf = self.features()
        pf['confirmation_issue'] = '平台内容已变化，需重新确认'
        result = v.classify_row('GLOVE-L', pf, {'GLOVE-L':[record]}, [record])
        self.assertEqual(result['核验状态'], '待人工确认')

    def test_plain_name_and_quantity_without_discriminators_remain_manual(self):
        record = erp_record('A', '普通暖贴30片', item_id='')
        result = v.classify_row('A', v.build_features('普通暖贴30片', '普通暖贴30片'), {'A':[record]}, [record])
        self.assertEqual(result['核验状态'], '待人工确认')

    def test_three_in_one_total_is_enough_under_user_policy(self):
        record = erp_record('MIX', '暖火三合一暖贴20片（艾草5+益母草5+生姜10）', item_id='')
        pf = v.build_features('暖火暖贴', '三合一【艾草+益母草+生姜】20片')
        result = v.classify_row('MIX', pf, {'MIX':[record]}, [record])
        self.assertEqual(result['核验状态'], '编码正确')
        self.assertIn('配比不参与', result['匹配依据'])

    def test_explicit_three_in_one_composition_can_be_verified(self):
        record = erp_record('MIX', '暖火三合一暖贴20片（艾草5+益母草5+生姜10）', item_id='')
        pf = v.build_features('暖火暖贴', '暖火三合一20片（艾草5+益母草5+生姜10）')
        result = v.classify_row('MIX', pf, {'MIX':[record]}, [record])
        self.assertEqual(result['核验状态'], '编码正确')

    def test_capacity_decimals_are_not_truncated(self):
        pf = v.build_features('热水袋', 'U型粉色1200.5ml')
        self.assertEqual(pf['evidence']['capacity'], {'1200.5ml'})

    @patch.dict(v.BUSINESS_RULES, {'three_in_one_mixed_total_only':False})
    @patch.object(v, 'audit_current_code', v.classify_row)
    def test_component_confirmation_is_scoped_to_unchanged_platform_sku(self):
        import confirmed_mappings as cm
        record = erp_record('MIX', '暖火三合一暖贴20片（艾草5+益母草5+生姜10）', item_id='')
        raw = {'商品ID':'1', 'skuID':'2', '商品标题':'暖火暖贴',
               'sku名称':'三合一【艾草+益母草+生姜】20片', 'sku编码':'MIX'}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'shop.csv'
            pd.DataFrame([raw]).to_csv(path, index=False, encoding='utf-8-sig')
            initial, _ = v.verify_platform_file(str(path), [record], {'MIX':[record]}, confirmed_entries={})
            context = initial.iloc[0].to_dict()
            rule = {cm.platform_key(context): {'platform_fingerprint':cm.platform_fingerprint(context),
                    'composition':['艾草:5片','益母草:5片','生姜:10片'], 'basis':'用户明确确认此SKU配比'}}
            with patch.dict(v.BUSINESS_RULES, {'component_confirmations':rule}):
                matched, _ = v.verify_platform_file(str(path), [record], {'MIX':[record]}, confirmed_entries={})
                self.assertEqual(matched.iloc[0]['核验状态'], '编码正确')
                self.assertEqual(matched.iloc[0]['组成确认依据'], '用户明确确认此SKU配比')
                for field, changed in [('skuID','3'), ('商品标题','暖火新版暖贴'), ('sku名称','三合一20片')]:
                    with self.subTest(field=field):
                        pd.DataFrame([{**raw, field:changed}]).to_csv(path,index=False,encoding='utf-8-sig')
                        result, _ = v.verify_platform_file(str(path), [record], {'MIX':[record]}, confirmed_entries={})
                        self.assertEqual(result.iloc[0]['核验状态'], '待人工确认')
                        self.assertEqual(result.iloc[0]['组成确认依据'], '')


if __name__ == '__main__':
    unittest.main()
