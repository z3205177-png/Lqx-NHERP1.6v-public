import copy
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import confirmed_business_specs as b
import verify_codes as v


class ConfirmedBusinessSpecsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records,cls.index=v.build_erp_records(v.load_erp(str(ROOT/'data/组合装.csv'),str(ROOT/'data/单品.csv')))

    def audit(self,code,sku,title='',context=None,index=None):
        feature=v.build_features(title,sku)
        feature['context']=context or {}
        return v.audit_current_code(code,feature,index or self.index,self.records)

    def registered_spec(self,code):
        return b.load_rules()['products'][code]['specs'][0]

    def test_all_decision_definitions_exist_but_are_not_verdicts(self):
        config=b.load_rules()
        self.assertEqual(len(config['rules']),34)
        self.assertEqual(len(config['pending']),4)
        for product in config['products'].values():
            self.assertNotIn('verdict',product)
            self.assertTrue(product['erp_fingerprint'])

    def test_recipe_is_shared_with_other_platform_and_title_edits(self):
        sku=self.registered_spec('NHCP02001020')['original_spec']
        for platform in ['京东','快手','小红书']:
            result=self.audit('NHCP02001020',sku,'新标题',{'平台':platform,'SKU ID':'new'})
            self.assertEqual(result['核验状态'],'核对通过')
            self.assertIn('09.1',result['业务口径依据'])

    def test_equal_total_with_different_recipe_cannot_pass(self):
        result=self.audit('NHCP02001020','艾草暖贴15片+生姜暖贴5片')
        self.assertNotEqual(result['核验状态'],'核对通过')
        self.assertIn('数量不一致',result['冲突项目'])

    def test_unknown_new_composition_cannot_borrow_known_erp_recipe(self):
        result=self.audit('NHCP02001020','艾草暖贴+生姜暖贴共20片')
        self.assertEqual(result['核验状态'],'待人工确认')

    def test_exact_size_confirmation_keeps_its_sku_identity(self):
        spec=self.registered_spec('NHCP1240101012')
        good=self.audit('NHCP1240101012',spec['original_spec'],context=spec['identity'])
        other=self.audit('NHCP1240101012',spec['original_spec'],context={'平台':'天猫','SKU ID':'new'})
        self.assertEqual(good['核验状态'],'核对通过')
        self.assertNotEqual(other['核验状态'],'核对通过')

    def test_changed_erp_or_duplicate_binding_is_not_reused(self):
        code='NHCP02001020'; sku=self.registered_spec(code)['original_spec']
        changed=copy.deepcopy(self.index[code][0]); changed['erp_fingerprint']='changed'
        for records in [[changed],[self.index[code][0],copy.deepcopy(self.index[code][0])]]:
            result=self.audit(code,sku,index={**self.index,code:records})
            self.assertNotEqual(result['核验状态'],'核对通过')

    def test_independent_quantity_change_does_not_match_exact_spec(self):
        code='NH85101'; entry=self.registered_spec(code)
        pf=v.build_features('眼罩',entry['original_spec'])
        pf['qty']=(99,'片');pf['context']={'独立规格数量':'99片'}
        prepared,_=b.transform_platform(pf,code,self.index[code],v.build_features)
        self.assertEqual(prepared['qty'],(99,'片'))
        self.assertNotIn('confirmed_components',prepared)

    def test_oil_is_not_a_patch_and_main_quantity_conflict_remains(self):
        code='NHCP17701031284'
        self.assertEqual(self.audit(code,'15片热敷暖腰带送艾草精油')['核验状态'],'核对通过')
        self.assertNotEqual(self.audit(code,'30片热敷暖腰带送艾草精油')['核验状态'],'核对通过')
        self.assertNotEqual(self.audit(code,'15片热敷暖腰带送KT精油贴')['核验状态'],'核对通过')

    def test_explicit_oil_quantity_is_still_compared(self):
        feature=v.build_features('','暖贴20片送精油2瓶')
        a=b.accessory_feature(feature,['oil'],v.build_features)
        z=b.accessory_feature(v.build_features('','暖贴20片送精油1瓶'),['oil'],v.build_features)
        self.assertIn('附赠品数量不一致',b.accessory_conflicts(a,z)[0][0])

    def test_cover_absence_does_not_drop_bottle_capacity(self):
        self.assertEqual(self.audit('RSD03201','灰色U型热水袋1200ML送超柔布套')['核验状态'],'核对通过')
        self.assertNotEqual(self.audit('RSD03201','灰色U型热水袋1400ML送超柔布套')['核验状态'],'核对通过')

    def test_shell_color_and_explicit_shell_count_are_checked_separately(self):
        a=b.accessory_feature(v.build_features('','小暖手贴20片送蓝色蛋壳2个'),['shell'],v.build_features)
        z=b.accessory_feature(v.build_features('','小暖手贴20片送粉色蛋壳'),['shell'],v.build_features)
        conflicts,_=b.accessory_conflicts(a,z)
        self.assertTrue(any('数量不一致' in x for x in conflicts))
        self.assertTrue(any('颜色不一致' in x for x in conflicts))
        self.assertEqual(a['qty'],(20,'片'))

    def test_patch_piece_and_support_piece_are_not_combined(self):
        code='NH55902'; entry=self.registered_spec(code)
        prepared,_=b.transform_platform(v.build_features('',entry['original_spec']),code,self.index[code],v.build_features)
        self.assertIsNone(prepared['qty'])
        self.assertEqual(prepared['confirmed_components']['护膝']['qty'],(2,'只'))
        self.assertEqual(prepared['confirmed_components']['暖膝']['qty'],(20,'片'))

    def test_warming_core_series_cannot_be_substituted(self):
        pf=v.build_features('','小黄鸭暖手贴20片')
        ef=v.build_features('','小魔仙暖手贴20片')
        self.assertIn('暖芯系列不一致',v.current_code_conflicts(pf,ef))

    def test_finished_box_does_not_authorize_new_box_codes(self):
        self.assertEqual(self.audit('CH04101','生姜暖贴30片')['核验状态'],'核对通过')
        self.assertNotEqual(self.audit('CH04101','生姜暖贴40片')['核验状态'],'核对通过')
        self.assertNotEqual(self.audit('CH04101','艾草暖贴30片')['核验状态'],'核对通过')

    def test_erp_typo_interpretation_keeps_original_name(self):
        r=self.index['NH4573038610'][0]
        self.assertEqual(r['name'],'KT经典暖贴30盒装送KT足贴10对')
        self.assertEqual(r['features']['confirmed_components']['暖贴']['qty'],(30,'片'))

    def test_mixed_shoe_cover_materials_keep_their_counts(self):
        self.assertNotEqual(self.audit('NH1485013011','无纺布鞋套50只+CPE鞋套100只')['核验状态'],'核对通过')
        self.assertIsNone(v.quantity_compare((25,'双'),(50,'只'),{'鞋套'}))

    def test_essential_oil_patch_has_its_own_component(self):
        code='NH0160297101'; entry=self.registered_spec(code)
        self.assertEqual(self.audit(code,entry['original_spec'])['核验状态'],'核对通过')
        record=self.index[code][0]
        self.assertEqual(record['features']['confirmed_components']['精油贴']['qty'],(24,'枚'))
        self.assertIsNone(v.quantity_compare((24,'枚'),(24,'片'),set()))

    def test_all_four_deferred_rows_remain_pending(self):
        for item in b.load_rules()['pending']:
            result=self.audit(item['reference_code'],'优惠装',context=item['identity'])
            self.assertEqual(result['核验状态'],'待人工确认')

    def test_component_size_uses_the_existing_xxl_equivalence(self):
        a=v.build_features('护腰','黑色护腰XXL送艾草暖贴20片')
        z=v.build_features('','',erp_name='黑色护腰2XL送艾草暖贴20片')
        self.assertEqual(v.current_code_conflicts(a,z),[])

    def test_selected_spec_normalization_preserves_word_boundaries(self):
        self.assertNotEqual(b.selected_spec('双插手 套餐'),b.selected_spec('双插手套餐'))

    def test_different_scent_quantities_cannot_be_combined(self):
        a=v.build_features('眼罩','蒸汽眼罩玫瑰5片+蒸汽眼罩无香15片')
        z=v.build_features('','',erp_name='蒸汽眼罩玫瑰10片+蒸汽眼罩无香10片')
        self.assertTrue(any('数量不一致' in x for x in v.current_code_conflicts(a,z)))

    def test_different_shoe_materials_cannot_be_combined(self):
        a=v.build_features('鞋套','无纺布鞋套50只+CPE鞋套100只')
        z=v.build_features('','',erp_name='无纺布鞋套100只+CPE鞋套50只')
        self.assertTrue(any('数量不一致' in x for x in v.current_code_conflicts(a,z)))

    def test_explicit_two_shell_record_keeps_difference_from_default_one(self):
        result=self.audit('NH5500106005','颜色分类:40片送20片【小暖手送暖蛋】;')
        self.assertEqual(result['核验状态'],'异常（商品/规格不一致）')
        self.assertIn('附赠品数量不一致',result['冲突项目'])

    def test_shell_bare_count_and_abbreviated_color_are_not_lost(self):
        a=b.accessory_feature(v.build_features('','暖手贴20片送2蓝色蛋壳'),['shell'],v.build_features)
        z=b.accessory_feature(v.build_features('','暖手贴20片送1KT白蛋壳'),['shell'],v.build_features)
        conflicts,_=b.accessory_conflicts(a,z)
        self.assertTrue(any('数量不一致' in x for x in conflicts))
        self.assertTrue(any('颜色不一致' in x for x in conflicts))


class QuantityBoundaryFollowupTests(unittest.TestCase):
    def test_parenthetical_total_breakdown_is_not_an_additional_bundle(self):
        self.assertEqual(v.quantity_details('暖贴20片(10片+10片)')[0],(20,'片'))
        self.assertTrue(v.quantity_structure('暖贴20片(10片+15片)')['incomplete'])

    def test_weight_multiplier_is_not_a_bag_count(self):
        self.assertEqual(v.quantity_details('除湿袋20袋(250克*20)')[0],(20,'袋'))

    def test_explicit_chinese_outer_count_and_rate_can_be_multiplied(self):
        self.assertEqual(v.quantity_details('两盒装暖膝贴5片/盒')[0],(10,'片'))
        self.assertIsNone(v.quantity_details('暖膝贴5片/盒')[0])

    def test_negation_does_not_create_an_unknown_gift(self):
        self.assertFalse(v.quantity_structure('经典暖贴30片【不含赠品】')['incomplete'])
        self.assertTrue(v.quantity_structure('经典暖贴30片送未知赠品')['incomplete'])

    def test_marketing_one_box_is_not_an_outer_box_count(self):
        self.assertFalse(v.quantity_structure('艾草暖贴买40送20【到手60片】满满一盒更划算')['incomplete'])


if __name__=='__main__':unittest.main()
