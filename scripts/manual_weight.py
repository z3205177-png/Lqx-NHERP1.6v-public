"""Flag unsupported agricultural sale weights; never convert or compare them."""
import re
import unicodedata

PRODUCE = re.compile(r'大蒜|蒜头|蒜瓣|果蔬|水果|蔬菜|农产品')
WEIGHT = re.compile(r'\d+(?:\.\d+)?\s*(?:公斤|千克|市斤|斤|克|kg|g)(?![a-z])', re.I)


def needs_weight_review(platform, current):
    features = [platform, *(r['features'] for r in current)]
    texts = [unicodedata.normalize('NFKC', f.get('text', '')).lower() for f in features]
    return any(PRODUCE.search(t) for t in texts) and any(WEIGHT.search(t) for t in texts)


def apply_weight_guard(result, platform, current):
    if not needs_weight_review(platform, current):
        return result
    result = dict(result)
    note = '需人工核重：农产品重量尚未自动核验，未执行斤/克/kg/g换算或重量比较'
    if result['核验状态'] in {'核对通过', '编码正确'}:
        result['核验状态'] = '待人工确认'
        result['核验说明'] = '原编码已收录；重量尚需人工核验'
    if '需人工核重' not in result.get('核验说明', ''):
        result['核验说明'] = '；'.join(filter(None, [result.get('核验说明', ''), note]))
    if '需人工核重' not in result.get('判定路径', ''):
        result['判定路径'] = '；'.join(filter(None, [result.get('判定路径', ''), '需人工核重']))
    return result
