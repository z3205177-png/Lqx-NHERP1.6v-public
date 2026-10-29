"""Interpret confirmed product facts, without overriding an audit verdict.

Source platforms are provenance. Reuse is bound to an unchanged ERP record and
selected specification text; the two explicitly SKU-only decisions retain IDs.
"""
import json
import re
import unicodedata
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / 'config/confirmed_business_specs.json'


def selected_spec(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(text))).strip().lower()


@lru_cache(maxsize=1)
def load_rules():
    data = json.loads(DEFAULT_PATH.read_text(encoding='utf-8')) if DEFAULT_PATH.exists() else {}
    if data and data.get('version') != 1:
        raise ValueError('业务口径配置版本无效')
    return data


def binding_valid(record, entry):
    return record.get('erp_fingerprint') == entry.get('erp_fingerprint')


def canonical_feature(feature, entry, build):
    result = deepcopy(feature)
    components = {}
    for key, part in entry.get('components', {}).items():
        item = build('', part['text'])
        item['qty'] = tuple(part['qty']) if part.get('qty') else None
        item['quantity_structure'] = {'raw': part['text'], 'qty': item['qty'],
            'parts': [], 'issues': [], 'incomplete': False, 'additive': False}
        components[key] = item
    quantity = entry.get('qty')
    result['qty'] = tuple(quantity) if quantity else None
    result['qty_issues'] = []
    result['quantity_structure'] = {'raw': feature['quantity_text'], 'qty': result['qty'],
        'parsed_total': result['qty'], 'parts': [dict(key=k, text=v['quantity_text'], qty=v['qty']) for k,v in components.items()],
        'issues': [], 'incomplete': False, 'additive': bool(components),
        'confirmed_rule_ids': entry['rule_ids']}
    result['confirmed_components'] = components
    for key, values in entry.get('evidence_overrides', {}).items():
        result['evidence'][key] = set(values)
    if 'color_values' in entry:
        result['business_color_values'] = entry['color_values']
    if entry.get('finished_product'):
        result['packaging_issue'] = ''
        result['families'] = set(entry['families'])
        result['erp_product_confirmation'] = '；'.join(entry['rule_ids'])
    result['business_rule_ids'] = list(entry['rule_ids'])
    return result


ACCESSORY_PATTERNS = {
    'oil': r'(?:[+＋]?\s*(?:送|赠|带))(?:[一二两\d]+\s*(?:瓶|支))?(?:艾草精油|艾草油|精油)(?!\s*贴)(?:\d+\s*(?:瓶|支|毫升|ml))?(?=[\s,，;；|{}【】()（）\[\]]|$)',
    'cover': r'(?:[+＋]?\s*(?:送|赠)|[+＋])(?:纯棉|加绒|长绒|超柔|仿兔绒|毛绒|水晶绒|樱花粉|大象灰|粉色|灰色|蓝色|黑色|白色|红色)*布套(?:各?\d+\s*个)?',
    'shell': r'(?:[+＋]?\s*(?:送|赠))?(?:\d+\s*个?)?(?:可爱|卡通猫|白色|蓝色|紫色|粉色|黄色|白|蓝|紫|粉|黄|KT|kt)*(?:蛋壳|暖蛋)(?:\d+\s*个?)?',
    'hook': r'(?:[+＋]?\s*(?:送|赠))(?:壁挂|挂钩|双面粘钩)(?:\d+\s*个)?',
    'sleeve': r'(?:[+＋]?\s*(?:送|赠)|[+＋])(?:粉色|灰色|蓝色|黑色|白色)*冰袖(?:粉色|灰色|蓝色|黑色|白色)*(?:\d+\s*(?:对|只))?',
    'pillow': r'(?:[+＋]?\s*(?:送|赠))(?:蓝色小花|蓝色|粉色|灰色|绿色)?冰枕(?:颜色随机|随机颜色|随机|\d+\s*个)?',
    'blanket': r'(?:[+＋]?\s*(?:送|赠))(?:毛毯|盖毯)(?:\d+\s*条)?',
}


def accessory_feature(feature, allowed, build):
    """Separate approved accessories so their colors/counts cannot become main specs."""
    text, accessories = feature['quantity_text'], {}
    for kind in allowed:
        if kind not in ACCESSORY_PATTERNS:
            continue
        def take(match):
            raw = match[0]
            numeric = re.sub(r'一(?=瓶|支)','1',raw)
            qty = re.search(r'(\d+)\s*(个|只|对|瓶|支|条|毫升|ml)', numeric)
            amount = (int(qty[1]), qty[2]) if qty else ((1, '个') if kind == 'shell' else None)
            if kind == 'shell' and not qty:
                number=re.search(r'\d+',raw)
                if number: amount=(int(number[0]),'个')
            accessories[kind] = {'text': raw, 'qty': amount}
            return ''
        text = re.sub(ACCESSORY_PATTERNS[kind], take, text, flags=re.I)
    if not accessories:
        return deepcopy(feature)
    if 'shell' in accessories:
        text = text.replace('替换芯','暖手贴').replace('暖芯','暖手贴')
        text = re.sub(r'(小暖手|大暖手)(?!贴)',r'\1贴',text)
    text = re.sub(r'[+＋]\s*(?=[,，;；|}]|$)', '', text)
    text = re.sub(r'(?<=[;；:：])\s*[+＋]', '', text)
    base = build(feature.get('title_text', ''), text, erp_name=text if feature.get('is_erp') else '')
    result = {**deepcopy(feature), **{k:base[k] for k in ('qty','qty_issues','quantity_structure','evidence','variants')}}
    result['quantity_structure']['raw'] = feature['quantity_text']
    result['component_parse_text'] = text
    result['business_accessories'] = accessories
    result['comparison_color_text'] = text
    return result


def transform_platform(feature, code, records, build):
    config = load_rules()
    scope = config.get('products', {}).get(code)
    if not scope:
        return feature, ''
    if len(records) != 1 or not binding_valid(records[0], scope):
        return feature, '已确认商品的ERP记录缺失、重复或内容变化，口径需重新确认'
    result = accessory_feature(feature, scope.get('accessories', []), build)
    result['business_rule_ids'] = scope['rule_ids']
    context = feature.get('context', {})
    if context.get('独立规格数量'):
        result['qty'],result['qty_issues'] = feature['qty'],feature['qty_issues']
    for entry in scope.get('specs', []):
        if selected_spec(feature['quantity_text']) != entry['selected_spec']:
            continue
        if str(context.get('独立规格数量','')) != entry.get('independent_quantity',''):
            continue
        identity = entry.get('identity')
        if identity and any(str(context.get(k,'')) != str(v) for k,v in identity.items()):
            continue
        result = canonical_feature(result, entry, build)
        break
    return result, ''


def transform_erp(record, build):
    scope = load_rules().get('products', {}).get(record['code'])
    if not scope or not binding_valid(record, scope):
        return
    feature = accessory_feature(record['features'], scope.get('accessories', []), build)
    if scope.get('erp_interpretation'):
        feature = canonical_feature(feature, scope['erp_interpretation'], build)
    record['features'] = feature


def accessory_conflicts(platform, erp):
    conflicts, issues = [], []
    pa, ea = platform.get('business_accessories', {}), erp.get('business_accessories', {})
    for kind in pa.keys() & ea.keys():
        a,b = pa[kind],ea[kind]
        if a['qty'] and b['qty']:
            if a['qty'][1] != b['qty'][1]:
                issues.append('附赠品单位尚未确认换算：'+kind)
            elif a['qty'][0] != b['qty'][0]:
                conflicts.append('附赠品数量不一致：'+kind)
        if kind in {'cover','shell','sleeve','pillow'}:
            colors=lambda text:set(re.findall('粉色|灰色|蓝色|黑色|白色|红色|紫色|绿色|黄色',text)) | {x+'色' for x in re.findall(r'([白蓝紫粉黄])(?=蛋壳|暖蛋)',text)}
            ac,bc=colors(a['text']),colors(b['text'])
            if ac and bc and not ac & bc and '随机' not in a['text']+b['text']:
                conflicts.append('附赠品颜色不一致：'+kind)
            materials=lambda text:set(re.findall('纯棉|仿兔绒|水晶绒|毛绒|加绒|长绒',text))
            am,bm=materials(a['text']),materials(b['text'])
            if am and bm and not am & bm:
                conflicts.append('附赠品材质不一致：'+kind)
    return conflicts,issues


def pending_note(context):
    for entry in load_rules().get('pending', []):
        if all(str(context.get(k,'')) == str(v) for k,v in entry['identity'].items()):
            return entry['note']
    return ''
