"""Explicit human confirmations, scoped to an unchanged platform SKU and ERP row."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DEFAULT_PATH = Path(__file__).resolve().parents[1] / 'config/confirmed_mappings.json'
CONTEXT_FIELDS = ('平台', '店铺', '商品 ID', 'SKU ID', '商品标题', 'SKU', 'ERP货品编号', 'ERP规格编码', '独立规格数量')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def platform_key(row):
    return digest([str(row.get(k, '')) for k in CONTEXT_FIELDS[:4]])


def platform_fingerprint(row):
    return digest({k: str(row.get(k, '')) for k in CONTEXT_FIELDS})


def load_mappings(path=None):
    path = Path(path) if path else DEFAULT_PATH
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    entries = data['mappings']
    if not isinstance(entries, dict):
        raise ValueError('人工确认映射的mappings必须是对象')
    return entries


def lookup_confirmation(row, records, entries):
    entry = entries.get(platform_key(row))
    if entry is None:
        return None, ''
    if entry['platform_fingerprint'] != platform_fingerprint(row):
        return None, '平台商品标题、SKU规格或身份字段变化，人工映射需重新确认'
    accepted = entry.get('accepted_erp_records')
    if accepted:
        verified = {}
        for code, fingerprint in accepted.items():
            alternatives = [r for r in records if r['code'] == code]
            if len(alternatives) != 1:
                return None, '已确认可用编码在ERP中缺失或重复，需重新确认'
            if alternatives[0].get('erp_fingerprint') != fingerprint:
                return None, '已确认可用ERP记录已变化，需重新确认'
            verified[code] = alternatives[0]
        raw = str(row.get('原编码', ''))
        wrapped = re.fullmatch(r'="((?:[^"]|"")*)"', raw)
        current = (wrapped.group(1).replace('""', '"') if wrapped else raw).strip()
        if current in verified:
            return {**entry, 'record': verified[current]}, ''
        if len(verified) > 1:
            return None, '存在多个已确认可用编码；当前码为空或不在允许范围，需人工选择目标编码'
        return {**entry, 'record': next(iter(verified.values()))}, ''
    matches = [r for r in records if r['code'] == entry['erp_code']]
    if len(matches) != 1:
        return None, '人工映射编码在ERP中缺失或重复，需重新确认'
    if matches[0].get('erp_fingerprint') != entry['erp_fingerprint']:
        return None, 'ERP对应记录已变化，人工映射需重新确认'
    return {**entry, 'record': matches[0]}, ''


def import_confirmations(report_path, erp_records, erp_df, mapping_path=None):
    """Only rows marked 是 with a person and reason are saved; candidates never are."""
    report_path = Path(report_path).resolve()
    destination = Path(mapping_path).resolve() if mapping_path else DEFAULT_PATH.resolve()
    if destination == report_path:
        raise ValueError('映射文件不能覆盖确认报告')
    rows = pd.read_excel(report_path, sheet_name='人工确认表', dtype=str, keep_default_na=False)
    marked = rows[rows['确认'].eq('是')]
    if marked.empty:
        return 0
    metadata = pd.read_excel(report_path, sheet_name='平台文件识别', dtype=str, keep_default_na=False)
    for row in metadata.to_dict('records'):
        source = Path(row['source_file'])
        if not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('原始平台文件已变化或不可读取，请重新核验后再确认')
        if destination == source.resolve():
            raise ValueError('映射文件不能覆盖原始平台文件')
    expected_erp = set(pd.read_excel(report_path, sheet_name='ERP合并库', dtype=str, keep_default_na=False)['ERP文件SHA256'])
    if expected_erp != set(erp_df['ERP文件SHA256']):
        raise ValueError('ERP文件已变化，请重新核验后再确认')
    if destination in {Path(p).resolve() for p in erp_df['ERP源文件']}:
        raise ValueError('映射文件不能覆盖ERP源文件')
    pending = {}
    for row in marked.to_dict('records'):
        if not all(row.get(k, '').strip() for k in ('商品 ID', 'SKU ID', '确认ERP编码', '确认人', '确认依据')):
            raise ValueError('标记确认的行必须填写商品ID、SKU ID、确认ERP编码、确认人和确认依据')
        if row['平台内容指纹'] != platform_fingerprint(row):
            raise ValueError('人工确认表的原始商品字段被修改，请重新生成报告')
        matches = [r for r in erp_records if r['code'] == row['确认ERP编码'].strip()]
        if len(matches) != 1:
            raise ValueError('确认ERP编码必须在合并库中非空且唯一')
        key = platform_key(row)
        entry = {'platform_fingerprint': platform_fingerprint(row), 'erp_code': matches[0]['code'],
                 'erp_fingerprint': matches[0]['erp_fingerprint'], 'confirmed_by': row['确认人'].strip(),
                 'basis': row['确认依据'].strip(), 'confirmed_at': datetime.now(timezone.utc).isoformat()}
        if key in pending and (pending[key]['erp_code'], pending[key]['platform_fingerprint']) != (entry['erp_code'], entry['platform_fingerprint']):
            raise ValueError('同一平台SKU出现冲突的人工确认，未保存任何行')
        pending[key] = entry
    entries = load_mappings(destination)
    entries.update(pending)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        backup = destination.with_name(destination.name + '.before-import.json')
        backup.write_bytes(destination.read_bytes())
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps({'version': 1, 'mappings': entries}, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(destination)
    return len(pending)
