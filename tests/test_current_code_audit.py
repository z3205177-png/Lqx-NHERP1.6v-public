import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import verify_codes as v
from test_matching import erp_record


class CurrentCodeAuditTests(unittest.TestCase):
    def audit(self, sku, erp_name, title='暖火暖贴', code='000123', extra=()):
        record = erp_record('000123', erp_name)
        records = [record, *extra]
        index = {}
        for row in records:
            index.setdefault(row['code'], []).append(row)
        return v.audit_current_code(code, v.build_features(title, sku), index, records)

    def test_existing_code_and_same_quantity_pass(self):
        result = self.audit('艾草暖贴60片', '暖火艾草暖贴60片')
        self.assertEqual(result['核验状态'], '核对通过')
        self.assertEqual(result['应改为编码'], '')

    def test_missing_specs_pass_even_with_other_possible_candidates(self):
        result = self.audit('超值装', '暖火艾草暖贴60片', extra=[erp_record('OTHER', '暖火艾草暖贴60片')])
        self.assertEqual(result['核验状态'], '核对通过')

    def test_missing_erp_specs_pass(self):
        self.assertEqual(self.audit('艾草暖贴60片', '暖火暖贴')['核验状态'], '核对通过')

    def test_existing_code_wrong_quantity_is_exception(self):
        result = self.audit('艾草暖贴60片', '暖火艾草暖贴100片')
        self.assertEqual(result['核验状态'], '异常（商品/规格不一致）')
        self.assertIn('数量不一致', result['冲突项目'])
        self.assertEqual(result['应改为编码'], '')

    def test_absent_code_is_exception_regardless_of_similar_goods(self):
        self.assertEqual(self.audit('艾草暖贴60片', '暖火艾草暖贴60片', code='OLD')['核验状态'], '异常（ERP未找到）')

    def test_blank_code_is_retained_for_supplement(self):
        result = self.audit('艾草暖贴60片', '暖火艾草暖贴60片', code='')
        self.assertEqual(result['核验状态'], '编码缺失（待补录）')
        self.assertEqual(result['应改为编码'], '')

    def test_explicit_conflicts(self):
        for title, sku, name, reason in [
            ('手套', '蓝色PVC手套M码100只', '暖贴100片', '品类'),
            ('手套', '蓝色PVC手套M码100只', '蓝色丁腈手套M码100只', '材质'),
            ('手套', '蓝色PVC手套M码100只', '蓝色PVC手套L码100只', '尺码'),
            ('护膝', '咖色护膝L+艾草暖贴15片', '护膝灰色L+艾草暖贴15片', '颜色'),
            ('暖贴', '三合一暖贴10片', '艾草暖贴10片', '配方/混合装'),
            ('热水袋', '粉色U型热水袋1200ml', '粉色U型热水袋1600ml', '容量'),
            ('蒸汽眼罩', '玫瑰眼罩10片', '无香眼罩10片', '香型'),
            ('热敷贴', '暖膝热敷贴10片', '暖腰热敷贴10片', '主品部位'),
        ]:
            with self.subTest(reason=reason):
                result = self.audit(sku, name, title)
                self.assertEqual(result['核验状态'], '异常（商品/规格不一致）')
                self.assertIn(reason, result['冲突项目'])

    def test_pair_conversion_and_package_multiplication(self):
        for sku, name in [('足贴60片', '足贴艾草30对'), ('鞋垫40片', '鞋垫5对*4包'), ('暖贴30片*2包', '暖贴60片')]:
            with self.subTest(sku=sku):
                self.assertEqual(self.audit(sku, name, sku)['核验状态'], '核对通过')

    def test_three_in_one_ratio_is_ignored(self):
        result = self.audit('三合一暖贴20片（艾草10+益母草5+生姜5）', '三合一暖贴20片（艾草5+益母草5+生姜10）')
        self.assertEqual(result['核验状态'], '核对通过')

    def test_cartoon_and_erp_style_words_are_not_explicit_conflict(self):
        self.assertEqual(self.audit('卡通暖贴60片', 'KT经典暖贴60片')['核验状态'], '核对通过')

    def test_xxl_and_2xl_notation(self):
        self.assertEqual(self.audit('黑色护腰XXL送艾草暖贴20片', '黑色护腰2XL送艾草暖贴20片', '护腰')['核验状态'], '核对通过')

    def test_bundle_same_total_but_different_components(self):
        result = self.audit('暖贴40片+足贴40片', '暖贴60片+足贴20片')
        self.assertEqual(result['核验状态'], '异常（商品/规格不一致）')
        self.assertIn('套装暖贴数量', result['冲突项目'])

    def test_bundle_pair_conversion(self):
        self.assertEqual(self.audit('暖贴40片+足贴40片', '暖贴40片+足贴20对')['核验状态'], '核对通过')

    def test_bundle_total_is_not_the_gift_component_quantity(self):
        result = self.audit('通用暖贴,买40送40足贴【到手80片】', '通用暖贴40片+经典足贴40片')
        self.assertEqual(result['核验状态'], '核对通过')

    def test_equal_main_and_gift_counts_are_added(self):
        self.assertEqual(self.audit('50片送50片【穿戴式暖手宝】', '穿戴式暖手足宝100片', '暖手宝')['核验状态'], '核对通过')

    def test_overall_total_is_not_attached_to_the_nearest_named_gift(self):
        result = self.audit('买20片送10片【到手30片】;艾草暖膝贴【买即送护膝2只】', '暖膝贴30片送护膝1对', '暖膝贴')
        # 2026-10-28: unresolved bundle units require confirmation; a pair of
        # knee supports is not covered by the foot-patch pair/piece permission.
        self.assertEqual(result['核验状态'], '待人工确认')
        self.assertIn('组成单位不可比较',result['核验说明'])

    def test_per_box_quantity_without_box_count_is_not_total(self):
        # 2026-10-28: an explicit package rate without a total is pending.
        self.assertEqual(self.audit('四合一眼罩【10片/盒】', '四合一眼罩40片盒装', '眼罩')['核验状态'], '待人工确认')

    def test_single_product_quantity_vs_bundle_component(self):
        self.assertEqual(self.audit('暖贴60片', '暖贴40片+足贴20片')['核验状态'], '异常（商品/规格不一致）')

    def test_duplicate_erp_code_with_conflicting_specs_is_retained(self):
        result = self.audit('暖贴60片', '暖贴60片', extra=[erp_record('000123', '暖贴100片', '单品')])
        self.assertEqual(result['核验状态'], '待人工确认')
        self.assertEqual(result['当前编码ERP记录数'], 2)

    def test_identical_erp_rows_do_not_require_identity_uniqueness(self):
        result = self.audit('暖贴60片', '暖贴60片', extra=[erp_record('000123', '暖贴60片', '单品')])
        self.assertEqual(result['核验状态'], '核对通过')
        self.assertIn('单品', result['ERP数据来源'])

    def test_conflicting_duplicate_specs_with_incomplete_record_between(self):
        result = self.audit('经济装', '暖贴60片', extra=[erp_record('000123','暖贴'), erp_record('000123','暖贴100片')])
        self.assertEqual(result['核验状态'], '待人工确认')

    def test_confirmed_size_table_detects_wrong_numeric_size(self):
        record = erp_record('A', '防雨鞋套919透明 34/35码')
        pf = v.build_features('防雨鞋套', '尺码:XL;颜色分类:中筒透明色◆PVC材质;')
        pf['context'] = {'平台':'天猫','商品 ID':'702219298599'}
        result = v.audit_current_code('A', pf, {'A':[record]}, [record])
        self.assertIn('数字尺码/尺寸不一致', result['冲突项目'])

    def test_919_size_table_does_not_apply_to_939(self):
        record = erp_record('A', '防雨鞋套939透明 34/35码')
        pf = v.build_features('防雨鞋套', '尺码:XL;颜色分类:高筒透明色◆PVC材质;')
        pf['context'] = {'平台':'天猫','商品 ID':'702219298599'}
        result = v.audit_current_code('A', pf, {'A':[record]}, [record])
        self.assertEqual(result['核验状态'], '核对通过')

    def test_confirmed_product_model_detects_wrong_model(self):
        record = erp_record('A', '防雨鞋套919透明 34/35码')
        pf = v.build_features('防雨鞋套', '尺码:L;颜色分类:高筒透明色◆PVC材质;')
        pf['context'] = {'平台':'天猫','商品 ID':'702219298599'}
        result = v.audit_current_code('A', pf, {'A':[record]}, [record])
        self.assertIn('型号不一致', result['冲突项目'])

    def test_random_color_does_not_imply_a_fixed_color(self):
        result = self.audit('蓝色或粉色随机色PVC手套M码100只', '透明PVC手套M码100只', '手套')
        self.assertEqual(result['核验状态'], '核对通过')

    def test_full_pipeline_preserves_leading_zero_and_duplicate_sku(self):
        raw = [{'商品ID':'001', 'skuID':'002', '商品标题':'暖贴', 'sku名称':'暖贴60片', 'sku编码':'000123'},
               {'商品ID':'001', 'skuID':'002', '商品标题':'暖贴', 'sku名称':'暖贴100片', 'sku编码':'000123'}]
        record = erp_record('000123', '暖贴60片')
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / '快手.csv'
            pd.DataFrame(raw).to_csv(file, index=False, encoding='utf-8-sig')
            result, _ = v.verify_platform_file(str(file), [record], {'000123':[record]}, confirmed_entries={})
        self.assertEqual(result['原编码'].tolist(), ['000123', '000123'])
        self.assertEqual(result['核验状态'].tolist(), ['核对通过', '异常（商品/规格不一致）'])
        self.assertEqual(len(result), 2)

    def test_alternative_platform_field_names(self):
        record = erp_record('000123', '暖贴60片')
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'shop.csv'
            pd.DataFrame([{'itemId':'001','variantId':'002','title':'暖贴','销售属性':'暖贴60片','outerId':'000123'}]).to_csv(file,index=False,encoding='utf-8-sig')
            result, _ = v.verify_platform_file(str(file), [record], {'000123':[record]}, confirmed_entries={})
        self.assertEqual(result.iloc[0]['核验状态'], '核对通过')
        self.assertEqual(result.iloc[0]['商品 ID'], '001')


if __name__ == '__main__':
    unittest.main()
