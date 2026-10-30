import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import verify_codes as v
from test_matching import erp_record


class OfferRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):v.load_alias_config()

    def audit(self,spec,name,title='暖贴'):
        r=erp_record('A',name)
        return v.audit_current_code('A',v.build_features(title,spec),{'A':[r]},[r])

    def test_offers_with_selectors_are_complete_piece_totals(self):
        for spec,total in [('40送20片★艾草款【适用40-43码】',60),
            ('30送10片★卡通款【适用32-35码】',40),('60送40片★特惠款【适用36-39码】',100),
            ('50送50片【艾草保暖 热敷驱寒】',100),('暖贴艾草买20片送10片',30)]:
            with self.subTest(spec=spec):
                d=v.quantity_structure(spec)
                self.assertEqual(d['qty'],(total,'片'));self.assertFalse(d['incomplete'])
                self.assertEqual(d['offer_details']['total'],(total,'片'))

    def test_offer_total_mismatch_is_a_real_conflict(self):
        r=self.audit('30送20片【艾草保暖 热敷驱寒】','暖贴艾草60片')
        self.assertEqual(r['核验状态'],'异常（商品/规格不一致）')
        self.assertIn('数量不一致',r['核验说明'])

    def test_conversion_is_still_limited_to_approved_families(self):
        self.assertEqual(self.audit('40送20片★艾草款【适用40-43码】','鞋垫艾草男码30对',title='发热鞋垫')['核验状态'],'核对通过')
        self.assertNotEqual(self.audit('40送20片★艾草款','暖贴艾草30对')['核验状态'],'核对通过')

    def test_unknown_gifts_or_missing_units_are_not_inferred(self):
        for spec in ['40片送暖蛋','40片送未知商品20片','40送20片未知赠品','40送','40送20',
            '暖贴40送20片送暖蛋','暖贴40送20片送足贴10片']:
            with self.subTest(spec=spec):
                self.assertNotEqual(self.audit(spec,'暖贴60片')['核验状态'],'核对通过')

    def test_named_phone_heater_is_not_treated_as_generic_offer_prose(self):
        for spec in ['买30片送20片【手机发热宝】','买30片送20片【手机加热贴】快速发热']:
            with self.subTest(spec=spec):
                self.assertEqual(self.audit(spec,'暖贴50片')['核验状态'],'待人工确认')

    def test_different_formula_or_category_is_not_same_item(self):
        d=v.quantity_structure('艾草暖贴40送20片★生姜款')
        self.assertTrue(d['incomplete']);self.assertIsNone(d['qty'])
        self.assertNotEqual(self.audit('暖贴40片送足贴20片','暖贴60片')['核验状态'],'核对通过')
        self.assertNotEqual(self.audit('暖贴40送20片足贴','暖贴20片')['核验状态'],'核对通过')
        self.assertTrue(v.quantity_structure('暖贴40送20片未知赠品+暖贴10片')['incomplete'])
        self.assertNotEqual(self.audit('暖贴艾草40片+暖贴生姜20片','暖贴艾草60片')['核验状态'],'核对通过')

    def test_whole_offer_selector_keeps_style_and_size(self):
        self.assertEqual(self.audit('40送20片★艾草款【适用40-43码】','鞋垫艾草男码30对',title='发热鞋垫')['核验状态'],'核对通过')
        self.assertEqual(self.audit('40送20片★艾草款【适用40-43码】','鞋垫生姜男码30对',title='发热鞋垫')['核验状态'],'异常（商品/规格不一致）')

    def test_main_count_survives_oil_remark_but_unknown_main_does_not_pass(self):
        self.assertEqual(v.quantity_details('暖颈贴5片盒装*2送精油')[0],(10,'片'))
        self.assertEqual(self.audit('暖贴20片送精油','暖贴20片')['核验状态'],'核对通过')
        self.assertEqual(self.audit('暖贴10片送精油','暖贴20片')['核验状态'],'异常（商品/规格不一致）')
        self.assertEqual(v.quantity_details('二盒送精油')[0],(2,'盒'))
        self.assertNotEqual(self.audit('二盒送精油','暖贴20片')['核验状态'],'核对通过')
        self.assertNotEqual(self.audit('送精油','暖贴20片')['核验状态'],'核对通过')

    def test_oil_remark_and_three_in_one_total_policy_coexist(self):
        r=self.audit('三合一暖贴买15送5【到手20片】送精油','三合一暖贴20片')
        self.assertEqual(r['核验状态'],'核对通过')
        self.assertNotEqual(self.audit('三合一暖贴20片','暖贴艾草20片')['核验状态'],'核对通过')

    def test_raw_original_offer_and_unknown_gift_are_kept(self):
        spec='40送20片★艾草款【适用40-43码】'
        self.assertEqual(v.quantity_structure(spec)['raw'],spec)
        self.assertTrue(v.quantity_structure('暖贴20片送未知赠品')['incomplete'])
        for text,total in [('暖贴拍30送20片【到手50片】',50),('暖贴拍30送10片同款【到手40片】实惠装',40)]:
            with self.subTest(text=text):
                self.assertEqual(v.quantity_details(text)[0],(total,'片'))
                self.assertEqual(self.audit(text,'暖贴'+str(total)+'片')['核验状态'],'核对通过')


class KneePartRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):v.load_alias_config()

    def conflicts(self,title,spec,name):
        return v.current_code_conflicts(v.build_features(title,spec),v.build_features('','',erp_name=name))

    def test_title_use_of_knee_support_does_not_conflict_with_knee_patch_site(self):
        c=self.conflicts('暖火膝盖蒸汽热敷贴护膝艾草发热贴','颜色分类:【U先】2片装;','暖火暖膝热敷贴2片（蓝色）')
        self.assertFalse(c)

    def test_wearable_knee_support_does_not_become_a_patch(self):
        for spec in ['灰色护膝L','护膝2只','穿戴护膝2件']:
            with self.subTest(spec=spec):
                self.assertTrue(any('商品类型不一致' in c for c in self.conflicts('护膝',spec,'暖膝热敷贴2片')))

    def test_different_sites_are_still_conflicts(self):
        for name in ['暖颈热敷贴2片','暖足贴2片','暖腰贴2片']:
            with self.subTest(name=name):
                self.assertTrue(any('主品部位不一致' in c for c in self.conflicts('护膝热敷贴','护膝热敷贴2片',name)))

    def test_site_alias_does_not_alias_components(self):
        parts=v.audit_components('护膝2只+暖膝贴20片')
        self.assertEqual(set(parts),{'护膝','暖膝'})
        self.assertEqual(parts['护膝']['qty'],(2,'只'))
        self.assertEqual(parts['暖膝']['qty'],(20,'片'))


class RetiredReviewRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        v.load_alias_config()
        cls.records,cls.by=v.build_erp_records(v.load_erp(*v.resolve_erp_inputs()[:2]))
        cls.retired=json.loads((ROOT/'config/retired_sku_audit_reviews.json').read_text(encoding='utf-8'))['reviews']
        cls.active=v.sku_reviews.load_reviews()

    def feature(self,entry):
        c=entry['context'];f=v.build_features(c['商品标题'],c['SKU'])
        f['context']={**c,'店铺':'无人工覆盖验证'}
        f['erp_item_id']=c.get('ERP货品编号','');f['spec_code']=c.get('ERP规格编码','')
        return f

    def test_104_original_decisions_are_either_active_or_archived(self):
        self.assertEqual(len(self.retired),31)
        self.assertEqual(len(self.active),73)
        self.assertFalse(set(self.retired)&set(self.active))
        self.assertEqual(Counter(e['mode'] for e in self.active.values()),{'confirmed':55,'pending':15,'conflict':3})
        self.assertTrue(all(e['mode']=='confirmed' for e in self.retired.values()))

    def test_all_retired_decisions_work_without_runtime_review_override(self):
        for key,e in self.retired.items():
            with self.subTest(sku=e['context']['SKU ID']):
                f=self.feature(e);r=v.audit_current_code(e['source_code'],f,self.by,self.records)
                expected='核对通过' if e['source_code']==e['target_code'] else None
                if expected:self.assertEqual(r['核验状态'],expected)
                else:
                    self.assertNotEqual(r['核验状态'],'核对通过')
                    self.assertEqual(v.suggest_code_candidates(f,r,self.records,self.by)['推测商家编码'],e['target_code'])
                result,proposed=v.sku_reviews.apply_review(f['context'],e['source_code'],r,self.by,self.active)
                self.assertEqual(result,r);self.assertIsNone(proposed)
                self.assertEqual(v.audit_current_code(e['target_code'],f,self.by,self.records)['核验状态'],'核对通过')

    def test_retired_offer_works_for_a_new_sku_without_human_fingerprint(self):
        e=next(e for e in self.retired.values() if '送' in e['context']['SKU'])
        f=self.feature(e);f['context']['SKU ID']='brand-new-sku'
        r=v.audit_current_code(e['source_code'],f,self.by,self.records)
        self.assertEqual(r['核验状态'],'核对通过')
        self.assertIsNone(v.sku_reviews.apply_review(f['context'],e['source_code'],r,self.by,self.active)[1])

    def test_retired_rule_does_not_pass_an_unknown_code_or_changed_total(self):
        e=next(e for e in self.retired.values() if '40送20片' in e['context']['SKU'])
        f=self.feature(e)
        self.assertEqual(v.audit_current_code('MISSING',f,self.by,self.records)['核验状态'],'异常（ERP未找到）')
        c=e['context'];f=v.build_features(c['商品标题'],c['SKU'].replace('40送20片','40送10片'))
        self.assertEqual(v.audit_current_code(e['source_code'],f,self.by,self.records)['核验状态'],'异常（商品/规格不一致）')

    def test_all_three_in_one_single_formula_exceptions_are_still_active(self):
        ids={'100277872697338','192420633131338','192687207365338','192826814765338',
            '193145114324338','194360900475338','194509911210338'}
        self.assertTrue(ids<={e['context']['SKU ID'] for e in self.active.values()})


if __name__=='__main__':unittest.main()
