import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import verify_codes as v
from test_matching import erp_record


class QuantityParseGuardTests(unittest.TestCase):
    def setUp(self):
        self.context = {'平台':'快手', '商品 ID':'001', 'SKU ID':'002',
                        '商品标题':'10片暖火蒸汽热敷手腕带', 'SKU':'【三段式发热】暖火蒸汽热敷手腕带；2盒【共10片送精油】环绕包裹手部',
                        'ERP货品编号':'', 'ERP规格编码':'', '独立规格数量':''}
        self.pf = v.build_features(self.context['商品标题'], self.context['SKU'])
        self.pf['context'] = self.context
        self.erp = erp_record('A', '暖火热敷手腕带2盒10片送精油')
        self.erp.update(erp_fingerprint='ERP-EXACT', source_row=7)
        scope = patch.object(v.business_specs, 'load_rules', return_value={'products':{
            'A':{'erp_fingerprint':'ERP-EXACT', 'accessories':['oil'], 'rule_ids':['fixture']}}})
        scope.start(); self.addCleanup(scope.stop)
        v.business_specs.transform_erp(self.erp, v.build_features)
        self.entry = {'context':self.context, 'code':'A',
                      'content_fingerprint':v.sku_reviews.content_fingerprint(self.context),
                      'erp_fingerprints':['ERP-EXACT']}
        self.guards = {v.sku_reviews.review_key(self.context):self.entry}
        self.result = {'核验状态':'核对通过', '核验说明':'original', '匹配依据':'original',
                       '判定路径':'原编码收录与明示规格核对', '应改为编码':''}

    def apply(self, result=None, pf=None, erp=None, code='A'):
        with patch.object(v, 'load_quantity_parse_guards', return_value=self.guards):
            return v.apply_quantity_parse_guard(result or self.result, pf or self.pf, code, [erp or self.erp])

    def test_approved_gap_becomes_pending_without_changing_inputs(self):
        original = copy.deepcopy((self.result, self.pf, self.erp))
        result = self.apply()
        self.assertEqual(result['核验状态'], '待人工确认')
        self.assertIn('ERP侧数量无法解析', result['核验说明'])
        self.assertIn('数量未明确', result['核验说明'])
        self.assertEqual(result['应改为编码'], '')
        detail = json.loads(result['数量解析保护JSON'])
        self.assertEqual(detail['platform_quantity'], [[10, '片']])
        self.assertEqual(detail['erp'][0]['source_row'], 7)
        self.assertEqual((self.result, self.pf, self.erp), original)

    def test_other_identity_does_not_inherit_guard(self):
        for field in ['平台', '商品 ID', 'SKU ID']:
            with self.subTest(field=field):
                pf = copy.deepcopy(self.pf); pf['context'][field] += 'changed'
                self.assertEqual(self.apply(pf=pf)['核验状态'], '核对通过')
    def test_changed_binding_is_visible_and_never_passes(self):
        for field in ['商品标题', 'SKU', 'ERP规格编码', '独立规格数量']:
            with self.subTest(field=field):
                pf = copy.deepcopy(self.pf); pf['context'][field] += 'changed'
                result = self.apply(pf=pf)
                self.assertEqual(result['核验状态'], '待人工确认')
                self.assertIn(field, result['核验说明'])
                self.assertEqual(result['确认有效性'], '已失效')
        self.assertEqual(self.apply(code='B')['核验状态'], '待人工确认')
        changed = copy.deepcopy(self.erp); changed['erp_fingerprint'] = 'OTHER'
        self.assertEqual(self.apply(erp=changed)['核验状态'], '待人工确认')

    def test_expiry_keeps_conflict_evidence_and_survives_repeated_checks(self):
        pf = copy.deepcopy(self.pf); pf['context']['商品标题'] += '（双11）'
        original = {**self.result, '核验状态':'异常（商品/规格不一致）', '冲突项目':'数量不一致'}
        first = self.apply(result=original, pf=pf)
        second = self.apply(result=first, pf=pf)
        self.assertEqual(first, second)
        self.assertEqual(first['核验状态'], '待人工确认')
        self.assertEqual(first['冲突项目'], '数量不一致')
        detail = json.loads(first['确认失效JSON'])
        self.assertEqual(detail[0]['原算法状态'], '异常（商品/规格不一致）')
        self.assertEqual(detail[0]['原冲突项目'], '数量不一致')
        # A later confirmation cannot silently restore pass on an expired guard.
        revived = self.apply(result={**first, '核验状态':'核对通过'}, pf=pf)
        self.assertEqual(revived['核验状态'], '待人工确认')

    def test_file_location_and_store_label_do_not_define_scope(self):
        pf = copy.deepcopy(self.pf); pf['context']['店铺'] = '另一个本机标签'
        pf['context']['源文件'] = 'different.csv'
        self.assertEqual(self.apply(pf=pf)['核验状态'], '待人工确认')

    def test_existing_nonpass_decisions_are_preserved(self):
        for state in ['异常（商品/规格不一致）', '异常（ERP未找到）', '编码缺失（待补录）', '待人工确认']:
            result = {**self.result, '核验状态':state}
            self.assertIs(self.apply(result=result), result)

    def test_missing_platform_quantity_and_erp_declarations_are_outside_scope(self):
        pf = copy.deepcopy(self.pf); pf['qty'] = None; pf['quantity_structure']['alternative_quantities'] = []
        with patch.object(v.business_specs, 'transform_platform', return_value=(pf, '')):
            self.assertEqual(self.apply(pf=pf)['核验状态'], '核对通过')
        erp = copy.deepcopy(self.erp); erp['features'] = v.build_features('', '', erp_name='热水袋粉色')
        self.assertEqual(self.apply(erp=erp)['核验状态'], '核对通过')

    def test_parsed_and_alternative_quantities_do_not_trigger_guard(self):
        erp = copy.deepcopy(self.erp); erp['features']['qty'] = (10, '片')
        self.assertEqual(self.apply(erp=erp)['核验状态'], '核对通过')
        erp['features']['qty'] = None
        erp['features']['quantity_structure']['alternative_quantities'] = [(10, '片')]
        self.assertEqual(self.apply(erp=erp)['核验状态'], '核对通过')
        erp['features']['quantity_structure']['alternative_quantities'] = [(2, '盒')]
        self.assertEqual(self.apply(erp=erp)['核验状态'], '核对通过')

    def test_component_quantity_coverage_is_not_missing_total(self):
        pf = copy.deepcopy(self.pf); erp = copy.deepcopy(self.erp)
        part = v.build_features('', '暖贴10片')
        pf['confirmed_components'] = {'暖贴':copy.deepcopy(part)}
        erp['features']['confirmed_components'] = {'暖贴':copy.deepcopy(part)}
        self.assertEqual(self.apply(pf=pf, erp=erp)['核验状态'], '核对通过')

    def test_native_pipeline_preserves_duplicate_rows_and_codes(self):
        import pandas as pd
        from simple_report import prepare_rows
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / '快手.csv'
            item = {'商品ID':'001', 'skuID':'002', '商品标题':self.context['商品标题'],
                    'sku名称':self.context['SKU'], 'sku编码':'A'}
            pd.DataFrame([item, item]).to_csv(p, index=False, encoding='utf-8-sig')
            original = p.read_bytes()
            with patch.object(v, 'load_quantity_parse_guards', return_value=self.guards):
                result, meta = v.verify_platform_file(str(p), [self.erp], {'A':[self.erp]},
                    platform_override='快手', confirmed_entries={}, review_entries={})
            self.assertEqual(list(result['核验状态']), ['待人工确认'] * 2)
            self.assertEqual(list(result['原编码']), ['A', 'A'])
            self.assertEqual(list(result['推测商家编码']), ['', ''])
            self.assertEqual([q['源行号'] for q in meta['_quantity_details']], [2, 3])
            pending, rows = prepare_rows(result)
            self.assertEqual(len(pending), 2); self.assertEqual(len(rows[0]), 12)
            self.assertIn('ERP侧数量无法解析', rows[0]['问题说明'])
            self.assertEqual(p.read_bytes(), original)

    def test_title_only_change_is_visible_in_default_report(self):
        import pandas as pd
        from simple_report import prepare_rows
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / '快手.csv'
            item = {'商品ID':'001', 'skuID':'002', '商品标题':self.context['商品标题']+'（2026双11改版）',
                    'sku名称':self.context['SKU'], 'sku编码':'A'}
            pd.DataFrame([item]).to_csv(p, index=False, encoding='utf-8-sig')
            with patch.object(v, 'load_quantity_parse_guards', return_value=self.guards):
                result, _ = v.verify_platform_file(str(p), [self.erp], {'A':[self.erp]},
                    platform_override='快手', confirmed_entries={}, review_entries={})
            record = result.to_dict('records')[0]
            self.assertEqual(record['核验状态'], '待人工确认')
            self.assertEqual(record['原编码'], 'A')
            self.assertEqual(record['推测商家编码'], '')
            pending, rows = prepare_rows(result)
            self.assertEqual(len(pending), 1); self.assertEqual(len(rows[0]), 12)
            self.assertIn('数量保护已失效', rows[0]['问题说明'])
            self.assertIn('商品标题', rows[0]['问题说明'])


if __name__ == '__main__':
    unittest.main()
