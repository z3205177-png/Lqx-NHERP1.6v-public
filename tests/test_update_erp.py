"""update_erp.py 的行为测试。

全部使用临时目录里的迷你项目，不依赖本机绝对路径和真实 ERP 库。
"""
import contextlib
from datetime import date
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

import update_erp as u  # noqa: E402

COMBO_COLS = ['组合装名称', '商家编码', '类别', '重量']
SINGLE_COLS = ['商家编码', '货品名称', '货品编号', '分类']


def write_csv(path, columns, rows, encoding='gbk'):
    pd.DataFrame(rows, columns=columns).to_csv(
        path, index=False, encoding=encoding, lineterminator='\n')


def make_project(tmp, combo_rows, single_rows, version='erp-20260101-v1'):
    """构造一个最小的可用项目：两份 CSV + 登记文件。"""
    root = Path(tmp) / 'proj'
    (root / 'config').mkdir(parents=True)
    (root / 'data').mkdir()
    write_csv(root / 'data/组合装.csv', COMBO_COLS, combo_rows)
    write_csv(root / 'data/单品.csv', SINGLE_COLS, single_rows)
    manifest = {
        'version': version,
        'registered_at': '2026-01-01',
        'erp': {
            'combo': {'path': 'data/组合装.csv',
                      'sha256': u.sha256_of(root / 'data/组合装.csv'),
                      'rows': len(combo_rows)},
            'single': {'path': 'data/单品.csv',
                       'sha256': u.sha256_of(root / 'data/单品.csv'),
                       'rows': len(single_rows)},
        },
    }
    (root / 'config/erp_library.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return root


def run_main(root, combo, single, extra=()):
    manifest = root / 'config/erp_library.json'
    argv = ['update_erp.py', '--combo-erp', str(combo), '--single-erp', str(single),
            '--manifest', str(manifest), *extra]
    with mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
        return u.main()


class TestDiffRecords(unittest.TestCase):
    def records(self, rows):
        df = pd.DataFrame(rows, columns=COMBO_COLS)
        return u.table_records(df, '组合装', '商家编码')

    def test_detects_added_changed_removed(self):
        old = self.records([['A', 'C1', 'x', '1'], ['B', 'C2', 'x', '1']])
        new = self.records([['A', 'C1', 'x', '1'], ['B改', 'C2', 'x', '1'], ['D', 'C3', 'x', '1']])
        stat = u.diff_records(old, new)
        self.assertEqual([code for code, _ in stat['added']], ['C3'])
        self.assertEqual([code for code, *_ in stat['changed']], ['C2'])
        self.assertEqual(stat['removed'], [])

    def test_identical_content_reports_no_change(self):
        old = self.records([['A', 'C1', 'x', '1']])
        new = self.records([['A', 'C1', 'x', '1']])
        stat = u.diff_records(old, new)
        self.assertEqual((stat['added'], stat['changed'], stat['removed']), ([], [], []))

    def test_same_code_multiple_rows_kept(self):
        old = self.records([['A', 'C1', 'x', '1']])
        new = self.records([['A', 'C1', 'x', '1'], ['A2', 'C1', 'y', '2']])
        stat = u.diff_records(old, new)
        self.assertEqual(len(stat['changed']), 1)
        self.assertEqual(stat['changed'][0][0], 'C1')

    def test_diff_is_byte_order_insensitive(self):
        # 列顺序不同、内容相同：指纹按 sort_keys 计算，应判为无变化
        df_a = pd.DataFrame([['A', 'C1', 'x', '1']], columns=COMBO_COLS)
        df_b = df_a[['商家编码', '组合装名称', '重量', '类别']]
        old = u.table_records(df_a, '组合装', '商家编码')
        new = u.table_records(df_b, '组合装', '商家编码')
        self.assertEqual(u.diff_records(old, new), {'added': [], 'removed': [], 'changed': []})


class TestNextVersion(unittest.TestCase):
    def setUp(self):
        # Fixed clock makes the tests independent of the execution date.
        patcher = mock.patch.object(u, 'date')
        clock = patcher.start()
        clock.today.return_value = date(2026, 10, 30)
        self.addCleanup(patcher.stop)

    def test_same_day_v1_with_empty_history_goes_v2(self):
        self.assertEqual(u.next_version({'version': 'erp-20261030-v1', 'updates': []}),
                         'erp-20261030-v2')

    def test_non_contiguous_history_takes_max_plus_one(self):
        manifest = {'version': 'erp-20261030-v3', 'updates': [{'version': 'erp-20261030-v1'}]}
        self.assertEqual(u.next_version(manifest), 'erp-20261030-v4')

    def test_other_day_starts_at_v1(self):
        manifest = {'version': 'erp-20200101-v9', 'updates': [{'version': 'erp-20200101-v9'}]}
        self.assertTrue(u.next_version(manifest).endswith('-v1'))


class TestHeaderGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.combo = [['A', 'C1', 'x', '1']]
        self.single = [['S1', '单品一', 'p1', '类']]
        self.root = make_project(self.tmp.name, self.combo, self.single)

    def test_column_set_change_aborts(self):
        bad = Path(self.tmp.name) / 'bad_combo.csv'
        write_csv(bad, COMBO_COLS + ['备注'], [['A', 'C1', 'x', '1', 'n']])
        code = run_main(self.root, bad, self.root / 'data/单品.csv')
        self.assertEqual(code, 2)

    def test_name_column_rename_aborts(self):
        # 核验引擎按固定列名读 ERP，改名后工具不能放行
        renamed = Path(self.tmp.name) / 'renamed_combo.csv'
        write_csv(renamed, ['商品名称', '商家编码', '类别', '重量'], [['A', 'C1', 'x', '1']])
        code = run_main(self.root, renamed, self.root / 'data/单品.csv')
        self.assertEqual(code, 2)

    def test_column_order_change_does_not_abort(self):
        reordered = Path(self.tmp.name) / 'ordered_combo.csv'
        write_csv(reordered, ['商家编码', '组合装名称', '重量', '类别'], [['C1', 'A', '1', 'x']])
        code = run_main(self.root, reordered, self.root / 'data/单品.csv')
        self.assertEqual(code, 0)


class TestGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = make_project(self.tmp.name, [['A', 'C1', 'x', '1']], [['S1', '单品一', 'p1', '类']])

    def test_gbk_unencodable_aborts_before_any_write(self):
        bad_single = Path(self.tmp.name) / 'emoji_single.csv'
        write_csv(bad_single, SINGLE_COLS, [['S1', '单品一🎁', 'p1', '类']], encoding='utf-8-sig')
        before = u.sha256_of(self.root / 'data/组合装.csv')
        with self.assertRaises(SystemExit):
            run_main(self.root, self.root / 'data/组合装.csv', bad_single, extra=['--apply'])
        self.assertEqual(u.sha256_of(self.root / 'data/组合装.csv'), before)
        self.assertFalse((self.root / 'data/erp_versions').exists())

    def test_baseline_hash_mismatch_aborts(self):
        target = self.root / 'data/组合装.csv'
        target.write_bytes(target.read_bytes() + b'\n')
        with self.assertRaises(SystemExit):
            run_main(self.root, self.root / 'data/组合装.csv', self.root / 'data/单品.csv')


class TestImpact(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = make_project(self.tmp.name, [['A', 'C1', 'x', '1']], [['S1', '单品一', 'p1', '类']])
        self.df = pd.read_csv(self.root / 'data/组合装.csv', encoding='gbk',
                              dtype=str, keep_default_na=False)
        self.records = u.table_records(self.df, '组合装', '商家编码')
        fp = self.records[0]['fp']
        (self.root / 'config/sku_audit_reviews.json').write_text(json.dumps({
            'version': 1,
            'reviews': {'k': {'context': {'平台': '天猫', 'SKU ID': '9'},
                              'mode': 'confirmed', 'source_code': 'C1',
                              'target_code': 'C1', 'erp_bindings': {'C1': [fp]},
                              'basis': 'test', 'reviewed_by': 'test',
                              'content_fingerprint': 'x'}}},
            ensure_ascii=False), encoding='utf-8')

    def test_unchanged_record_has_no_impact(self):
        newly, pre = u.evaluate_impact({'组合装': self.records}, {'组合装': self.records}, self.root)
        self.assertEqual((newly, pre), ([], []))

    def test_changed_record_reported_as_newly_broken(self):
        modified = pd.DataFrame([['A改', 'C1', 'x', '1']], columns=COMBO_COLS)
        after = u.table_records(modified, '组合装', '商家编码')
        newly, pre = u.evaluate_impact({'组合装': self.records}, {'组合装': after}, self.root)
        self.assertEqual(len(newly), 1)
        self.assertEqual(newly[0]['kind'], 'SKU复核')
        self.assertEqual(pre, [])

    def test_deleted_record_reported(self):
        after = u.table_records(pd.DataFrame([], columns=COMBO_COLS), '组合装', '商家编码')
        newly, _ = u.evaluate_impact({'组合装': self.records}, {'组合装': after}, self.root)
        self.assertEqual(len(newly), 1)
        self.assertIn('已不存在', newly[0]['reason'])

    def test_preexisting_breakage_not_counted_as_new(self):
        empty = u.table_records(pd.DataFrame([], columns=COMBO_COLS), '组合装', '商家编码')
        newly, pre = u.evaluate_impact({'组合装': empty}, {'组合装': empty}, self.root)
        self.assertEqual(newly, [])
        self.assertEqual(len(pre), 1)

    def write_mapping(self, fingerprint):
        (self.root / 'config/confirmed_mappings.json').write_text(json.dumps({
            'mappings': {'k': {'platform_fingerprint': 'p', 'erp_code': 'C1',
                               'accepted_erp_records': {'C1': fingerprint},
                               'confirmed_by': 'test', 'basis': 'test'}}},
            ensure_ascii=False), encoding='utf-8')

    def test_string_fingerprint_is_not_a_false_alarm(self):
        """accepted_erp_records 的值是字符串；被 sorted() 拆成字符会恒定误报。"""
        self.write_mapping(self.records[0]['fp'])
        newly, pre = u.evaluate_impact({'组合装': self.records}, {'组合装': self.records}, self.root)
        self.assertEqual((newly, pre), ([], []))

    def test_string_fingerprint_still_detects_real_change(self):
        self.write_mapping(self.records[0]['fp'])
        modified = pd.DataFrame([['A改', 'C1', 'x', '1']], columns=COMBO_COLS)
        after = u.table_records(modified, '组合装', '商家编码')
        newly, _ = u.evaluate_impact({'组合装': self.records}, {'组合装': after}, self.root)
        self.assertIn('人工映射', {item['kind'] for item in newly})


class TestAtomicWrite(unittest.TestCase):
    def test_partial_manifest_staging_failure_cleans_every_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_project(tmp, [['A', 'C1', 'x', '1']], [['S1', '单品一', 'p1', '类']])
            protected = [root / 'data/组合装.csv', root / 'data/单品.csv', root / 'config/erp_library.json']
            originals = {p: p.read_bytes() for p in protected}
            real_write = Path.write_text

            def interrupted_write(path, *args, **kwargs):
                if path.name == 'erp_library.json.staged':
                    path.write_bytes(b'{"partial":')
                    raise OSError('模拟登记暂存写入中断')
                return real_write(path, *args, **kwargs)

            with mock.patch.object(Path, 'write_text', interrupted_write):
                with self.assertRaises(OSError):
                    run_main(root, root / 'data/组合装.csv', root / 'data/单品.csv', extra=['--apply'])
            self.assertTrue(all(p.read_bytes() == content for p, content in originals.items()))
            self.assertEqual(list(root.rglob('*.staged')), [])
            self.assertEqual(list(root.rglob('*.bak')), [])

    def test_swap_rolls_back_when_second_replace_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / 'a.csv'
            second = Path(tmp) / 'b.csv'
            first.write_bytes(b'old_a')
            second.write_bytes(b'old_b')
            df = pd.DataFrame([['A', 'C1', 'x', '1']], columns=COMBO_COLS)
            real_replace = u.os.replace
            calls = {'n': 0}

            def flaky(src, dst):
                calls['n'] += 1
                if calls['n'] == 2:
                    raise OSError('模拟第二个文件替换失败')
                return real_replace(src, dst)

            with mock.patch.object(u.os, 'replace', side_effect=flaky):
                with self.assertRaises(OSError):
                    u.stage_and_swap([(df, first), (df, second)])
            self.assertEqual(first.read_bytes(), b'old_a')
            self.assertEqual(second.read_bytes(), b'old_b')
            self.assertEqual(list(Path(tmp).glob('*.staged')), [])
            self.assertEqual(list(Path(tmp).glob('*.bak')), [])

    def test_manifest_failure_rolls_back_both_csvs(self):
        """登记文件与两份 CSV 必须同一事务：登记写失败时 CSV 也要回退。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_project(tmp, [['A', 'C1', 'x', '1']], [['S1', '单品一', 'p1', '类']])
            new_combo = Path(tmp) / 'new_combo.csv'
            write_csv(new_combo, COMBO_COLS, [['A', 'C1', 'x', '1'], ['B', 'C2', 'y', '2']])
            before = {name: u.sha256_of(root / 'data' / name)
                      for name in ('组合装.csv', '单品.csv')}

            real_replace = u.os.replace
            calls = {'n': 0}

            def flaky(src, dst):
                calls['n'] += 1
                if calls['n'] == 3:      # 第三份是登记文件
                    raise OSError('模拟登记写入失败')
                return real_replace(src, dst)

            with mock.patch.object(u.os, 'replace', side_effect=flaky):
                with self.assertRaises(OSError):
                    run_main(root, new_combo, root / 'data/单品.csv', extra=['--apply'])

            for name, digest in before.items():
                self.assertEqual(u.sha256_of(root / 'data' / name), digest, f'{name} 未回滚')
            manifest = json.loads((root / 'config/erp_library.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['version'], 'erp-20260101-v1')
            self.assertEqual(manifest['erp']['combo']['rows'], 1)
            leftovers = (list((root / 'data').glob('*.staged'))
                         + list((root / 'config').glob('*.staged')))
            self.assertEqual(leftovers, [])

    def test_rollback_failure_keeps_backups(self):
        """回滚本身失败时必须保留 .bak，否则已换新的文件再也恢复不回来。"""
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / 'a.csv'
            second = Path(tmp) / 'b.csv'
            first.write_bytes(b'old_a')
            second.write_bytes(b'old_b')
            staged_first = Path(tmp) / 'a.csv.staged'
            staged_second = Path(tmp) / 'b.csv.staged'
            staged_first.write_bytes(b'new_a')
            staged_second.write_bytes(b'new_b')

            real_copy = u.shutil.copy2
            real_replace = u.os.replace
            state = {'replace': 0, 'copy': 0}

            def flaky_replace(src, dst):
                state['replace'] += 1
                if state['replace'] == 2:
                    raise OSError('模拟替换失败')
                return real_replace(src, dst)

            def flaky_copy(src, dst):
                state['copy'] += 1
                if state['copy'] == 3:      # 前两次是备份，第三次是第一次恢复
                    raise OSError('模拟恢复失败')
                return real_copy(src, dst)

            with mock.patch.object(u.os, 'replace', side_effect=flaky_replace), \
                    mock.patch.object(u.shutil, 'copy2', side_effect=flaky_copy):
                with self.assertRaises(OSError):
                    u.commit([(staged_first, first), (staged_second, second)])

            self.assertTrue((Path(tmp) / 'a.csv.bak').exists(), '恢复失败时备份必须保留')
            self.assertTrue((Path(tmp) / 'b.csv.bak').exists(), '恢复失败时备份必须保留')

    def test_stage_failure_cleans_temp_files(self):
        """暂存阶段失败时不能留下 .staged 半成品，原库也不能变。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_project(tmp, [['A', 'C1', 'x', '1']], [['S1', '单品一', 'p1', '类']])
            new_combo = Path(tmp) / 'new_combo.csv'
            write_csv(new_combo, COMBO_COLS, [['A', 'C1', 'x', '1'], ['B', 'C2', 'y', '2']])
            before = u.sha256_of(root / 'data/组合装.csv')

            real_stage = u.stage_csv
            state = {'n': 0}

            def flaky_stage(df, target):
                state['n'] += 1
                if state['n'] == 2:      # 第二份（单品）暂存失败
                    raise OSError('模拟暂存失败')
                return real_stage(df, target)

            with mock.patch.object(u, 'stage_csv', side_effect=flaky_stage):
                with self.assertRaises(OSError):
                    run_main(root, new_combo, root / 'data/单品.csv', extra=['--apply'])

            leftovers = (list((root / 'data').glob('*.staged'))
                         + list((root / 'config').glob('*.staged')))
            self.assertEqual(leftovers, [], '暂存失败后不应残留临时文件')
            self.assertEqual(u.sha256_of(root / 'data/组合装.csv'), before)


class TestArchiveAndInstall(unittest.TestCase):
    def test_apply_archives_backs_up_and_updates_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_project(tmp, [['A', 'C1', 'x', '1']], [['S1', '单品一', 'p1', '类']])
            new_combo = Path(tmp) / 'new_combo.csv'
            write_csv(new_combo, COMBO_COLS, [['A', 'C1', 'x', '1'], ['B', 'C2', 'y', '2']])
            code = run_main(root, new_combo, root / 'data/单品.csv', extra=['--apply'])
            self.assertEqual(code, 0)

            manifest = json.loads((root / 'config/erp_library.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['erp']['combo']['rows'], 2)
            self.assertEqual(u.sha256_of(root / 'data/组合装.csv'),
                             manifest['erp']['combo']['sha256'])
            self.assertEqual(len(manifest['updates']), 1)
            self.assertEqual(manifest['updates'][0]['added_codes'], 1)

            archived = root / 'data/erp_versions' / 'erp-20260101-v1'
            self.assertTrue((archived / '组合装.csv').is_file())
            self.assertTrue((root / 'config/erp_library.backup-erp-20260101-v1.json').is_file())


class TestCompareStatus(unittest.TestCase):
    def row(self, sku='1', status='通过', code='C1', guess='', spec='10片'):
        return {'平台': '天猫', '商品ID': 'P1', 'SKU_ID': sku, '名称': 'n', '规格': spec,
                '原编码': code, '状态': status, '推测': guess}

    def test_status_change_detected(self):
        changes = u.compare_status([self.row()], [self.row(status='规格不一致')])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['field'], '状态')

    def test_code_change_detected_even_if_status_same(self):
        changes = u.compare_status([self.row()], [self.row(code='C2')])
        self.assertEqual([c['field'] for c in changes], ['原编码'])

    def test_guess_change_detected(self):
        changes = u.compare_status([self.row()], [self.row(guess='C9')])
        self.assertEqual([c['field'] for c in changes], ['推测'])

    def test_row_count_change_detected(self):
        changes = u.compare_status([self.row()], [self.row(), self.row(spec='20片')])
        self.assertEqual([c['field'] for c in changes], ['行数'])

    def test_duplicate_ids_do_not_overwrite(self):
        before = [self.row(status='通过'), self.row(status='待确认')]
        after = [self.row(status='规格不一致'), self.row(status='待确认')]
        changes = u.compare_status(before, after)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['old'], '通过')


class TestReadCsv(unittest.TestCase):
    def test_reads_gbk_utf8_and_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            for encoding in ('gbk', 'utf-8', 'utf-8-sig'):
                path = Path(tmp) / f'{encoding}.csv'
                write_csv(path, SINGLE_COLS, [['S1', '单品一', 'p1', '类']], encoding=encoding)
                df, used = u.read_csv_any(path)
                self.assertEqual(len(df), 1, f'{encoding} 读取失败')
                self.assertEqual(df.iloc[0]['货品名称'], '单品一')


if __name__ == '__main__':
    unittest.main()
