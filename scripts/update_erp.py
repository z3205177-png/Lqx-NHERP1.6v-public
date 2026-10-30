"""ERP 标准库更新工具。

默认只预演（dry-run），不写任何文件；加 --apply 才真正归档并登记。

设计要点：
1. 表头守卫：新 CSV 的列名集合必须与当前登记版本完全一致，否则拒绝。
   ERP 导出多一列/少一列/列改名，会让该表全部记录的 erp_fingerprint 改变，
   进而使引用它们的已确认记录集体失效。这是最需要拦住的一种更新。
2. 差异按「来源表 + 商家编码 + 整行原始字段」比对，不看字节，
   所以用 Excel/pandas 另存一遍（引号、换行变化）不会被误判成大面积修改。
3. 影响评估直接复用线上判定逻辑：比对每个确认登记的 ERP 指纹与更新后的实际指纹，
   算出哪些确认会失效。失效意味着回退到算法判定，不会自动变成「待确认」。
4. --apply 时：归档旧版到 data/erp_versions/<旧版本>/，覆盖 data/ 两份 CSV，
   更新 config/erp_library.json（含更新历史）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from confirmed_mappings import digest  # noqa: E402

DEFAULT_MANIFEST = ROOT / 'config' / 'erp_library.json'
NAME_CANDIDATES = ('组合装名称', '货品名称', '商品名称', '名称')
COMBO_NAMES = ('组合装名称', '商品名称', '名称')
SINGLE_NAMES = ('货品名称', '商品名称', '名称')


# ---------------------------------------------------------------- 读取与识别

def read_csv_any(path: Path) -> tuple[pd.DataFrame, str]:
    last = None
    for enc in ('utf-8-sig', 'utf-8', 'gbk'):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str, keep_default_na=False), enc
        except UnicodeDecodeError as exc:  # 换下一个编码再试
            last = exc
    raise SystemExit(f'无法识别文件编码：{path}（{last}）')


def pick_name_column(columns, preferred=NAME_CANDIDATES) -> str | None:
    for candidate in preferred:
        if candidate in columns:
            return candidate
    for column in columns:
        if '名称' in str(column):
            return str(column)
    return None


def fingerprint(source: str, raw: dict) -> str:
    return digest({'source': source, 'raw': raw})


def table_records(df: pd.DataFrame, source: str, code_col: str) -> list[dict]:
    """把一张表拆成可比较的记录；保留全部行，不按编码去重。"""
    records = []
    for raw in df.to_dict('records'):
        code = str(raw.get(code_col, '')).strip()
        records.append({'code': code, 'fp': fingerprint(source, raw), 'raw': raw})
    return records


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- 差异统计

def diff_records(old: list[dict], new: list[dict]) -> dict:
    """按编码归并差异。同一编码可能有多行，全部保留。"""
    old_by = defaultdict(list)
    new_by = defaultdict(list)
    for r in old:
        old_by[r['code']].append(r['fp'])
    for r in new:
        new_by[r['code']].append(r['fp'])

    added, removed, changed = [], [], []
    old_fp_set = {fp for fp in old_by.values() for fp in fp}
    keys = set(old_by) | set(new_by)
    for code in keys:
        old_fps = Counter(old_by.get(code, []))
        new_fps = Counter(new_by.get(code, []))
        if not old_fps:
            added.append((code, sum(new_fps.values())))
        elif not new_fps:
            removed.append((code, sum(old_fps.values())))
        elif old_fps != new_fps:
            changed.append((code, sum(old_fps.values()), sum(new_fps.values())))
    return {'added': sorted(added), 'removed': sorted(removed), 'changed': sorted(changed)}


# ---------------------------------------------------------------- 影响评估

def collect_dependencies(base: Path) -> dict:
    """收集所有确认对 (编码, ERP指纹) 的依赖。

    五份配置、两类绑定形式，缺一不可：
    - 多编码多指纹（erp_bindings）：sku_audit_reviews、agricultural_confirmations
    - 单编码单指纹（code -> fingerprint）：confirmed_business_specs.products、
      erp_product_confirmations.records、confirmed_mappings

    只覆盖前两类会让改动农产品、业务规格、成品身份绑定的记录时，
    错误地报告「无确认受影响」。
    """
    cfg = base / 'config'
    deps = {'multi': [], 'single': []}

    def read(name):
        path = cfg / name
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

    def add_multi(kind, label, bindings):
        if not bindings:
            return
        normalized = {}
        for code, value in bindings.items():
            # 两种存储形式并存：sku_audit_reviews / agricultural 用列表，
            # confirmed_mappings 的 accepted_erp_records 用单个字符串。
            # 字符串若直接 sorted() 会被拆成单字符列表，与真实指纹永远不等，
            # 结果是该形式的所有绑定恒定误报「失效」。
            if isinstance(value, str):
                normalized[code] = [value] if value else []
            else:
                normalized[code] = sorted(str(fingerprint) for fingerprint in value)
        deps['multi'].append({'kind': kind, 'label': label, 'bindings': normalized})

    def add_single(kind, label, code, fingerprint):
        if code and fingerprint:
            deps['single'].append({'kind': kind, 'label': label,
                                   'code': code, 'fp': fingerprint})

    data = read('sku_audit_reviews.json')
    if data:
        for entry in data.get('reviews', {}).values():
            ctx = entry.get('context', {})
            add_multi('SKU复核', f"{ctx.get('平台', '')} · SKU {ctx.get('SKU ID', '')}",
                      entry.get('erp_bindings') or {})

    data = read('agricultural_confirmations.json')
    if data:
        for entry in data.get('rows', {}).values():
            ctx = entry.get('context', {})
            add_multi('农产品确认', f"{ctx.get('平台', '')} · SKU {ctx.get('SKU ID', '')}",
                      entry.get('erp_bindings') or {})

    data = read('confirmed_business_specs.json')
    if data:
        for code, entry in (data.get('products') or {}).items():
            add_single('业务规格确认', f'业务规格 {code}', code, entry.get('erp_fingerprint'))

    data = read('erp_product_confirmations.json')
    if data:
        for code, entry in (data.get('records') or {}).items():
            add_single('成品身份确认', f'成品身份 {code}', code, entry.get('erp_fingerprint'))

    data = read('confirmed_mappings.json')
    if data:
        for key, entry in (data.get('mappings') or {}).items():
            # 标签必须能区分不同映射：多条映射的 confirmed_by 往往相同，
            # 只用它会互相合并，导致失效条数被少算。
            label = f"人工映射 {entry.get('confirmed_by', '')} · {str(key)[:8]}"
            accepted = entry.get('accepted_erp_records') or {}
            if accepted:
                add_multi('人工映射', label, accepted)
            elif entry.get('erp_code'):
                add_single('人工映射', label, entry['erp_code'], entry.get('erp_fingerprint'))
    return deps


def dependency_statuses(records: dict, base: Path) -> dict:
    """返回 {(类型, 标签, 编码): 原因}，只含当前失效的绑定。"""
    by_code = defaultdict(list)
    for rows in records.values():
        for record in rows:
            by_code[record['code']].append(record['fp'])

    statuses = {}
    deps = collect_dependencies(base)
    for item in deps['multi']:
        for code, expected in item['bindings'].items():
            actual = sorted(by_code.get(code, []))
            if actual == sorted(expected):
                continue
            statuses[(item['kind'], item['label'], code)] = (
                f'ERP记录 {code} 内容变化' if actual else f'ERP记录 {code} 已不存在')
    for item in deps['single']:
        actual = by_code.get(item['code'], [])
        if len(actual) == 1 and actual[0] == item['fp']:
            continue
        if len(actual) != 1:
            reason = f'ERP记录 {item["code"]} 缺失或重复（{len(actual)} 条）'
        else:
            reason = f'ERP记录 {item["code"]} 内容变化'
        statuses[(item['kind'], item['label'], item['code'])] = reason
    return statuses


def evaluate_impact(old_records: dict, new_records: dict, base: Path) -> tuple[list[dict], list[dict]]:
    """区分「本次更新造成的失效」和「更新前就已经失效」。

    混在一起报会让报告失去价值：历史遗留的过期绑定会淹没真正需要关注的那几条。
    """
    before = dependency_statuses(old_records, base)
    after = dependency_statuses(new_records, base)

    def rows(statuses, keys):
        return [{'kind': key[0], 'label': key[1], 'code': key[2], 'reason': statuses[key]}
                for key in keys]

    newly = rows(after, [k for k in after if k not in before])
    preexisting = rows(after, [k for k in after if k in before])
    return newly, preexisting


# ---------------------------------------------------------------- 结论级预演

def run_verify(base: Path, platform_files: list[str], platform: str, store: str,
               combo: Path | None, single: Path | None, out_dir: Path) -> list[Path]:
    """调用核验入口生成结果；combo/single 为空表示使用当前标准库。"""
    script = base / 'scripts' / 'verify_codes.py'
    if not script.is_file():
        raise SystemExit(f'找不到核验入口：{script}')
    outputs = []
    for index, platform_file in enumerate(platform_files):
        out = out_dir / f'{platform}_{index}.xlsx'
        cmd = [sys.executable, str(script),
               '--platform-file', platform_file, '--platform', platform,
               '--store', store, '--output', str(out)]
        if combo and single:
            cmd += ['--combo-erp', str(combo), '--single-erp', str(single)]
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=1800)
        if result.returncode != 0 or not out.exists():
            raise SystemExit(f'核验失败：{platform_file}\n{result.stderr[-1200:]}')
        outputs.append(out)
    return outputs


STATUS_COLUMNS = ['平台', '商品ID', 'SKU_ID', '名称', '规格', '原编码',
                  '状态', '推测', '问题', 'c1', 'c2', 'c3']
COMPARE_FIELDS = ('状态', '原编码', '推测')


def load_status(paths: list[Path]) -> list[dict]:
    """读取全部结果，保留重复行。

    同一 (商品ID, SKU_ID) 可能在多个导出文件里重复出现。用 dict 归并会互相覆盖，
    把后一份的内容当作唯一事实，差异被吃掉，所以这里返回列表，由比对函数分组。
    """
    from openpyxl import load_workbook
    records = []
    for path in paths:
        sheet = load_workbook(path)['全部结果']
        for row in sheet.iter_rows(min_row=5, values_only=True):
            data = dict(zip(STATUS_COLUMNS, row))
            if not any(value is not None and str(value).strip() for value in data.values()):
                continue
            records.append(data)
    return records


def compare_status(before: list[dict], after: list[dict]) -> list[dict]:
    """比较状态、原编码、推测，并报出行数变化（新增或消失）。

    只比状态会漏掉「编码改了但状态没变」「目标编码换了」以及新增/消失的行。
    """
    def group(rows):
        grouped = defaultdict(list)
        for row in rows:
            grouped[(str(row['商品ID']), str(row['SKU_ID']))].append(row)
        return grouped

    grouped_before, grouped_after = group(before), group(after)
    changes = []
    for key in set(grouped_before) | set(grouped_after):
        old_rows = grouped_before.get(key, [])
        new_rows = grouped_after.get(key, [])
        sample = (old_rows or new_rows)[0]
        if len(old_rows) != len(new_rows):
            changes.append({'code': sample['原编码'], 'spec': str(sample['规格'])[:44],
                            'field': '行数', 'old': f'{len(old_rows)} 行',
                            'new': f'{len(new_rows)} 行'})
            continue
        for old_row, new_row in zip(old_rows, new_rows):
            for field in COMPARE_FIELDS:
                old_value = str(old_row.get(field, ''))
                new_value = str(new_row.get(field, ''))
                if old_value != new_value:
                    changes.append({'code': old_row['原编码'],
                                    'spec': str(old_row['规格'])[:44],
                                    'field': field, 'old': old_value, 'new': new_value})
    return changes


# ---------------------------------------------------------------- 登记写入

def next_version(manifest: dict) -> str:
    """按「当天已出现的最大序号 + 1」生成，不按条数计数。

    计数法在两种情况下会撞号：当前已是当天 v1 但 updates 为空；历史版本号不连续
    （如只有 v1、v3）。两种都会让新旧版本同名，归档目录互相覆盖。
    """
    today = date.today().strftime('%Y%m%d')
    prefix = f'erp-{today}-v'
    highest = 0
    versions = [manifest.get('version', '')]
    versions += [item.get('version', '') for item in manifest.get('updates') or []]
    for value in versions:
        value = str(value)
        if value.startswith(prefix) and value[len(prefix):].isdigit():
            highest = max(highest, int(value[len(prefix):]))
    return f'{prefix}{highest + 1}'


def ensure_gbk_encodable(df: pd.DataFrame, label: str) -> None:
    """写出前整体校验编码，避免写到一半失败留下半更新库。"""
    for column in df.columns:
        for value in df[column]:
            text = str(value)
            try:
                text.encode('gbk')
            except UnicodeEncodeError:
                raise SystemExit(
                    f'{label} 含 GBK 无法编码的字符，已中止，未改动任何文件。\n'
                    f'  列：{column}\n  值：{text[:80]!r}\n'
                    f'  在 ERP 导出侧修正后重试；如需改存 UTF-8，须同步调整读取编码。')


def stage_csv(df: pd.DataFrame, target: Path) -> Path:
    """把表写成同目录的临时文件，返回临时路径。失败时清掉自己留下的半成品。"""
    tmp = target.with_name(target.name + '.staged')
    try:
        df.to_csv(tmp, index=False, encoding='gbk', lineterminator='\n')
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    return tmp


def commit(staged: list[tuple[Path, Path]]) -> None:
    """把已写好的临时文件统一替换到目标位置；任一步失败则全部回滚。

    两份 CSV 和登记文件必须在同一个事务里：只回滚 CSV 而不回滚登记，
    或者登记写失败而 CSV 已换，都会留下半更新库。

    回滚本身失败时（例如目标被占用、权限问题），**备份一律保留**并打印路径。
    删掉备份等于把「部分文件已换新」变成无法恢复的状态。
    """
    backups: list[tuple[Path, Path]] = []
    keep_backups = False
    try:
        for _, target in staged:
            backup = target.with_name(target.name + '.bak')
            shutil.copy2(target, backup)
            backups.append((backup, target))
        for tmp, target in staged:
            os.replace(tmp, target)
    except Exception:
        failed = []
        for backup, target in backups:
            if not backup.exists():
                continue
            try:
                shutil.copy2(backup, target)
            except Exception:
                failed.append(target.name)
        if failed:
            keep_backups = True
            print('写入失败，且以下文件无法自动恢复：' + '、'.join(failed))
            print('备份已保留，未删除。请手工从下列文件恢复后再重试：')
            for backup, target in backups:
                print(f'    {backup}  →  {target}')
        else:
            print(f'写入失败，已从备份恢复：{"、".join(target.name for _, target in backups)}')
        raise
    finally:
        for tmp, _ in staged:
            Path(tmp).unlink(missing_ok=True)
        if not keep_backups:
            for backup, _ in backups:
                Path(backup).unlink(missing_ok=True)


def stage_and_swap(pairs: list[tuple[pd.DataFrame, Path]]) -> None:
    """两份表的便捷入口：暂存后统一提交。"""
    commit([(stage_csv(df, path), path) for df, path in pairs])


def archive_and_install(manifest: dict, manifest_path: Path,
                        combo_df: pd.DataFrame, single_df: pd.DataFrame,
                        stats: dict, broken: list[dict]) -> dict:
    base = manifest_path.resolve().parent.parent
    old_version = manifest.get('version', 'unregistered')
    archive_dir = base / 'data' / 'erp_versions' / old_version
    archive_dir.mkdir(parents=True, exist_ok=True)

    # 沿用登记里记录的路径，不改变文件位置，避免路径解析风险
    combo_path = (base / manifest['erp']['combo']['path']).resolve()
    single_path = (base / manifest['erp']['single']['path']).resolve()

    # 归档旧版（已归档则不覆盖）
    for path, filename in ((combo_path, '组合装.csv'), (single_path, '单品.csv')):
        target = archive_dir / filename
        if path.exists() and not target.exists():
            shutil.copy2(path, target)

    # 长期归档：登记文件另存一份供人工回退（与事务内的临时 .bak 是两回事）
    backup_manifest = manifest_path.with_suffix(f'.backup-{old_version}.json')
    shutil.copy2(manifest_path, backup_manifest)

    ensure_gbk_encodable(combo_df, '组合装')
    ensure_gbk_encodable(single_df, '单品')

    # 三份一起暂存：两份 CSV + 登记文件。任一份写失败，已写的临时文件全部清掉。
    new_version = next_version(manifest)
    staged: list[tuple[Path, Path]] = []
    manifest_tmp = manifest_path.with_name(manifest_path.name + '.staged')
    try:
        combo_tmp = stage_csv(combo_df, combo_path)
        staged.append((combo_tmp, combo_path))
        single_tmp = stage_csv(single_df, single_path)
        staged.append((single_tmp, single_path))

        manifest['version'] = new_version
        manifest['registered_at'] = date.today().isoformat()
        manifest['erp']['combo'].update({
            'sha256': sha256_of(combo_tmp),
            'rows': int(len(combo_df)),
        })
        manifest['erp']['single'].update({
            'sha256': sha256_of(single_tmp),
            'rows': int(len(single_df)),
        })
        manifest.setdefault('updates', []).append({
            'version': new_version,
            'registered_at': date.today().isoformat(),
            'previous_version': old_version,
            'combo_rows': int(len(combo_df)),
            'single_rows': int(len(single_df)),
            'added_codes': len(stats['added']),
            'changed_codes': len(stats['changed']),
            'removed_codes': len(stats['removed']),
            'broken_confirmations': len(broken),
        })

        # Register the path before writing: a failed write may leave a partial JSON.
        staged.append((manifest_tmp, manifest_path))
        manifest_tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        for tmp, _ in staged:
            Path(tmp).unlink(missing_ok=True)
        raise

    commit(staged)
    return {'version': new_version, 'archive': archive_dir, 'manifest_backup': backup_manifest}


# ---------------------------------------------------------------- 主流程

def main() -> int:
    parser = argparse.ArgumentParser(description='ERP 标准库更新（默认预演，--apply 才写入）')
    parser.add_argument('--combo-erp', required=True, help='新组合装 CSV')
    parser.add_argument('--single-erp', required=True, help='新单品 CSV')
    parser.add_argument('--manifest', default=str(DEFAULT_MANIFEST), help='登记文件，默认 config/erp_library.json')
    parser.add_argument('--apply', action='store_true', help='真正写入：归档、覆盖、更新登记')
    parser.add_argument('--preview-platform-file', action='append', default=[],
                        help='结论级预演用的平台导出文件，可重复')
    parser.add_argument('--preview-platform', default='快手', help='结论级预演的平台名')
    parser.add_argument('--preview-store', default='预演', help='结论级预演的店铺名')
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    base = manifest_path.parent.parent

    combo_new = Path(args.combo_erp).resolve()
    single_new = Path(args.single_erp).resolve()
    for path in (combo_new, single_new):
        if not path.is_file():
            raise SystemExit(f'文件不存在：{path}')

    combo_df, combo_enc = read_csv_any(combo_new)
    single_df, single_enc = read_csv_any(single_new)

    print('=' * 62)
    print(f'ERP 更新{"（正式写入）" if args.apply else "（预演，不写任何文件）"}')
    print('=' * 62)
    print(f'当前登记版本：{manifest.get("version")}   登记日期 {manifest.get("registered_at")}')

    # 1) 列与编码校验
    problems = []
    for label, df, enc in (('组合装', combo_df, combo_enc), ('单品', single_df, single_enc)):
        name_col = pick_name_column(df.columns, COMBO_NAMES if label == '组合装' else SINGLE_NAMES)
        if '商家编码' not in df.columns:
            problems.append(f'{label}缺少「商家编码」列；实际列：{list(df.columns)}')
        if not name_col:
            problems.append(f'{label}找不到名称列；实际列：{list(df.columns)}')
        print(f'\n[{label}] {len(df)} 行，编码 {enc}，名称列「{name_col}」')
        print(f'  列：{list(df.columns)}')
    if problems:
        raise SystemExit('\n'.join(['无法继续：'] + ['  - ' + p for p in problems]))

    # 2) 基线校验：当前库必须与登记一致，否则后面的差异和影响都不可信
    for key, label in (('combo', '组合装'), ('single', '单品')):
        current = (base / manifest['erp'][key]['path']).resolve()
        if not current.is_file():
            raise SystemExit(f'当前标准库缺失：{current}')
        actual_hash = sha256_of(current)
        registered = manifest['erp'][key]['sha256']
        if actual_hash != registered:
            raise SystemExit(
                f'{label} 当前文件与登记哈希不一致，预演结果不可信，已中止。\n'
                f'  文件：{current}\n'
                f'  实际：{actual_hash}\n'
                f'  登记：{registered}\n'
                f'  先确认库是否被手工改过；若确实要以此为准，先修正登记再来更新。')

    # 3) 编码可写性：GBK 写不出的字符必须在动任何文件之前拦住
    ensure_gbk_encodable(combo_df, '组合装')
    ensure_gbk_encodable(single_df, '单品')

    # 4) 表头守卫：列集合必须与登记版本一致。列顺序不影响记录指纹，只提示不拦截
    schema_ok = True
    for key, label, df in (('combo', '组合装', combo_df), ('single', '单品', single_df)):
        current = base / manifest['erp'][key]['path']
        if not current.exists():
            raise SystemExit(f'当前标准库缺失：{current}')
        old_cols = list(pd.read_csv(current, encoding='gbk', nrows=0).columns)
        new_cols = list(df.columns)
        if set(old_cols) != set(new_cols):
            schema_ok = False
            added = [c for c in new_cols if c not in old_cols]
            missing = [c for c in old_cols if c not in new_cols]
            print(f'\n⚠ 表头不一致 —— {label}')
            print(f'   登记版本：{old_cols}')
            print(f'   本次文件：{new_cols}')
            if added:
                print(f'   多出列：{added}')
            if missing:
                print(f'   缺少列：{missing}')
            print('   后果：该表全部记录的指纹会改变，引用它们的已确认记录将全部失效。')
        elif old_cols != new_cols:
            print(f'\n提示：{label} 列顺序变化（不影响记录指纹，按新顺序处理）')
            print(f'   登记版本：{old_cols}')
            print(f'   本次文件：{new_cols}')
    if not schema_ok:
        print('\n已中止：表头与登记版本不一致，不能继续。')
        print('两条理由都必须同时解决才能更新：')
        print('  1. 核验引擎按固定列名读取 ERP —— 组合装取「组合装名称」、单品取「货品名称」')
        print('     （见 verify_codes.load_erp）。列名改了，工具即便放行，后续核验也跑不通。')
        print('  2. 列集合变化会让该表全部记录的指纹改变，引用它们的已确认记录集体失效。')
        print('正确顺序：先改核验引擎的列名解析并完成回归，再来更新库。')
        return 2

    # 5) 记录级差异
    print('\n' + '-' * 62)
    print('记录差异（按 编码 + 整行内容 比对，不看字节）')
    print('-' * 62)
    old_records, new_records = {}, {}
    stats_all = {'added': [], 'removed': [], 'changed': []}
    for key, label, df in (('combo', '组合装', combo_df), ('single', '单品', single_df)):
        old_df = pd.read_csv(base / manifest['erp'][key]['path'], encoding='gbk',
                             dtype=str, keep_default_na=False)
        source = label
        old_recs = table_records(old_df, source, '商家编码')
        new_recs = table_records(df, source, '商家编码')
        old_records[label] = old_recs
        new_records[label] = new_recs
        stat = diff_records(old_recs, new_recs)
        print(f'\n[{label}] 旧 {len(old_recs)} 行 → 新 {len(new_recs)} 行')
        print(f'  新增编码 {len(stat["added"])} 个，修改 {len(stat["changed"])} 个，删除 {len(stat["removed"])} 个')
        for code, count in stat['added'][:8]:
            print(f'    + {code}（{count} 行）')
        for code, old_n, new_n in stat['changed'][:8]:
            print(f'    ~ {code}（{old_n} 行 → {new_n} 行，内容变化）')
        for code, count in stat['removed'][:8]:
            print(f'    - {code}（{count} 行）')
        if len(stat['added']) > 8:
            print(f'    … 新增共 {len(stat["added"])} 个，仅列前 8 个')
        for field in ('added', 'changed', 'removed'):
            stats_all[field] += stat[field]

    # 6) 影响评估
    print('\n' + '-' * 62)
    print('已确认记录的影响评估')
    print('-' * 62)
    newly_broken, preexisting = evaluate_impact(old_records, new_records, base)
    if not newly_broken:
        print('本次更新不会使任何原本有效的确认失效。')
    else:
        print(f'⚠ 本次更新会导致 {len(newly_broken)} 条确认失效（更新前有效，更新后失效）：')
        for item in newly_broken[:20]:
            print(f'    [{item["kind"]}] {item["label"]} —— {item["reason"]}')
        if len(newly_broken) > 20:
            print(f'    … 共 {len(newly_broken)} 条，仅列前 20 条')
        print('    失效后回退到算法判定，不会自动变成「待确认」，需人工重新确认。')
    if preexisting:
        kinds = Counter(item['kind'] for item in preexisting)
        print(f'\n另有 {len(preexisting)} 条绑定在本次更新前就已失效（与本次无关，未展开）：')
        print(f'    {dict(kinds)}')
        print('    这些属于历史遗留的过期绑定，建议单独清理。')

    # 7) 结论级预演
    if args.preview_platform_file:
        print('\n' + '-' * 62)
        print(f'结论级预演：新旧两版 ERP 各跑一遍 {args.preview_platform} 数据，对比结论')
        print('-' * 62)
        with tempfile.TemporaryDirectory(prefix='erp_preview_') as tmp:
            tmp_dir = Path(tmp)
            before_dir = tmp_dir / 'before'
            after_dir = tmp_dir / 'after'
            stage = tmp_dir / 'new'
            for folder in (before_dir, after_dir, stage):
                folder.mkdir()
            combo_stage = stage / '组合装.csv'
            single_stage = stage / '单品.csv'
            combo_df.to_csv(combo_stage, index=False, encoding='gbk', lineterminator='\n')
            single_df.to_csv(single_stage, index=False, encoding='gbk', lineterminator='\n')
            before_paths = run_verify(base, args.preview_platform_file, args.preview_platform,
                                      args.preview_store, None, None, before_dir)
            after_paths = run_verify(base, args.preview_platform_file, args.preview_platform,
                                     args.preview_store, combo_stage, single_stage, after_dir)
            before, after = load_status(before_paths), load_status(after_paths)
            changes = compare_status(before, after)
            print(f'旧库 {len(before)} 行 → 新库 {len(after)} 行，共 {len(changes)} 处差异')
            for item in changes[:15]:
                print(f'    {item["code"]}  [{item["field"]}] {item["old"]} → {item["new"]}   {item["spec"]}')
            if len(changes) > 15:
                print(f'    … 共 {len(changes)} 处，仅列前 15 条')

    # 8) 写入或收尾
    print('\n' + '=' * 62)
    if not args.apply:
        print('预演完成，未修改任何文件。')
        print('确认无误后加 --apply 执行：归档旧版 → 覆盖标准库 → 更新登记。')
        return 0

    result = archive_and_install(manifest, manifest_path,
                                 combo_df, single_df, stats_all, newly_broken)
    print(f'已更新到版本 {result["version"]}')
    print(f'旧版归档：{result["archive"]}')
    print(f'登记备份：{result["manifest_backup"]}')
    print('下一步：重跑各平台核验，核对状态变化是否符合预期。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
