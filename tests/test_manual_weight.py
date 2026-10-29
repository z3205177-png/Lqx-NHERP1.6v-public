import sys
import unittest
from pathlib import Path
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import verify_codes as v
from manual_weight import apply_weight_guard
from simple_report import prepare_rows
from test_matching import erp_record


class ManualWeightTests(unittest.TestCase):
    def test_mixed_weight_units_detect_explicit_conflict(self):
        record=erp_record('A','大蒜1.5KG')
        result=v.audit_current_code('A',v.build_features('大蒜','5斤装'),{'A':[record]},[record])
        self.assertEqual(result['核验状态'],'异常（商品/规格不一致）')
        self.assertIn('净重不一致',result['核验说明'])
        self.assertIsNone(v.quantity_details('5斤装')[0])

    def test_other_statuses_survive_and_the_note_is_visible_in_excel(self):
        pf=v.build_features('大蒜','200g*9袋')
        for state in ['异常（ERP未找到）','编码缺失（待补录）','异常（商品/规格不一致）']:
            result=apply_weight_guard({'核验状态':state,'核验说明':'原有说明'},pf,[])
            self.assertEqual(result['核验状态'],state)
            row={**result,'异常说明':result['核验说明'],'原编码':'0001','候选明细JSON':'[]'}
            self.assertIn('需人工核重',prepare_rows(pd.DataFrame([row]))[1][0]['问题说明'])
        once=apply_weight_guard(result,pf,[])
        self.assertEqual(once,result)

    def test_clothing_body_weight_and_ginger_patches_are_not_produce(self):
        for title,spec in [('护膝','适合100-140斤'),('生姜暖贴','20片'),('硅胶热水袋','重200g')]:
            result=apply_weight_guard({'核验状态':'核对通过'},v.build_features(title,spec),[])
            self.assertEqual(result,{'核验状态':'核对通过'})


if __name__=='__main__':unittest.main()
