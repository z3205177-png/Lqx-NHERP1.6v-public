import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import verify_codes as v
from test_matching import erp_record


class PendingCleanupTests(unittest.TestCase):
    def audit(self,sku,erp,title='暖贴'):
        r=erp_record('A',erp)
        return v.audit_current_code('A',v.build_features(title,sku),{'A':[r]},[r])

    def test_negative_gift_and_generic_marketing_are_not_gifts(self):
        for spec in ['暖贴30片【不含赠品】','卡通三合一暖贴30片【多种搭配】12小时']:
            self.assertFalse(v.quantity_structure(spec)['incomplete'])
        self.assertEqual(self.audit('暖贴30片【不含赠品】','暖贴30片')['核验状态'],'核对通过')

    def test_negative_text_does_not_erase_another_real_gift(self):
        for spec in ['暖贴30片【不含赠品】送未知赠品','暖贴30片【多种搭配】送耳塞2个']:
            self.assertEqual(self.audit(spec,'暖贴30片')['核验状态'],'待人工确认')

    def test_marketing_tails_do_not_create_unknown_products(self):
        for text,n in [('买15送5【共20片】温暖双手（顺丰包邮）',20),('买2送1【到手30片】温灸热敷',30),
            ('买3送2【实发300只】超划算',300),('暖贴买30送20【到手50片】满满一盒更划算',50)]:
            detail=v.quantity_structure(text)
            self.assertFalse(detail['incomplete'],text)
            self.assertEqual(detail['qty'][0],n)

    def test_unknown_noun_in_offer_tail_remains_pending(self):
        for spec in ['暖贴买20送10【共30片】耳塞','暖贴买20送10支精油【共30片】','暖贴20片送5片未知赠品']:
            self.assertEqual(self.audit(spec,'暖贴30片')['核验状态'],'待人工确认')

    def test_chinese_promo_badge_does_not_override_explicit_total(self):
        for spec,n in [('【买三送二】益母草超值抢购款 50片装',50),('【买四送二】艾草超值抢购款60片装',60),('暖贴买二送一共30片',30)]:
            p=v.quantity_structure(spec)
            self.assertFalse(p['incomplete']);self.assertEqual(p['qty'],(n,'片'))
        self.assertEqual(self.audit('暖贴【买三送二】50片','暖贴40片')['核验状态'],'异常（商品/规格不一致）')
        self.assertTrue(v.quantity_structure('暖贴【买三送二耳塞】50片')['incomplete'])

    def test_field_boundary_is_not_an_unknown_gift(self):
        p=v.quantity_structure('{颜色分类:买30送20【到手50片】更划算， 类型:冷敷润眼贴【舒缓眼疲劳】}')
        self.assertFalse(p['incomplete']);self.assertEqual(p['qty'],(50,'片'))

    def test_explicit_gift_product_keeps_composition(self):
        p='艾草热敷贴买40送40足贴【到手80片】更划算'
        self.assertEqual(self.audit(p,'暖贴艾草40片+足贴20对')['核验状态'],'核对通过')
        self.assertNotEqual(self.audit(p,'暖贴艾草20片+足贴30对')['核验状态'],'核对通过')

    def test_count_field_named_pieces_is_an_explicit_unit(self):
        self.assertEqual(v.quantity_details('片数:30;颜色分类:三合一【艾草+益母草+生姜】;')[0],(30,'片'))
        self.assertIsNone(v.quantity_details('数量:30')[0])

    def test_parenthesized_counts_are_breakdown_not_extra(self):
        p=v.quantity_structure('暖足宝8对（3对+5对）（红色）')
        self.assertEqual(p['qty'],(8,'对'));self.assertFalse(p['incomplete']);self.assertEqual(len(p['breakdown_details']),1)
        self.assertTrue(v.quantity_structure('暖足宝8对（3对+6对）')['incomplete'])
        self.assertTrue(v.quantity_structure('暖贴10片（暖贴5片+足贴5片）')['incomplete'])

    def test_equivalent_pair_units_are_scoped(self):
        self.assertEqual(v.quantity_details('16片装/8对暖手足宝')[0],(16,'片'))
        self.assertTrue(v.quantity_structure('16片/10对暖足贴')['incomplete'])
        self.assertFalse(v.quantity_structure('16片/8对暖贴')['incomplete'])
        self.assertEqual(self.audit('16片/8对暖贴','暖贴8对')['核验状态'],'核对通过')
        self.assertEqual(self.audit('16片/8对暖贴','暖贴9对')['核验状态'],'异常（商品/规格不一致）')
        self.assertIsNone(v.quantity_compare((16,'片'),(8,'对'),{'暖贴'}))

    def test_marketing_family_text_does_not_contaminate_component(self):
        p='{颜色分类:艾草热敷贴*持续发热12小时，片数:【暖身暖足】40片暖贴+40片足贴（到手80片）}'
        self.assertEqual(self.audit(p,'暖贴艾草40片+足贴20对')['核验状态'],'核对通过')

    def test_sized_apparel_retains_both_components_without_inventing_count(self):
        spec='尺码:M码【80-100斤】;颜色分类:黑色双兜+【送20片艾草暖贴】;'
        self.assertEqual(self.audit(spec,'暖火护腰-黑色M送艾草暖贴20片',title='护腰保暖')['核验状态'],'核对通过')
        pf=v.build_features('护腰',spec)
        self.assertIsNone(v.audit_feature_components(pf)['护腰']['qty'])
        for erp in ['护腰黑色L送艾草暖贴20片','护腰黑色M送艾草暖贴30片']:
            self.assertNotEqual(self.audit(spec,erp,title='护腰')['核验状态'],'核对通过')

    def test_plus_glyph_and_unknown_main_role(self):
        spec='M码【80-110斤】；黑色双兜✚【30片艾草暖贴】'
        self.assertEqual(self.audit(spec,'护腰黑色M送艾草暖贴30片',title='护腰')['核验状态'],'核对通过')
        self.assertNotEqual(self.audit('未知赠品M码+20片艾草暖贴','护腰M送艾草暖贴20片',title='护腰')['核验状态'],'核对通过')
        pf=v.build_features('护腰护膝套餐',spec)
        self.assertNotIn('component_parse_text',pf)

    def test_weight_multiplication_never_uses_nearest_unrelated_count(self):
        p=v.quantity_structure('【防潮除湿】2袋/包；20袋 （250克*20)大容量')
        self.assertEqual(p['qty'],(20,'袋'));self.assertFalse(p['incomplete'])
        self.assertIsNone(v.quantity_details('除湿袋250克*20')[0])

    def test_nested_totals_are_not_multiplied(self):
        self.assertEqual(v.quantity_details('买3送2【共5盒250只装】更划算')[0],(250,'只'))

    def test_automatic_total_does_not_hide_contradiction(self):
        for text in ['暖贴买20片送10片共40片','眼罩5片*2盒共20片','暖贴共20片合计30片']:
            self.assertTrue(v.quantity_structure(text)['incomplete'])
            self.assertNotEqual(self.audit(text,'暖贴40片')['核验状态'],'核对通过')

    def test_separate_unit_totals_are_not_the_same_as_a_conflicting_total(self):
        self.assertEqual(v.quantity_details('到手9双【共18片】暖足贴')[0],(18,'片'))
        self.assertTrue(v.quantity_structure('共18片合计20片暖足贴')['incomplete'])
        self.assertFalse(v.quantity_structure('买3送1【到手四盒共40片】超值装')['incomplete'])

    def test_mixed_formula_promo_never_suggests_single_formula(self):
        pf=v.build_features('暖贴','买10片送5片;宫暖组合【艾草/益母草】;')
        records=[erp_record('AI','暖贴艾草15片'),erp_record('YI','暖贴益母草15片')]
        by={r['code']:[r] for r in records}
        result=v.audit_current_code('',pf,by,records)
        suggestion=v.suggest_code_candidates(pf,result,records,by)
        self.assertEqual(result['核验状态'],'编码缺失（待补录）')
        self.assertEqual(suggestion['推测候选编码数'],0)


if __name__=='__main__':unittest.main()
