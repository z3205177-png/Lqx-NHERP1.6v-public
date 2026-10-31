import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import verify_codes as v
from test_matching import erp_record

TITLE='暖火暖手宝贴穿戴式暖宝宝儿童学生蒸汽热敷暖手部便携冬季暖贴'
SPEC='穿戴式【草本暖手】工作学习手不凉,买30送10【到手40片】更划算'


class CrossCategoryGuardTests(unittest.TestCase):
    def audit(self,spec=SPEC,title=TITLE,name='1000ml热水袋兔毛贴布粉兔子',extra=(),confirmation=None):
        record=erp_record('WATER',name);records=[record,*extra]
        pf=v.build_features(title,spec);pf['confirmation']=confirmation
        index={}
        for e in records:index.setdefault(e['code'],[]).append(e)
        return v.audit_current_code('WATER',pf,index,records)

    def test_reported_40_piece_to_water_bottle_injection_is_blocked(self):
        self.assertEqual(v.build_features(TITLE,SPEC)['families'],set())
        result=self.audit()
        self.assertEqual(result['核验状态'],'待人工确认')
        self.assertIn('跨品类',result['核验说明'])
        self.assertIn('40片',result['核验说明'])
        self.assertIn('1000ml热水袋',result['核验说明'])
        self.assertEqual(result['应改为编码'],'')

    def test_original_thermal_product_and_seo_title_remain_unchanged(self):
        for title in [TITLE,TITLE+' 热水袋保暖用品']:
            result=self.audit(title=title,name='暖火暖手宝40片袋装')
            self.assertEqual(result['核验状态'],'核对通过')
            self.assertNotIn('跨品类疑点JSON',result)

    def test_existing_quantity_conflict_is_preserved(self):
        result=self.audit(name='暖火暖手宝10片袋装')
        self.assertNotEqual(result['核验状态'],'核对通过')
        self.assertIn('数量',result['核验说明'])
        self.assertNotIn('跨品类疑点JSON',result)

    def test_real_water_bottle_and_unknown_description_are_not_broadly_blocked(self):
        for title,spec in [('热水袋','1000ml热水袋兔毛贴布粉兔子'),('保暖用品','超值装'),(TITLE,'穿戴式草本暖手')]:
            result=self.audit(title=title,spec=spec)
            self.assertEqual(result['核验状态'],'核对通过')
            self.assertNotIn('跨品类疑点JSON',result)

    def test_explicit_bundle_does_not_use_single_item_gate(self):
        for spec,name in [(SPEC+'+1000ml热水袋','1000ml热水袋送暖手贴40片'),
                          (SPEC+'搭配布套','1000ml热水袋兔毛贴布粉兔子')]:
            result=self.audit(spec=spec,name=name)
            self.assertNotIn('跨品类疑点JSON',result)

    def test_erp_without_capacity_and_duplicate_conflicting_records_keep_existing_rules(self):
        result=self.audit(name='热水袋粉色')
        self.assertEqual(result['核验状态'],'核对通过')
        self.assertNotIn('跨品类疑点JSON',result)
        result=self.audit(extra=[erp_record('WATER','暖火暖手宝40片袋装')])
        self.assertEqual(result['核验状态'],'待人工确认')
        self.assertIn('ERP同一编码',result['匹配依据'])
        self.assertNotIn('跨品类疑点JSON',result)

    def test_verified_explicit_confirmation_is_not_replaced(self):
        result=self.audit(confirmation={'record':{'code':'WATER'},'confirmed_by':'已确认','basis':'已核实该SKU关系'})
        self.assertEqual(result['核验状态'],'核对通过')
        self.assertNotIn('跨品类疑点JSON',result)

    def test_all_equivalent_erp_sources_are_retained_in_evidence(self):
        result=self.audit(extra=[erp_record('WATER','1000ml热水袋兔毛贴布粉兔子',source='单品')])
        self.assertEqual(result['核验状态'],'待人工确认')
        evidence=json.loads(result['跨品类疑点JSON'])['erp']
        self.assertEqual(len(evidence),2)
        self.assertEqual({x['source'] for x in evidence},{'单品','组合装'})

    def test_valid_sku_confirmation_remains_authoritative_in_pipeline(self):
        import pandas as pd
        record=erp_record('WATER','1000ml热水袋兔毛贴布粉兔子')
        record['erp_fingerprint']='ERP-EXACT'
        context={'平台':'快手','商品 ID':'001','SKU ID':'002','商品标题':TITLE,'SKU':SPEC,
                 'ERP货品编号':'','ERP规格编码':'','独立规格数量':''}
        entry={'context':context,'content_fingerprint':v.sku_reviews.content_fingerprint(context),
               'source_code':'WATER','target_code':'WATER','erp_bindings':{'WATER':['ERP-EXACT']},
               'mode':'confirmed','reviewed_by':'业务确认','basis':'仅此未变SKU和ERP记录的明确确认'}
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'快手.csv'
            pd.DataFrame([{'商品ID':'001','skuID':'002','商品标题':TITLE,'sku名称':SPEC,'sku编码':'WATER'}]).to_csv(p,index=False,encoding='utf-8-sig')
            result,_=v.verify_platform_file(str(p),[record],{'WATER':[record]},platform_override='快手',
                confirmed_entries={},review_entries={v.sku_reviews.review_key(context):entry})
            self.assertEqual(result.iloc[0]['核验状态'],'核对通过')
            self.assertEqual(result.iloc[0]['人工确认依据'],entry['basis'])
            self.assertEqual(result.iloc[0]['原编码'],'WATER')

    def test_default_pipeline_preserves_code_and_does_not_suggest_replacement(self):
        import pandas as pd
        from simple_report import prepare_rows
        record=erp_record('WATER','1000ml热水袋兔毛贴布粉兔子')
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'快手注入.csv'
            pd.DataFrame([{'商品ID':'001','skuID':'002','商品标题':TITLE,'sku名称':SPEC,'sku编码':'WATER'}]).to_csv(p,index=False,encoding='utf-8-sig')
            original=p.read_bytes()
            result,_=v.verify_platform_file(str(p),[record],{'WATER':[record]},platform_override='快手',confirmed_entries={},review_entries={})
            row=result.iloc[0]
            self.assertEqual(row['原编码'],'WATER')
            self.assertEqual(row['核验状态'],'待人工确认')
            self.assertEqual(row['推测商家编码'],'')
            self.assertEqual(row['候选明细JSON'],'[]')
            proof=json.loads(row['跨品类疑点JSON'])
            self.assertEqual(proof['platform_quantity'],[40,'片'])
            self.assertEqual(proof['erp'][0]['name'],record['name'])
            pending,rows=prepare_rows(result)
            self.assertEqual(len(pending),1);self.assertEqual(len(rows[0]),12)
            self.assertIn('跨品类',rows[0]['问题说明'])
            self.assertEqual(p.read_bytes(),original)


if __name__=='__main__':unittest.main()
