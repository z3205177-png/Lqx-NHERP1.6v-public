"""Make an identified expired binding visible without reusing its decision."""
import json


def mark_expired(result, mechanism, reason):
    updated = dict(result)
    entries = json.loads(updated.get('确认失效JSON') or '[]')
    known = next((e for e in entries if e['机制'] == mechanism and e['原因'] == reason), None)
    if known is None:
        known = {'机制':mechanism, '原因':reason, '原算法状态':result['核验状态'],
                 '原算法依据':result.get('匹配依据', ''), '原冲突项目':result.get('冲突项目', ''),
                 '原核验说明':result.get('核验说明', '')}
        entries.append(known)
    # Actual missing/unknown codes retain their own required-action category.
    # A revived specification conflict does not prove an expired exception wrong.
    if updated['核验状态'] in {'核对通过', '异常（商品/规格不一致）'}:
        updated['核验状态'] = '待人工确认'
    note = f'{mechanism}已失效：{reason}'
    if note not in updated.get('核验说明', ''):
        updated['核验说明'] = '；'.join(filter(None, [note,
            '原算法状态：' + known['原算法状态'], updated.get('核验说明', '')]))
    marker = '确认失效：' + mechanism
    if marker not in updated.get('判定路径', ''):
        updated['判定路径'] = '；'.join(filter(None, [updated.get('判定路径', ''), marker]))
    updated['确认有效性'] = '已失效'
    updated['确认失效JSON'] = json.dumps(entries, ensure_ascii=False)
    return updated
