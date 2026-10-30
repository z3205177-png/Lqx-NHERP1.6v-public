import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import regress_all as r


def row(**changes):
    return {**dict(zip(r.STATUS_COLUMNS,['天猫','P','S','title','30片','A','通过','','','','',''])),
            '_full_evidence':True,'_candidates':[],**changes}


class CompareTests(unittest.TestCase):
    def test_short_and_long_states(self):
        for a,b in [('异常（商品/规格不一致）','规格不一致'),('编码缺失（待补录）','编码为空'),('异常（ERP未找到）','ERP未找到')]:
            self.assertEqual(r.normalize_status(a),r.normalize_status(b))
        self.assertEqual(r.normalize_status(None),'')

    def test_same_rows_no_change_and_duplicate_rows_preserved(self):
        self.assertEqual(r.compare_with_baseline([row(),row()],[row(),row()]),[])
        self.assertEqual(len(r.compare_with_baseline([row(),row(状态='待确认')],[row(),row()])),1)

    def test_raw_code_target_spec_and_title_are_compared(self):
        for field in ['原编码','推测','规格','名称','c1']:
            with self.subTest(field=field):
                changes=r.compare_with_baseline([row(**{field:'changed'})],[row()])
                self.assertEqual(changes[0]['field'],field)
                self.assertEqual(changes[0]['sku_id'],'S')

    def test_full_candidates_include_beyond_visible_three(self):
        old=row(_candidates=[('A','甲','单品','1'),('B','乙','单品','2'),('C','丙','单品','3'),('D','丁','单品','4')])
        new=copy.deepcopy(old);new['_candidates'][-1]=('E','戊','单品','5')
        self.assertEqual(r.compare_with_baseline([new],[old]),[])
        self.assertEqual(r.compare_with_baseline([new],[old],True)[0]['field'],'_candidates')

    def test_added_removed_rows_and_cross_platform_ids(self):
        self.assertEqual(r.compare_with_baseline([row(),row()],[row()])[0]['field'],'行数')
        self.assertEqual(len(r.compare_with_baseline([row(平台='京东')],[row()])),2)

    def test_reordered_rows_are_reported(self):
        first,second=row(),row(SKU_ID='S2')
        self.assertEqual(r.compare_with_baseline([second,first],[first,second])[0]['field'],'行序')


class RunnerTests(unittest.TestCase):
    def run_case(self,current=None,prior=None,missing=False,base_missing=False,baseline=True,options=()):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=root/'config.json';source=root/'source.csv';source.write_text('原编码',encoding='utf-8')
            config.write_text(json.dumps({'platforms':[{'name':'天猫','platform':'天猫','store':'测试','files':['source.csv']}]}),encoding='utf-8')
            base=root/'baseline';base.mkdir()
            if not base_missing:(base/'天猫.xlsx').write_bytes(b'fixture')
            argv=['--config',str(config),'--output',str(root/'output'),*options]
            if baseline:argv+=['--baseline',str(base)]
            def load(path):
                value=prior if Path(path).parent.name=='baseline' else current
                if isinstance(value,Exception):raise value
                return value
            with patch.object(r,'run_platform',return_value=(None,'缺少样本') if missing else (root/'current.xlsx','')) as call,patch.object(r,'load_status',side_effect=load),contextlib.redirect_stdout(io.StringIO()):
                code=r.main(argv)
            data=json.loads((root/'output/回归报告.json').read_text(encoding='utf-8'))
            self.assertEqual(source.read_text(encoding='utf-8'),'原编码')
            self.assertEqual(call.call_args.args[0]['files'],[str(source.resolve())])
            return code,data

    def test_identical_full_baseline_succeeds(self):
        code,data=self.run_case([row()],[row()])
        self.assertEqual(code,0);self.assertEqual(data['total_changes'],0);self.assertTrue(data['comparison_complete'])

    def test_change_fail_mode_and_report_mode(self):
        code,data=self.run_case([row(状态='待确认')],[row()],options=['--fail-on-change'])
        self.assertEqual(code,1);self.assertEqual(data['total_changes'],1)
        self.assertEqual(self.run_case([row(状态='待确认')],[row()])[0],0)

    def test_unknown_status_is_nonzero_and_not_silent(self):
        code,data=self.run_case([row(状态='未识别')],[row()])
        self.assertEqual(code,2);self.assertFalse(data['status_valid']);self.assertEqual(data['unknown_statuses'],{'未识别':1})
        self.assertIsNone(data['total_changes']);self.assertFalse(data['comparison_complete'])

    def test_invalid_baseline_is_incomplete(self):
        code,data=self.run_case([row()],[row(状态='未识别')])
        self.assertEqual(code,2);self.assertIsNone(data['total_changes'])

    def test_missing_sample_is_incomplete(self):
        code,data=self.run_case(missing=True)
        self.assertEqual(code,2);self.assertFalse(data['coverage_complete']);self.assertIsNone(data['total_changes'])

    def test_missing_baseline_is_not_zero_changes(self):
        code,data=self.run_case([row()],base_missing=True)
        self.assertEqual(code,2);self.assertFalse(data['comparison_complete']);self.assertIsNone(data['total_changes'])

    def test_no_baseline_is_explicitly_uncompared(self):
        code,data=self.run_case([row()],baseline=False)
        self.assertEqual(code,0);self.assertIsNone(data['total_changes']);self.assertFalse(data['comparison_complete'])

    def test_full_comparison_requires_evidence(self):
        code,data=self.run_case([row(_full_evidence=False)],[row()])
        self.assertEqual(code,2);self.assertFalse(data['comparison_complete'])
        self.assertEqual(self.run_case([row(_full_evidence=False)],[row()],options=['--comparison-scope','report'])[0],0)

    def test_corrupt_report_is_failure(self):
        code,data=self.run_case(ValueError('bad report'),[row()])
        self.assertEqual(code,2)

    def test_empty_output_is_not_complete(self):
        code,data=self.run_case([],[])
        self.assertEqual(code,2);self.assertFalse(data['coverage_complete'])

    def test_preprocess_cannot_mutate_or_blank_existing_code(self):
        with tempfile.TemporaryDirectory() as temp:
            f=Path(temp)/'source.csv';f.write_text('商家编码,货号,条形码\nCONFIRMED,,6927846504292',encoding='utf-8')
            original=f.read_bytes()
            result,error=r.run_platform({'name':'唯品会','files':[str(f)],'preprocess':'vip_code_column'},Path(temp),sys.executable)
            self.assertIsNone(result);self.assertIn('编码',error);self.assertEqual(f.read_bytes(),original)

    def test_bad_selection_and_duplicate_names_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'c.json';p.write_text(json.dumps({'platforms':[{'name':'A'},{'name':'A'}]}),encoding='utf-8')
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):r.main(['--config',str(p)])

    def test_output_cannot_overwrite_source(self):
        with tempfile.TemporaryDirectory() as temp:
            f=Path(temp)/'天猫.xlsx';f.write_bytes(b'original')
            result,error=r.run_platform({'name':'天猫','files':[str(f)]},Path(temp),sys.executable)
            self.assertIsNone(result);self.assertIn('覆盖',error);self.assertEqual(f.read_bytes(),b'original')

    def test_native_cli_accepts_multiple_files_and_repeated_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);files=[]
            for i in range(2):
                path=root/f'input{i}.csv'
                path.write_text(f'商品ID,skuID,商品标题,sku名称,sku编码\n00{i},SKU{i},艾草暖贴,艾草暖贴30片,NHCP02601\n',encoding='utf-8-sig')
                files.append(path)
            before=[p.read_bytes() for p in files]
            output,error=r.run_platform({'name':'双文件','platform':'快手','store':'测试','sheet':'Sheet1',
                                         'files':[str(p) for p in files]},root,sys.executable)
            self.assertEqual(error,'');self.assertIsNotNone(output)
            rows=r.load_status(output)
            self.assertEqual(len(rows),2);self.assertEqual([r['商品ID'] for r in rows],['000','001'])
            self.assertEqual(before,[p.read_bytes() for p in files])

    def test_selective_scope_remains_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=root/'c.json'
            config.write_text(json.dumps({'platforms':[{'name':n,'platform':'天猫','store':'测试','files':[]} for n in ['A','B']]}),encoding='utf-8')
            with patch.object(r,'run_platform',return_value=(root/'A.xlsx','')),patch.object(r,'load_status',return_value=[row()]),contextlib.redirect_stdout(io.StringIO()):
                code=r.main(['--config',str(config),'--output',str(root/'out'),'--only','A'])
            report=json.loads((root/'out/回归报告.json').read_text(encoding='utf-8'))
            self.assertEqual(code,0);self.assertEqual(report['configured_samples'],2)
            self.assertEqual(report['selected_samples'],1);self.assertFalse(report['selection_is_full'])


class ReportReaderTests(unittest.TestCase):
    def test_native_report_and_sidecar_are_checked(self):
        import pandas as pd
        from simple_report import write_simple_report
        from openpyxl import load_workbook
        original={'平台':'天猫','商品 ID':'001','SKU ID':'002','商品标题':'标题','SKU':'30片',
                  '原编码':'000A','核验状态':'异常（ERP未找到）','推测商家编码':'NEW',
                  '候选明细JSON':json.dumps([{'code':'NEW','name':'名称','source':'单品','source_row':12}])}
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'test.xlsx';write_simple_report(p,pd.DataFrame([original]))
            records=r.load_status(p);self.assertFalse(records[0]['_full_evidence'])
            evidence=p.parent/'核验依据';evidence.mkdir();sidecar=evidence/'test.json'
            sidecar.write_text(json.dumps({'results':[original]}),encoding='utf-8')
            records=r.load_status(p)
            self.assertTrue(records[0]['_full_evidence']);self.assertEqual(records[0]['商品ID'],'001')
            self.assertEqual(records[0]['_candidates'],[('NEW','名称','单品','12')])
            altered={**original,'原编码':'STALE'}
            sidecar.write_text(json.dumps({'results':[altered]}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'原编码'):r.load_status(p)
            sidecar.unlink()
            book=load_workbook(p);book['全部结果']['A4']='错误表头';book.save(p);book.close()
            with self.assertRaisesRegex(ValueError,'表头'):r.load_status(p)
            blank_id={**original,'SKU ID':''}
            write_simple_report(p,pd.DataFrame([blank_id]))
            sidecar.write_text(json.dumps({'results':[blank_id]}),encoding='utf-8')
            records=r.load_status(p)
            self.assertEqual(len(records),1);self.assertTrue(records[0]['_full_evidence'])


class ArchiveAuditTests(unittest.TestCase):
    def test_original_basis_and_audit_scope(self):
        data=json.loads((ROOT/'config/retired_sku_audit_reviews.json').read_text(encoding='utf-8'))
        self.assertEqual(len(data['reviews']),31)
        from collections import Counter
        self.assertEqual(Counter(e['retirement']['reason_code'] for e in data['reviews'].values()),
                         {'same_item_piece_gift':16,'existing_rules_reproduce':14,'knee_part_alias':1})
        for e in data['reviews'].values():
            self.assertTrue(e['basis']);self.assertTrue(e['retirement']['superseded_by'])
            self.assertEqual(e['retirement']['rule_version'],'faf86414c84e2028e224247bb489df64ea19a5f1')
            self.assertNotEqual(e['retirement']['rule_version'],e['retirement']['evaluation_base'])


if __name__=='__main__':unittest.main()
