import json
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import agricultural_specs as a
import verify_codes as v
from test_matching import erp_record


class AgriculturalTests(unittest.TestCase):
    def compare(self,p,e,title='大蒜',**extra):
        record=erp_record('A',e);record.update(extra)
        return v.audit_current_code('A',v.build_features(title,p),{'A':[record]},[record])

    def test_kg_g_and_jin_have_consistent_net_units(self):
        for left,right in [('5斤','2.5kg'),('1000克','1公斤'),('0.5千克','500g'),('1市斤','500克')]:
            with self.subTest(left=left):
                self.assertEqual(self.compare(left,'大蒜'+right)['核验状态'],'核对通过')

    def test_five_jin_is_not_one_and_half_kg(self):
        r=self.compare('5斤','大蒜1.5KG')
        self.assertEqual(r['核验状态'],'异常（商品/规格不一致）')

    def test_lower_bound_is_not_exact_weight(self):
        self.assertEqual(self.compare('净重500g+','大蒜600g')['核验状态'],'核对通过')
        self.assertEqual(self.compare('净重500g+','大蒜400g')['核验状态'],'异常（商品/规格不一致）')
        self.assertEqual(self.compare('净重500g','大蒜600g')['核验状态'],'异常（商品/规格不一致）')
        self.assertEqual(self.compare('净重500g+','大蒜400g+')['核验状态'],'待人工确认')

    def test_gross_never_proves_net(self):
        r=self.compare('含箱净重500g+','大蒜500g')
        self.assertEqual(r['核验状态'],'待人工确认')
        self.assertIn('需人工核重',r['核验说明'])
        d=json.loads(r['农产品解析JSON'])
        self.assertIsNone(d['platform']['net'])
        self.assertEqual(d['platform']['gross'],{'g':500,'bound':'min'})

    def test_same_total_different_bag_composition_conflicts(self):
        r=self.compare('蒜米500g*2袋','蒜米1000g*1包')
        self.assertEqual(r['核验状态'],'异常（商品/规格不一致）')
        self.assertIn('每包净重',r['核验说明'])

    def test_rate_plus_count_multiplies_on_both_sides(self):
        self.assertEqual(self.compare('2包装 每包净重2斤','蒜米1000g*2包',title='蒜米')['核验状态'],'核对通过')
        self.assertEqual(self.compare('2包装 每包净重2斤','蒜米1000g*3包',title='蒜米')['核验状态'],'异常（商品/规格不一致）')

    def test_missing_pack_count_is_pending(self):
        self.assertEqual(self.compare('每袋100g','蒜米100g*5包',title='蒜米')['核验状态'],'待人工确认')

    def test_dry_fresh_and_single_clove_stay_distinct(self):
        for p,e in [('干蒜1斤','鲜蒜1斤'),('独头蒜500g','干蒜500g'),('蒜米500g','独头蒜米500g')]:
            self.assertEqual(self.compare(p,e)['核验状态'],'异常（商品/规格不一致）')

    def test_approved_diameter_grades(self):
        for p,e in [('45-50mm','4.5cm'),('50-55mm','5.0-5.5cm'),('≥60mm','6.0cm')]:
            self.assertEqual(self.compare('干蒜净重1斤 '+p,'干蒜1斤 '+e)['核验状态'],'核对通过')
        self.assertEqual(self.compare('干蒜1斤50-55mm','干蒜1斤6cm')['核验状态'],'异常（商品/规格不一致）')

    def test_single_clove_grade(self):
        self.assertEqual(self.compare('独头蒜1斤2.5-3cm','独头蒜2.5cm 1斤')['核验状态'],'核对通过')

    def test_five_heads_per_string_without_weight_conversion(self):
        p=a.parse_spec('干蒜5头网兜3条5-5.5cm')
        self.assertEqual(p['heads'],15)
        self.assertIsNone(p['net'])
        r=self.compare('干蒜3条5-5.5cm','干蒜5头网兜3条5-5.5cm',net_weight_kg='1.2')
        self.assertEqual(r['核验状态'],'待人工确认')
        self.assertIn('核重',r['核验说明'])

    def test_by_weight_string_does_not_mean_one_string(self):
        s=a.parse_spec('干蒜5头网兜 5斤 5-5.5cm')
        self.assertIsNone(s['packs']); self.assertIsNone(s['heads'])

    def test_erp_weight_field_is_kg_but_not_pack_count(self):
        r=self.compare('干蒜3条净重660g+5-5.5cm','干蒜5头网兜3条5-5.5cm',net_weight_kg='1.2')
        self.assertEqual(r['核验状态'],'核对通过')
        r=self.compare('干蒜2条净重1斤','干蒜5头网兜1斤',net_weight_kg='0.5')
        self.assertEqual(r['核验状态'],'待人工确认')

    def test_inconsistent_erp_field_cannot_silently_pass(self):
        r=self.compare('蒜米1000g*2包','蒜米1000g*2包',net_weight_kg='3')
        self.assertEqual(r['核验状态'],'待人工确认')
        self.assertIn('ERP名称净重与重量字段',r['核验说明'])

    def test_gift_weight_does_not_replace_main_weight(self):
        r=self.compare('蒜米100g*20袋送生姜100g','蒜米100g*20包送生姜100g',net_weight_kg='2.1')
        self.assertEqual(r['核验状态'],'核对通过')
        d=json.loads(r['农产品解析JSON'])
        self.assertEqual(d['platform']['kind'],'蒜米')
        self.assertEqual(d['platform']['net']['g'],2000)
        self.assertEqual(d['platform']['gift']['net']['g'],100)

    def test_badge_gift_does_not_swallow_main_spec(self):
        p=a.parse_spec('【限量·赠姜】4袋 净重400g 每袋100g·独头蒜2.5cm',title='独头蒜米')
        self.assertEqual(p['kind'],'独头蒜米')
        self.assertEqual(p['net']['g'],400)
        self.assertTrue(p['issues'])

    def test_mixed_components_compare_each_not_total(self):
        same=self.compare('干蒜1斤+生姜2斤','干蒜500g+生姜1000g')
        self.assertEqual(same['核验状态'],'核对通过')
        wrong=self.compare('干蒜1斤+生姜2斤','干蒜1000g+生姜500g')
        self.assertEqual(wrong['核验状态'],'异常（商品/规格不一致）')

    def test_unknown_ratio_is_pending(self):
        self.assertEqual(self.compare('姜蒜组合250g6:4','姜蒜组合250g')['核验状态'],'待人工确认')

    def test_unknown_multipliers_never_pass(self):
        for p in ['大蒜500g*3','大蒜100g*2*3袋']:
            self.assertEqual(self.compare(p,p)['核验状态'],'待人工确认')

    def test_ranges_and_invalid_net_fields_are_not_exact_specs(self):
        for p in ['大蒜约500g','大蒜1-2斤','大蒜0g']:
            self.assertEqual(self.compare(p,p)['核验状态'],'待人工确认')
        for field in ['NaN','Infinity','-1','bad']:
            self.assertEqual(self.compare('大蒜500g','大蒜500g',net_weight_kg=field)['核验状态'],'待人工确认')

    def test_nonfood_ginger_and_bodyweight_unchanged(self):
        for title,spec in [('生姜暖贴','20片'),('护膝','适合100-140斤'),('热水袋','重500g'),('大蒜纸箱','5斤装')]:
            self.assertIsNone(a.parse_spec(spec,title))

    def test_stale_scoped_fact_has_visible_reason(self):
        entry=next(x for x in a.load_facts()['rows'].values() if x.get('relation_confirmed'))
        context={**entry['context'],'商品标题':entry['context']['商品标题']+'新标题'}
        pf=v.build_features(context['商品标题'],context['SKU']); pf['context']=context
        record=erp_record(entry['current_code'],'干蒜5头网兜1斤5-5.5cm')
        r=a.audit(pf,entry['current_code'],{entry['current_code']:[record]})
        self.assertEqual(r['核验状态'],'待人工确认');self.assertIn('已失效',r['核验说明'])


class AgriculturalConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records,cls.by=v.build_erp_records(v.load_erp(*v.resolve_erp_inputs()[:2]))

    def feature(self,entry):
        context=entry['context']
        pf=v.build_features(context['商品标题'],context['SKU']);pf['context']=context
        return pf

    def test_all_fifteen_deferred_rows_stay_pending(self):
        entries=[e for e in a.load_facts()['rows'].values() if e.get('pending')]
        self.assertEqual(len(entries),15)
        for e in entries:
            with self.subTest(sku=e['context']['SKU ID']):
                self.assertEqual(a.audit(self.feature(e),e['current_code'],self.by)['核验状态'],'待人工确认')

    def test_two_targets_remain_conflicts_then_pass_with_correct_code(self):
        entries=[e for e in a.load_facts()['rows'].values() if e.get('target_code')]
        self.assertEqual(len(entries),2)
        for e in entries:
            pf=self.feature(e)
            original=a.audit(pf,e['current_code'],self.by)
            self.assertEqual(original['核验状态'],'异常（商品/规格不一致）')
            self.assertEqual(a.suggestions(pf,original,self.records,self.by)['推测商家编码'],e['target_code'])
            self.assertEqual(a.audit(pf,e['target_code'],self.by)['核验状态'],'核对通过')

    def test_five_string_correspondences_are_not_global_conversions(self):
        for e in a.load_facts()['rows'].values():
            if not e.get('relation_confirmed'): continue
            pf=self.feature(e)
            self.assertEqual(a.audit(pf,e['current_code'],self.by)['核验状态'],'核对通过')
            pf['context']={**pf['context'],'SKU ID':'a-new-sku'}
            self.assertEqual(a.audit(pf,e['current_code'],self.by)['核验状态'],'待人工确认')

    def test_gift_confirmation_is_local_and_erp_bound(self):
        e=next(e for e in a.load_facts()['rows'].values() if e.get('gift_g'))
        pf=self.feature(e)
        self.assertEqual(a.audit(pf,e['current_code'],self.by)['核验状态'],'核对通过')
        pf['context']={**pf['context'],'SKU ID':'new'}
        self.assertEqual(a.audit(pf,e['current_code'],self.by)['核验状态'],'待人工确认')
        pf=self.feature(e);changed=deepcopy(self.by[e['current_code']][0]);changed['erp_fingerprint']='changed'
        result=a.audit(pf,e['current_code'],{**self.by,e['current_code']:[changed]})
        self.assertEqual(result['核验状态'],'待人工确认');self.assertIn('ERP记录变化',result['核验说明'])

    def test_changed_category_and_changed_product_do_not_reuse_facts(self):
        e=next(e for e in a.load_facts()['rows'].values() if e.get('relation_confirmed'))
        pf=self.feature(e);pf['context']={**pf['context'],'农产品店内分类':'新分类'}
        self.assertIn('已失效',a.audit(pf,e['current_code'],self.by)['核验说明'])
        context={**e['context'],'商品标题':'热水袋','SKU':'热水袋2个'}
        pf=v.build_features(context['商品标题'],context['SKU']);pf['context']=context
        result=a.audit(pf,e['current_code'],self.by)
        self.assertEqual(result['核验状态'],'待人工确认')
        self.assertEqual(v.suggest_code_candidates(pf,result,self.records,self.by)['推测候选编码数'],0)


if __name__=='__main__': unittest.main()
