"""Boundaries of user-confirmed agricultural policies (2026-10-29)."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import agricultural_specs as a
import verify_codes as v
from test_matching import erp_record

PASS='核对通过'
PENDING='待人工确认'
CONFLICT='异常（商品/规格不一致）'


class AgriculturalPolicyTests(unittest.TestCase):
    def audit(self,p,e,title='大蒜',**extra):
        record=erp_record('A',e);record.update(extra)
        return v.audit_current_code('A',v.build_features(title,p),{'A':[record]},[record])

    def test_gross_requires_both_limits_and_erp_denominator(self):
        for p,e,state in [('含箱净重550g','大蒜500g',PASS),('含箱净重551g','大蒜500g',CONFLICT),
            ('含包装净重220g','大蒜200g',PASS),('含包装净重221g','大蒜200g',CONFLICT),
            ('含箱净重250g','大蒜200g',CONFLICT),('含箱净重1100g','大蒜1000g',CONFLICT),
            ('含箱净重550.15g','大蒜500.15g',PASS),('含箱净重550.16g','大蒜500.15g',CONFLICT)]:
            with self.subTest(p=p,e=e):self.assertEqual(self.audit(p,e)['核验状态'],state)

    def test_gross_lower_bound_has_no_artificial_upper_limit(self):
        for p,e,state in [('含箱净重1500g+','大蒜2000g',PASS),('含箱净重1500g+','大蒜1500g',PASS),
            ('含箱净重1500g+','大蒜1450g',PASS),('含箱净重1500g+','大蒜1449g',CONFLICT),
            ('含箱净重500g+','大蒜500g+',PENDING)]:
            with self.subTest(p=p,e=e):self.assertEqual(self.audit(p,e)['核验状态'],state)

    def test_tolerance_is_once_on_total_not_per_container(self):
        self.assertEqual(self.audit('蒜米3桶 含箱净重1600g','蒜米500g*3桶')['核验状态'],CONFLICT)
        self.assertEqual(self.audit('蒜米3桶 含箱净重1550g','蒜米500g*3桶')['核验状态'],PASS)

    def test_gross_language_is_tied_to_the_weight_expression(self):
        for marker in ('含外包装净重','含包装净重','带箱重','含皮重','含箱重','毛重'):
            with self.subTest(marker=marker):self.assertEqual(self.audit(marker+'550g','大蒜500g')['核验状态'],PASS)
        self.assertEqual(self.audit('带箱发货，净重550g','大蒜500g')['核验状态'],CONFLICT)
        self.assertEqual(self.audit('净重550g','大蒜500g')['核验状态'],CONFLICT)
        self.assertEqual(self.audit('净重550g','大蒜500g',title='大蒜含箱发货')['核验状态'],CONFLICT)

    def test_gross_does_not_erase_explicit_net_conflict(self):
        self.assertEqual(self.audit('净重400g 含箱重500g','大蒜500g')['核验状态'],CONFLICT)
        self.assertEqual(self.audit('含箱重500g','大蒜')['核验状态'],PENDING)

    def test_ginger_garlic_bags_and_total_are_checked(self):
        self.assertEqual(self.audit('姜蒜结合4兜2斤6:4','姜蒜组合250g*4袋')['核验状态'],PASS)
        self.assertEqual(self.audit('姜蒜结合4兜','姜蒜组合250g*4袋')['核验状态'],PASS)
        self.assertEqual(self.audit('姜蒜结合4兜2斤','姜蒜组合250g*3袋')['核验状态'],CONFLICT)
        self.assertEqual(self.audit('姜蒜结合4兜净重900g','姜蒜组合250g*4袋')['核验状态'],CONFLICT)
        self.assertEqual(self.audit('姜蒜结合4兜含箱重1100g','姜蒜组合250g*4袋')['核验状态'],CONFLICT)

    def test_other_ratios_and_other_product_units_do_not_inherit_policy(self):
        for ratio in ('7:3','0:0','6:0'):
            with self.subTest(ratio=ratio):self.assertEqual(self.audit('姜蒜组合250g'+ratio,'姜蒜组合250g')['核验状态'],CONFLICT)
        self.assertEqual(self.audit('姜蒜组合250g3:2','姜蒜组合250g')['核验状态'],PASS)
        self.assertEqual(self.audit('蒜米2兜500g','蒜米250g*2袋')['核验状态'],PENDING)
        self.assertIsNone(a.parse_spec('20片6:4','生姜暖贴'))

    def test_ginger_garlic_erp_ratio_is_also_validated(self):
        self.assertEqual(self.audit('姜蒜组合250g6:4','姜蒜组合250g7:3')['核验状态'],CONFLICT)
        self.assertEqual(self.audit('姜蒜组合200g*2袋','姜蒜组合200g*2袋')['核验状态'],CONFLICT)

    def test_missing_erp_grade_waiver_is_only_for_matching_peeled_garlic(self):
        self.assertEqual(self.audit('独头蒜米2.5cm100g*2袋','独头蒜米100g*2包')['核验状态'],PASS)
        self.assertEqual(self.audit('蒜米2.5cm500g','蒜米500g')['核验状态'],PASS)
        self.assertEqual(self.audit('干蒜5-5.5cm500g','干蒜500g')['核验状态'],PENDING)
        self.assertEqual(self.audit('独头蒜米2.5cm500g','独头蒜米4cm500g')['核验状态'],CONFLICT)
        self.assertEqual(self.audit('独头蒜米2.5cm500g','蒜米500g')['核验状态'],CONFLICT)

    def test_count_only_requires_matching_counts_kind_and_grade(self):
        self.assertEqual(self.audit('干蒜3头5-5.5cm','干蒜3头网兜5-5.5cm')['核验状态'],PASS)
        for e,state in [('干蒜5头网兜5-5.5cm',CONFLICT),('鲜蒜3头5-5.5cm',CONFLICT),
            ('干蒜3头6cm',CONFLICT),('干蒜5-5.5cm',PENDING)]:
            with self.subTest(e=e):self.assertEqual(self.audit('干蒜3头5-5.5cm',e)['核验状态'],state)
        self.assertEqual(self.audit('干蒜3头500g','干蒜3头')['核验状态'],PENDING)
        self.assertEqual(self.audit('蒜米3袋','蒜米3包')['核验状态'],PENDING)

    def test_gifts_are_ignored_but_main_weight_is_still_checked(self):
        self.assertEqual(self.audit('蒜米500g送生姜100g','蒜米500g送生姜300g')['核验状态'],PASS)
        self.assertEqual(self.audit('蒜米500g赠姜','蒜米500g')['核验状态'],PASS)
        self.assertEqual(self.audit('蒜米400g赠姜','蒜米500g')['核验状态'],CONFLICT)
        self.assertEqual(self.audit('赠姜100g','大蒜500g')['核验状态'],PENDING)

    def test_gift_in_erp_total_does_not_replace_main_net(self):
        result=self.audit('蒜米2000g赠姜','蒜米送生姜100g',net_weight_kg='2.1')
        self.assertEqual(result['核验状态'],PASS)
        erp=json.loads(result['农产品解析JSON'])['erp'][0]
        self.assertEqual(erp['net']['g'],2000)
        self.assertEqual(self.audit('蒜米2100g赠姜','蒜米送生姜100g',net_weight_kg='2.1')['核验状态'],CONFLICT)
        self.assertEqual(self.audit('蒜米2000g赠姜','蒜米送生姜一份',net_weight_kg='2.1')['核验状态'],PENDING)


class ScopedAgriculturalPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records,cls.by=v.build_erp_records(v.load_erp(*v.resolve_erp_inputs()[:2]))

    def feature(self,entry):
        c=entry['context'];f=v.build_features(c['商品标题'],c['SKU'])
        f['agricultural']=a.parse_spec(c['SKU'],c['商品标题'],c['农产品店内分类'])
        f['context']=deepcopy(c)
        return f

    def test_exact_four_missing_weight_exceptions_expire_on_changed_identity_or_erp(self):
        entries=[e for e in a.load_facts()['rows'].values() if e.get('allow_missing_erp_weight')]
        self.assertEqual({e['context']['SKU ID'] for e in entries},
            {'10226375688299','10226390756354','10231652532445','10237531761170'})
        for e in entries:
            with self.subTest(sku=e['context']['SKU ID']):
                f=self.feature(e);code=e['current_code']
                r=a.audit(f,code,self.by)
                self.assertEqual(r['核验状态'],PASS);self.assertIn('重量未核',r['核验说明'])
                f['context']['SKU ID']='new'
                self.assertEqual(a.audit(f,code,self.by)['核验状态'],PENDING)
                f=self.feature(e);f['context']['SKU']+='新内容'
                self.assertIn('已失效',a.audit(f,code,self.by)['核验说明'])
                r=deepcopy(self.by[code][0]);r['erp_fingerprint']='changed'
                self.assertIn('ERP记录变化',a.audit(self.feature(e),code,{**self.by,code:[r]})['核验说明'])

    def test_missing_weight_exception_does_not_clear_count_or_grade_conflict(self):
        e=next(e for e in a.load_facts()['rows'].values() if e['context']['SKU ID']=='10226375688299')
        for key,value in [('grade','错误档位'),('heads',999),('packs',{'n':999,'unit':'条'})]:
            with self.subTest(key=key):
                f=self.feature(e);f['agricultural'][key]=value
                self.assertEqual(a.audit(f,e['current_code'],self.by)['核验状态'],CONFLICT)

    def test_missing_weight_exception_does_not_clear_missing_pack_evidence(self):
        e=next(e for e in a.load_facts()['rows'].values() if e['context']['SKU ID']=='10231652532445')
        f=self.feature(e);f['agricultural']['packs']={'n':2,'unit':'条'}
        result=a.audit(f,e['current_code'],self.by)
        self.assertEqual(result['核验状态'],PENDING)
        self.assertIn('ERP包装数量/形式未明确',result['核验说明'])

    def test_bucket_facts_are_500_with_original_450_history(self):
        entries=[e for e in a.load_facts()['rows'].values() if e['current_code'] in {'NCP04701','NCP04801','NCP04901'}]
        self.assertEqual(len(entries),3)
        for e in entries:
            self.assertEqual(e['pack_g'],500)
            self.assertEqual(e['history'][0]['previous_pack_g'],450)
            r=a.audit(self.feature(e),e['current_code'],self.by)
            self.assertEqual(r['核验状态'],PASS)
            self.assertNotIn('含包装重量按整单',r['核验说明'])


if __name__=='__main__':unittest.main()
