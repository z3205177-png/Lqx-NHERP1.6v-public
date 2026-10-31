"""Human audit decisions tied to exact platform SKU content and ERP records."""
import json
import re
from pathlib import Path

from confirmed_mappings import digest
from confirmation_expiry import mark_expired

DEFAULT_PATH = Path(__file__).resolve().parents[1] / 'config/sku_audit_reviews.json'
IDENTITY = ('平台', '商品 ID', 'SKU ID')
CONTENT = (*IDENTITY, '商品标题', 'SKU', 'ERP货品编号', 'ERP规格编码', '独立规格数量')
MARKER = '人工SKU复核'


def review_key(context):
    return digest([str(context.get(k, '')) for k in IDENTITY])


def content_fingerprint(context):
    # Marketplace product/SKU IDs identify the reviewed row independently of a
    # local export filename or the operator's choice of store label.
    return digest({k: str(context.get(k, '')) for k in CONTENT})


def load_reviews(path=None):
    path = Path(path) if path else DEFAULT_PATH
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('reviews'), dict):
        raise ValueError('SKU人工复核配置必须为version=1且reviews为对象')
    for key, entry in data['reviews'].items():
        if (key != review_key(entry['context']) or entry['mode'] not in {'confirmed', 'pending', 'conflict'}
                or not isinstance(entry['erp_bindings'], dict)):
            raise ValueError('SKU人工复核配置的身份、模式或ERP绑定无效')
        if entry['mode'] == 'confirmed' and len(entry['erp_bindings'].get(entry.get('target_code'), [])) != 1:
            raise ValueError('已确认SKU目标必须绑定一条ERP记录')
    return data['reviews']


def literal_code(value):
    value = str(value).strip()
    wrapped = re.fullmatch(r'="((?:[^"]|"")*)"', value)
    return wrapped.group(1).replace('""', '"') if wrapped else value


def empty_suggestion(note):
    result = {k: '' for k in ('推测商家编码', '推测ERP商品名称', '推测依据',
                              '其他候选编码', '其他候选ERP记录', '推测ERP来源')}
    return {**result, '候选明细JSON': '[]', '推测候选编码数': 0, '仍需确认的问题': note}


def apply_review(context, current_code, result, by_code, entries):
    """Return a reviewed audit and an optional suggestion, without changing input."""
    entry = entries.get(review_key(context))
    if entry is None:
        return result, None
    code = literal_code(current_code)
    issue = ''
    if entry['content_fingerprint'] != content_fingerprint(context):
        issue = '平台商品标题、SKU规格或身份字段变化，人工复核需重新确认'
    elif code not in {entry['source_code'], entry.get('target_code', ''), ''}:
        issue = '当前编码不在本次人工复核的原码或确认目标范围，需重新确认'
    else:
        for expected_code, fingerprints in entry['erp_bindings'].items():
            actual = sorted(r['erp_fingerprint'] for r in by_code.get(expected_code, []))
            if actual != fingerprints:
                issue = '本次人工复核关联ERP记录缺失、重复或内容变化，需重新确认'
                break
    updated = dict(result)
    updated['判定路径'] = result.get('判定路径', '') + '；' + MARKER
    if issue:
        updated = mark_expired(updated, '人工复核', issue)
        return updated, empty_suggestion(issue)
    updated.update({'人工确认人': entry['reviewed_by'], '人工确认依据': entry['basis']})
    mode = entry['mode']
    if mode == 'confirmed':
        target = by_code[entry['target_code']][0]
        if code == target['code']:
            updated.update({'核验状态': '核对通过', '冲突项目': '', '规格问题': '',
                            '匹配依据': '本SKU已由用户明确确认，平台内容与ERP记录指纹一致',
                            '核验说明': entry['basis']})
            return updated, empty_suggestion('')
        # A confirmed replacement never proves the platform's old code correct.
        if updated['核验状态'] == '核对通过' or (updated['核验状态'] == '待人工确认'
                and '解析待确认' in updated.get('判定路径','')):
            # A valid, exact human replacement resolves the interpretation;
            # the different original code remains a confirmed conflict.
            updated['核验状态'] = '异常（商品/规格不一致）'
            updated['冲突项目'] = '原编码与本SKU已确认目标不同'
        note = f"本SKU已确认目标：{target['code']}（{target['name']}）；原编码及原异常保留，未自动改码。"
        updated['核验说明'] = updated.get('核验说明', '') + '；' + note
        proposal = empty_suggestion('正确目标已确认；仍需人工修改平台原编码')
        proposal.update({'推测商家编码': target['code'], '推测ERP商品名称': target['name'],
                         '推测ERP来源': f"{target['source']}，ERP源行{target['source_row']}",
                         '推测依据': '本SKU用户明确指定的目标编码，ERP记录指纹有效',
                         '推测候选编码数': 1,
                         '候选明细JSON': json.dumps([{'code': target['code'], 'name': target['name'],
                             'source': target['source'], 'source_row': target['source_row'],
                             'evidence': ['用户明确确认本SKU目标编码']}], ensure_ascii=False)})
        return updated, proposal
    if mode == 'pending':
        if code:
            updated['核验状态'] = '待人工确认'
        updated['匹配依据'] = '用户明确要求本SKU暂定关系保持待人工确认'
    elif mode == 'conflict':
        if updated['核验状态'] == '核对通过':
            updated['核验状态'] = '异常（商品/规格不一致）'
    else:
        raise ValueError('未知SKU人工复核模式：' + mode)
    updated['核验说明'] = updated.get('核验说明', '') + '；' + entry['basis']
    return updated, empty_suggestion(entry['basis'])
