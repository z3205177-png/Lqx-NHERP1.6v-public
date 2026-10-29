import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import verify_codes as v
from test_matching import erp_record
import confirmed_business_specs as b


class ContextualFootWarmerTests(unittest.TestCase):
    def test_explicit_foot_patch_and_insole_names_remain_separate(self):
        self.assertEqual(v.extract_families('暖足贴10片'),{'足贴'})
        self.assertEqual(v.extract_families('暖火暖足宝艾草发热鞋垫'),{'发热鞋垫'})
        self.assertEqual(v.extract_families('暖足宝40对'),set())
        self.assertEqual(v.extract_families('暖足40片组合装外袋'),{'包装材料'})

    def test_unambiguous_insole_title_disambiguates_an_attribute_only_spec(self):
        r=erp_record('A','暖火艾草均码发热鞋垫粉40对')
        for n,status in [(40,'核对通过'),(30,'异常（商品/规格不一致）')]:
            pf=v.build_features('暖火暖足宝艾草发热鞋垫',f'{n}对【共{n*2}片 均码】；暖足宝')
            self.assertEqual(pf['families'],{'发热鞋垫'})
            self.assertEqual(v.audit_current_code('A',pf,{'A':[r]},[r])['核验状态'],status)

    def test_erp_ambiguous_warmer_is_not_forced_into_the_insole_category(self):
        r=erp_record('A','暖火暖足宝5对*3包（红色）')
        self.assertNotIn('发热鞋垫',r['features']['families'])
        pf=v.build_features('蒸汽暖足贴','蒸汽暖足贴30片')
        self.assertEqual(v.audit_current_code('A',pf,{'A':[r]},[r])['核验状态'],'核对通过')
        self.assertNotEqual(v.audit_current_code('A',v.build_features('蒸汽暖足贴','蒸汽暖足贴40片'),{'A':[r]},[r])['核验状态'],'核对通过')

    def test_marketing_tail_does_not_restore_a_broad_product_alias(self):
        self.assertFalse(v.quantity_structure('买3送2【到手50片】暖身先暖足')['incomplete'])
        self.assertTrue(v.quantity_structure('暖贴买20送10【到手30片】暖身先暖足耳塞')['incomplete'])


class LayeredPackagingTests(unittest.TestCase):
    def test_outer_package_count_is_not_multiplied_by_inner_items(self):
        for spec,qty in [('40包*10抽',(40,'包')),('10包*80抽',(10,'包')),
                         ('3盒×20张',(3,'盒')),('6袋*5段',(6,'袋'))]:
            self.assertEqual(v.quantity_details(spec)[0],qty)
            self.assertFalse(v.quantity_structure(spec)['incomplete'])

    def test_inner_total_is_recorded_with_its_own_unit(self):
        detail=v.quantity_structure('40包*10抽')['packaging_details'][0]
        self.assertEqual(detail['outer_quantity'],(40,'包'))
        self.assertEqual(detail['per_package'],(10,'抽'))
        self.assertEqual(detail['inner_total'],(400,'抽'))

    def test_outer_count_is_compared_to_erp_and_wrong_count_is_kept(self):
        for count,status in [(40,'核对通过'),(30,'异常（商品/规格不一致）')]:
            r=erp_record('A',f'加厚湿巾{count}包')
            pf=v.build_features('湿巾','40包*10抽')
            self.assertEqual(v.audit_current_code('A',pf,{'A':[r]},[r])['核验状态'],status)

    def test_real_pack_multipliers_keep_their_original_meaning(self):
        for text,qty in [('10片*3盒',(30,'片')),('5片×10包',(50,'片')),('5片袋装*5',(25,'片'))]:
            self.assertEqual(v.quantity_details(text)[0],qty)

    def test_unestablished_count_relationship_is_still_pending(self):
        for text in ['5包*10片','10片*3抽','40包*0抽','40包*10抽*2盒']:
            self.assertIsNone(v.quantity_details(text)[0])
            self.assertTrue(v.quantity_structure(text)['incomplete'])

    def test_inner_count_does_not_use_the_bare_multiplier_limit(self):
        self.assertEqual(v.quantity_details('10包*200抽')[0],(10,'包'))

    def test_shared_count_units_are_unchanged(self):
        self.assertEqual(v.COUNT_UNITS,r'片|对|包|袋|只|双|个|件|盒|副|套')

    def test_uncomparable_erp_count_is_not_silently_passed(self):
        for name in ['湿巾300抽','湿巾1盒','湿巾数量不明']:
            r=erp_record('A',name)
            result=v.audit_current_code('A',v.build_features('湿巾','40包*10抽'),{'A':[r]},[r])
            self.assertEqual(result['核验状态'],'待人工确认')
            self.assertIn('外包装数量未建立可比对应关系',result['冲突项目'])

    def test_packaging_incompleteness_is_checked_on_both_sides(self):
        r=erp_record('A','湿巾40包*10抽')
        result=v.audit_current_code('A',v.build_features('湿巾','湿巾300抽'),{'A':[r]},[r])
        self.assertEqual(result['核验状态'],'待人工确认')


class AccessoryLabelTests(unittest.TestCase):
    def test_all_user_facing_quantity_and_unit_labels_are_chinese(self):
        for kind,label in b.ACCESSORY_LABELS.items():
            pf={'business_accessories':{kind:{'text':'赠品','qty':(1,'个')}}}
            ef={'business_accessories':{kind:{'text':'赠品','qty':(2,'个')}}}
            conflicts,_=b.accessory_conflicts(pf,ef)
            self.assertEqual(conflicts,['附赠品数量不一致：'+label])
            ef['business_accessories'][kind]['qty']=(1,'只')
            _,issues=b.accessory_conflicts(pf,ef)
            self.assertEqual(issues,['附赠品单位尚未确认换算：'+label])

    def test_shell_count_conflict_remains_a_conflict(self):
        pf=b.accessory_feature(v.build_features('','暖手贴60片送暖蛋'),['shell'],v.build_features)
        ef=b.accessory_feature(v.build_features('','暖手贴60片送2个KT蛋壳'),['shell'],v.build_features)
        conflicts,_=b.accessory_conflicts(pf,ef)
        self.assertEqual(conflicts,['附赠品数量不一致：蛋壳/暖蛋'])

    def test_color_and_material_labels_do_not_expose_enum_names(self):
        pf={'business_accessories':{'cover':{'text':'红色纯棉布套','qty':None}}}
        ef={'business_accessories':{'cover':{'text':'蓝色毛绒布套','qty':None}}}
        conflicts,_=b.accessory_conflicts(pf,ef)
        self.assertEqual(conflicts,['附赠品颜色不一致：布套','附赠品材质不一致：布套'])


if __name__=='__main__':unittest.main()
