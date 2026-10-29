import sys
import unittest
import tempfile
from pathlib import Path
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import verify_codes as v
from test_matching import erp_record


class VerifiedPlatformProfiles(unittest.TestCase):
    def setUp(self):v.load_alias_config()

    def test_verified_export_headers_select_sku_fields(self):
        cases={
            '京东':['商品编码','商品名称','SKUID','销售属性','商家SKU'],
            '抖音':['商品ID','商品名称','规格ID（SKUID）','商品规格','商家SKU编码'],
            '唯品会':['V_SPU','V_SKU','商品名称','自定义尺码','自定义颜色','商家编码','条形码','货号'],
            '小红书':['itemId','商品标题','规格id','规格值','商家编码']}
        for platform,cols in cases.items():
            with self.subTest(platform=platform):
                selected=v.choose_platform_columns(pd.DataFrame(columns=cols),platform)
                self.assertEqual(selected['sku_name'],v.PLATFORM_PROFILES[platform]['columns']['sku_name'])
                self.assertNotEqual(selected['sku_name'],selected['title'])
                self.assertNotEqual(selected['code'],selected['product_id'])

    def test_jd_does_not_require_a_fixed_sheet_name(self):
        self.assertNotIn('sheet',v.PLATFORM_PROFILES['京东'])
        self.assertEqual(v.PLATFORM_PROFILES['京东']['columns']['sku_name'],'销售属性')

    def test_vip_sku_keeps_both_selected_attributes(self):
        self.assertEqual(v.PLATFORM_PROFILES['唯品会']['sku_name_columns'],['自定义尺码','自定义颜色'])
        self.assertEqual(v.PLATFORM_PROFILES['唯品会']['columns']['code'],'商家编码')

    def test_unconfirmed_vip_barcode_is_not_silently_used_as_code(self):
        with self.assertRaisesRegex(RuntimeError,'配置字段不存在'):
            v.choose_platform_columns(pd.DataFrame(columns=['V_SPU','V_SKU','商品名称','自定义尺码','条形码','货号']), '唯品会')

    def test_vip_composite_attributes_reach_the_real_audit_pipeline(self):
        record=erp_record('A','玫瑰蒸汽眼罩25片')
        data={'V_SPU':'001','V_SKU':'0002','商品名称':'蒸汽眼罩','自定义尺码':'均码',
              '自定义颜色':'玫瑰蒸汽眼罩5片袋装*5','商家编码':'A'}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'唯品会.csv'
            pd.DataFrame([data]).to_csv(path,index=False,encoding='utf-8-sig')
            results,meta=v.verify_platform_file(str(path),[record],{'A':[record]},
                platform_override='唯品会',confirmed_entries={},review_entries={})
            self.assertEqual(results.iloc[0]['核验状态'],'核对通过')
            self.assertEqual(results.iloc[0]['SKU'],'均码；玫瑰蒸汽眼罩5片袋装*5')
            self.assertEqual(meta['_quantity_details'][0]['platform']['qty'],(25,'片'))
            self.assertEqual(meta['_quantity_details'][0]['erp'][0]['quantity']['qty'],(25,'片'))
            pd.DataFrame([{k:x for k,x in data.items() if k!='自定义颜色'}]).to_csv(path,index=False,encoding='utf-8-sig')
            with self.assertRaisesRegex(RuntimeError,'SKU属性列缺失'):
                v.verify_platform_file(str(path),[record],{'A':[record]},platform_override='唯品会',
                    confirmed_entries={},review_entries={})


if __name__=='__main__':unittest.main()
