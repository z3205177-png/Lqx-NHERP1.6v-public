"""Agricultural specifications: shared parsing, scoped facts and safe comparison.

All quantities are commercial specifications, never measurements of actual stock.
No head/string-to-weight conversion is inferred.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import unicodedata

from confirmed_mappings import digest

CONFIG = Path(__file__).resolve().parents[1] / 'config/agricultural_confirmations.json'
WEIGHT = re.compile(r'(\d+(?:\.\d+)?)\s*(公斤|千克|市斤|斤|kg|克|g)(?![a-z])', re.I)
NON_FOOD = re.compile(r'暖贴|暖宝宝|热敷|艾灸|眼罩|护膝|护腰|洗发|面膜|精油|纸箱|包装材料|卷材')


def normalized(text):
    return unicodedata.normalize('NFKC', str(text or '')).lower()


def grams(number, unit):
    return float(Decimal(number) * {'公斤':1000, '千克':1000, 'kg':1000,
        '市斤':500, '斤':500, '克':1, 'g':1}[unit.lower()])


def kind(text):
    if NON_FOOD.search(text):
        return ''
    for label, pattern in [('姜蒜组合',r'姜蒜|蒜姜'), ('独头蒜米',r'独头.*(?:蒜米|去皮)'),
        ('独头蒜',r'独头'), ('蒜米',r'蒜米|去皮.*蒜|剥皮.*蒜'),
        ('干蒜',r'干蒜'), ('鲜蒜',r'鲜蒜'), ('生姜',r'生姜|山东.*姜|大姜'),
        ('大蒜',r'大蒜|蒜头|蒜瓣')]:
        if re.search(pattern,text):
            return label
    return ''


def is_agricultural(feature):
    return bool(feature.get('agricultural'))


def _grade(text, product_kind):
    match = re.search(r'(\d+(?:\.\d+)?)(?:\s*[-~至]\s*(\d+(?:\.\d+)?))?\s*(mm|cm)',text)
    if not match:
        return next((g for g in ('中果','大果','果王') if g in text), '')
    factor = 10 if match[3] == 'cm' else 1
    lo = float(match[1])*factor
    hi = float(match[2])*factor if match[2] else lo
    # Confirmed commercial grades for this dry-garlic family, not interval overlap.
    if product_kind in ('干蒜','大蒜'):
        if (lo,hi) in ((45,45),(45,50)): return '中果'
        if (lo,hi) == (50,55): return '大果'
        if (lo,hi) == (60,60): return '果王'
    if product_kind in ('独头蒜','独头蒜米') and (lo,hi) in ((25,25),(25,30)):
        return '独头25-30mm'
    return f'{lo:g}-{hi:g}mm'


def _parse_one(text, product_kind):
    result = {'raw':text,'kind':product_kind,'grade':_grade(text,product_kind),
        'net':None,'gross':None,'pack_g':None,'packs':None,'heads':None,'issues':[]}
    if re.search(r'[*×x]\s*\d+\s*[*×x]',text):
        result['issues'].append('多层包装倍数需确认')
    if re.search(r'[*×x]\s*\d+\s*(?:$|[|;])',text):
        result['issues'].append('未注明包装单位的倍数需确认')
    if (re.search(r'\d+(?:\.\d+)?\s*[-~至]\s*\d+(?:\.\d+)?\s*(?:kg|g|斤|克)',text)
            or (WEIGHT.search(text) and re.search(r'约|左右|上下|±',text))):
        result['issues'].append('重量范围或容差未确认')
    weights = list(WEIGHT.finditer(text))
    rates, totals = [], []
    for m in weights:
        value = grams(m[1],m[2]); tail=text[m.end():]; prefix=text[:m.start()]
        if value<=0: result['issues'].append('重量必须大于零')
        bound = 'min' if re.match(r'\s*\+',tail) else 'exact'
        measurement={'g':value,'bound':bound}
        # A naked trailing plus after a number is a bound, not an additive term.
        if re.search(r'(?:含箱|含(?:外)?包装|带箱|含皮重|毛重)(?:净?重)?\s*[:：]?\s*$',prefix):
            if result['gross'] and result['gross']!=measurement:
                result['issues'].append('含包装重量存在多个声明，需确认')
            result['gross']=measurement
            continue
        product=re.match(r'\s*[*×x]\s*(\d+)\s*(包|袋|桶|兜)',tail)
        if product:
            unit = '包' if product[2] in ('包','袋') else product[2]
            result['packs']={'n':int(product[1]),'unit':unit}
            rates.append(value); totals.append({'g':value*int(product[1]),'bound':bound})
        elif re.search(r'每\s*(?:包|袋|桶|兜)(?:净重)?\s*$',prefix) or re.match(r'\s*[/／]\s*(?:包|袋|桶|兜)',tail):
            rates.append(value)
        else:
            totals.append(measurement)
    pack_atoms=list(re.finditer(r'(\d+)\s*(包|袋|桶|兜|条)(?:装)?',text))
    if pack_atoms:
        declarations={(int(m[1]), '包' if m[2] in ('包','袋') else m[2]) for m in pack_atoms}
        if len(declarations)>1:
            result['issues'].append('包装数量存在多个声明，需确认')
        elif not result['packs']:
            n,unit=next(iter(declarations)); result['packs']={'n':n,'unit':unit}
    heads = re.search(r'(\d+)\s*头',text)
    if heads:
        result['heads']=int(heads[1])
        if '网兜' in text and result['packs'] and result['packs']['unit']=='条':
            result['heads'] *= result['packs']['n']
        elif '网兜' in text and weights and not result['packs']:
            # Five heads describes each string, not the entire multi-jin order.
            result['heads']=None
        elif '5头网兜' in text.replace(' ','') and not result['packs']:
            result['packs']={'n':1,'unit':'条'}
    if rates:
        if len(set(rates))>1: result['issues'].append('每包装量声明不一致')
        result['pack_g']=rates[0]
        if result['packs']:
            totals.append({'g':rates[0]*result['packs']['n'],'bound':'exact'})
        else:
            result['issues'].append('每包装量已知但包装数未知')
    if totals:
        exact={t['g'] for t in totals if t['bound']=='exact'}
        minimum=max((t['g'] for t in totals if t['bound']=='min'),default=0)
        if len(exact)>1 or (exact and next(iter(exact))<minimum):
            result['issues'].append('明示总净重与包装乘积不一致')
        result['net']=next((t for t in totals if t['bound']=='exact'),totals[0])
    return result


@lru_cache(maxsize=20000)
def _parse(text, title, category):
    text,title,category=map(normalized,(text,title,category))
    if NON_FOOD.search(text) or NON_FOOD.search(title):
        return None
    if re.search(r'\d+\s*(?:片|对|只)',text) and not WEIGHT.search(text):
        return None
    # Commercial gift badges occur before the actual SKU: retain the main item.
    badge_gift=bool(re.search(r'[\[【][^\]】]*(?:赠姜|赠生姜)[^\]】]*[\]】]',text))
    clean=re.sub(r'[\[【][^\]】]*(?:赠姜|赠生姜)[^\]】]*[\]】]','',text)
    trailing_badge=bool(re.search(r'(?:爆款)?赠姜(?=$|[|\s])',clean))
    clean=re.sub(r'(?:爆款)?赠姜(?=$|[|\s])','',clean)
    gift_split=re.split(r'送|赠(?:送)?',clean,maxsplit=1)
    main=gift_split[0]
    product_kind=kind(main)
    title_kind=kind(re.split(r'送|赠(?:送)?',title,maxsplit=1)[0])
    category_kind=kind(category)
    if category_kind and category_kind!='大蒜':
        # A real independent shop category resolves title/marketing ambiguity;
        # never derive this field from the code being checked.
        product_kind=category_kind if not product_kind or product_kind in ('大蒜','干蒜','独头蒜') else product_kind
    if not product_kind or product_kind=='大蒜' or (product_kind=='独头蒜' and title_kind=='独头蒜米'):
        product_kind=title_kind or product_kind
    if not product_kind: return None
    result=_parse_one(main,product_kind)
    result['raw']=text; result['parts']=[]
    # Explicit mixed ingredients are parsed individually; a total never replaces them.
    composition=re.sub(r'(\d+(?:\.\d+)?\s*(?:kg|g|斤|克|cm|mm))\s*\+',r'\1',main)
    split=re.split(r'[+＋]',composition)
    if len(split)>1 and all(kind(p) for p in split):
        result['parts']=[_parse_one(p,kind(p)) for p in split]
        result['net']=None
        result['kind']='组成组合'
        result['packs']=None; result['pack_g']=None; result['heads']=None
        result['issues']=[i for i in result['issues'] if i!='明示总净重与包装乘积不一致']
    if product_kind=='姜蒜组合':
        result['issues'].append('姜蒜具体组成及配比待确认')
    result['gift']=None
    if len(gift_split)>1:
        gift=re.split(r'[|【\[]',gift_split[1],maxsplit=1)[0]
        result['gift']=_parse_one(gift,kind(gift) or ('生姜' if '姜' in gift else ''))
        if not result['gift']['kind'] or not result['gift']['net']:
            result['issues'].append('赠品品类或净重待确认')
    elif badge_gift or trailing_badge:
        result['gift']=_parse_one('赠姜','生姜')
        result['issues'].append('赠姜净重及编码对应关系待确认')
    if re.search(r'[+＋]',composition) and not result['parts']:
        # Do not interpret the '+' of a mass/diameter lower bound as composition.
        remainder=re.sub(r'\d+(?:\.\d+)?\s*(?:kg|g|斤|克|cm|mm)\s*\+','',composition)
        if '+' in remainder or '＋' in remainder:
            result['issues'].append('混合组成未完整解析')
    return result


def parse_spec(text, title='', category=''):
    return deepcopy(_parse(str(text),str(title),str(category)))


@lru_cache(maxsize=1)
def load_facts():
    if not CONFIG.exists(): return {'rows':{}}
    data=json.loads(CONFIG.read_text(encoding='utf-8'))
    if data.get('version')!=1: raise ValueError('农产品确认配置版本不支持')
    return data


def row_identity(context):
    return digest([str(context.get(k,'')) for k in ('平台','商品 ID','SKU ID')])


def row_fingerprint(context):
    return digest({k:str(context.get(k,'')) for k in ('平台','商品 ID','SKU ID','商品标题','SKU','农产品店内分类')})


def scoped_fact(feature, by_code):
    context=feature.get('context',{})
    entry=load_facts()['rows'].get(row_identity(context))
    if not entry: return None,''
    if entry['fingerprint']!=row_fingerprint(context):
        return None,'农产品人工确认已失效：平台内容变化，请重新确认'
    for code, hashes in entry['erp_bindings'].items():
        if sorted(r.get('erp_fingerprint','') for r in by_code.get(code,[]))!=sorted(hashes):
            return None,'农产品人工确认已失效：关联ERP记录变化，请重新确认'
    return entry,''


def prepared_spec(feature, by_code):
    spec=deepcopy(feature.get('agricultural'))
    if not spec: return None,None,''
    fact, stale=scoped_fact(feature,by_code)
    if fact:
        if fact.get('pack_g') is not None:
            spec['pack_g']=fact['pack_g']
            if spec['packs']: spec['net']={'g':fact['pack_g']*spec['packs']['n'],'bound':'exact'}
        if fact.get('gift_g') is not None:
            if spec['gift']: spec['gift']['net']={'g':fact['gift_g'],'bound':'exact'}
            spec['issues']=[s for s in spec['issues'] if not s.startswith('赠品品类或净重')]
    return spec,fact,stale


def _mass_conflict(a,b):
    if a['bound']=='exact' and b['bound']=='exact': return a['g']!=b['g']
    if a['bound']=='min' and b['bound']=='exact': return b['g']<a['g']
    if a['bound']=='exact' and b['bound']=='min': return a['g']<b['g']
    return False


def display_quantity(value):
    if isinstance(value,dict):
        if 'n' in value: return f'{value["n"]}{value["unit"]}'
        return ('不少于' if value['bound']=='min' else '')+f'{value["g"]:g}g'
    return f'{value:g}' if isinstance(value,(float,int)) else str(value)


def _comparison_spec(spec):
    """Apply confirmed food policies to a copy; retain original parsed evidence."""
    spec=deepcopy(spec)
    spec['issues']=[s for s in spec['issues'] if not s.startswith(('赠品品类或净重','赠姜净重及编码'))]
    if spec['kind']=='姜蒜组合':
        spec['issues']=[s for s in spec['issues'] if s!='姜蒜具体组成及配比待确认']
        if spec['packs'] and spec['packs']['unit']=='兜':
            spec['packs']['unit']='包'
        # This per-bag standard is confined to ginger/garlic combinations.
        if spec['packs'] and spec['packs']['unit']=='包':
            if spec['pack_g'] is None:
                spec['pack_g']=250
            if not spec['net'] and not spec['gross']:
                spec['net']={'g':spec['pack_g']*spec['packs']['n'],'bound':'exact'}
    return spec


def compare_specs(a,b,*,allow_missing_erp_weight=False,policy_notes=None):
    """Return explicit conflicts and incomplete evidence separately."""
    a,b=_comparison_spec(a),_comparison_spec(b)
    notes=policy_notes if policy_notes is not None else []
    conflicts=[]; issues=[*a['issues'],*b['issues']]
    ak,bk=a['kind'],b['kind']
    if ak==bk=='姜蒜组合':
        for spec in (a,b):
            ratios=re.findall(r'(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)',spec['raw'])
            if any(Decimal(x)*4!=Decimal(y)*6 or Decimal(x)<=0 or Decimal(y)<=0 for x,y in ratios):
                conflicts.append('姜蒜配比与已确认口径不符：应为姜6:蒜4（重量比）')
            if spec['pack_g'] is not None and spec['pack_g']!=250:
                conflicts.append('姜蒜每袋净重与已确认250g不符')
            if spec['packs'] and spec['packs']['unit']=='包' and spec['net']:
                expected={'g':250*spec['packs']['n'],'bound':'exact'}
                if _mass_conflict(spec['net'],expected):
                    conflicts.append('姜蒜明示总净重与250g/袋乘积不一致')
        notes.append('姜蒜组合按250g/袋、兜=袋、姜蒜重量比6:4核对总重量和总袋数')
    if ak!=bk:
        if '大蒜' in (ak,bk) and {ak,bk}<={'大蒜','干蒜','鲜蒜'}:
            pass  # No explicit fresh/dried contradiction; quantity is still checked.
        else: conflicts.append(f'农产品品种/形态不一致：平台={ak}，ERP={bk}')
    if a['grade'] and b['grade'] and a['grade']!=b['grade']:
        conflicts.append(f'果径档位不一致：平台={a["grade"]}，ERP={b["grade"]}')
    elif a['grade'] and not b['grade'] and not (ak==bk and ak in ('蒜米','独头蒜米')):
        issues.append('ERP果径档位未明确')
    elif a['grade'] and not b['grade']:
        notes.append('蒜米类ERP未标果径，已按品类、重量及包装数核对')
    for key,label in [('packs','包装数量/形式'),('heads','头数'),('pack_g','每包净重')]:
        if a[key] is not None and b[key] is not None and a[key]!=b[key]:
            if key=='packs' and {a[key]['unit'],b[key]['unit']}=={'兜','包'} and a[key]['n']==b[key]['n']:
                issues.append('兜与包的包装对应关系待确认')
            else:
                unit='g' if key=='pack_g' else ('头' if key=='heads' else '')
                conflicts.append(f'{label}不一致：平台{display_quantity(a[key])}{unit}，ERP{display_quantity(b[key])}{unit}')
        elif a[key] is not None and b[key] is None:
            issues.append(f'ERP{label}未明确，不能由重量反推')
    count_only=not a['net'] and not a['gross'] and bool(a['heads'] or (a['packs'] and a['packs']['unit']=='条'))
    if a['net'] and b['net']:
        if _mass_conflict(a['net'],b['net']):
            conflicts.append(f'商品净重不一致：平台{display_quantity(a["net"])}，ERP{display_quantity(b["net"])}')
        elif b['net']['bound']=='min':
            issues.append('ERP仅给出重量下限，不能据此认定净重相同')
    elif a['net'] or b['net']:
        if count_only:
            notes.append('按头/条销售，未核重量')
        elif allow_missing_erp_weight and a['net'] and not b['net']:
            notes.append('本SKU已人工确认按件数和果径核对，重量未核')
        elif not a['gross']:
            issues.append('双方商品净重依据不足，需人工核重')
    if a['gross']:
        if not b['net'] or b['net']['bound']!='exact':
            issues.append('含包装重量缺少ERP确定净重，需人工核重')
        else:
            gross,net=a['gross'],Decimal(str(b['net']['g']))
            gross_g=Decimal(str(gross['g']))
            difference=(max(Decimal(0),gross_g-net) if gross['bound']=='min' else abs(gross_g-net))
            # One tolerance on the order total, never multiplied by package count.
            if difference>50 or difference>net*Decimal('0.1'):
                conflicts.append('含包装总重与ERP净重超出容差：整单差值须同时≤50g且≤ERP净重的10%')
            else:
                notes.append('含包装重量按整单总重核对（差值≤50g且≤ERP净重10%，+保留下限含义）')
    if count_only:
        notes.append('按头/条销售，未核重量')
    elif not a['net'] and not a['gross'] and a['packs']:
        issues.append('按包装销售的净重依据不足，需人工核重')
    # Gifts remain in parsed evidence and ERP total/main-weight reconciliation,
    # but do not participate in the commercial main-product comparison.
    x,y=a.get('parts',[]),b.get('parts',[])
    if bool(x)!=bool(y) or len(x)!=len(y):
        issues.append('双方组成明细不完整')
    elif x:
        xm={p['kind']:p for p in x}; ym={p['kind']:p for p in y}
        if len(xm)!=len(x) or len(ym)!=len(y):
            issues.append('重复部件组成需确认')
        elif xm.keys()!=ym.keys(): conflicts.append('组合部件品种不一致')
        else:
            for k in xm:
                c,i=compare_specs({**xm[k],'gift':None,'parts':[]},{**ym[k],'gift':None,'parts':[]})
                conflicts.extend(k+s for s in c); issues.extend(k+s for s in i)
    if not any((a['net'],a['gross'],a['packs'],a['heads'],a.get('parts'))):
        issues.append('平台缺少可核对的数量或重量规格')
    return list(dict.fromkeys(conflicts)),list(dict.fromkeys(issues))


def erp_spec(record):
    spec=deepcopy(record['features'].get('agricultural'))
    if not spec: return None
    field=record.get('net_weight_kg','')
    if field:
        try:
            value=float(Decimal(str(field))*1000)
            if not math.isfinite(value) or value<=0: raise InvalidOperation
            declared=spec['net']
            if spec.get('gift'):
                gift=spec['gift']['net']
                if declared and gift:
                    declared={'g':declared['g']+gift['g'],'bound':'exact'}
                else:
                    if gift and value>gift['g'] and not spec.get('parts'):
                        spec['net']={'g':value-gift['g'],'bound':'exact'}
                        spec['net_basis']='ERP组合总净重减去明确赠品净重'
                        declared={'g':value,'bound':'exact'}
                    else:
                        spec['issues'].append('组合重量字段不能反推主品或赠品净重')
                        declared=None
            if declared and _mass_conflict(declared,{'g':value,'bound':'exact'}):
                spec['issues'].append('ERP名称净重与重量字段不一致')
            elif not spec['net'] and not spec.get('gift') and not spec.get('parts'):
                spec['net']={'g':value,'bound':'exact'}
        except (InvalidOperation,ValueError):
            spec['issues'].append('ERP重量字段无效')
    return spec


def audit(feature, code, by_code):
    a,fact,stale=prepared_spec(feature,by_code)
    current=by_code.get(code,[])
    if not a and code and current:
        _,stale=scoped_fact(feature,by_code)
        if stale:
            return {'核验状态':'待人工确认','核验说明':stale,'匹配依据':stale,'冲突项目':'',
                '判定路径':'农产品规格核对；解析待确认','农产品解析JSON':json.dumps({'stale':stale},ensure_ascii=False)}
    if not a or not current or not code: return None
    conflicts=[]; issues=[stale] if stale else []
    parsed=[]; policy_notes=[]
    for r in current:
        b=erp_spec(r); parsed.append(b)
        if not b: issues.append('当前ERP不是可比较的食用农产品规格'); continue
        local_weight_exception=bool(fact and fact.get('allow_missing_erp_weight') and code==fact['current_code'])
        c,i=compare_specs(a,b,allow_missing_erp_weight=local_weight_exception,policy_notes=policy_notes)
        conflicts.extend(c); issues.extend(i)
    if len({json.dumps(b,sort_keys=True,ensure_ascii=False) for b in parsed})>1:
        issues.append('ERP同码存在不同农产品规格')
    if fact and fact.get('relation_confirmed') and code==fact['current_code']:
        # Only the exact five human-reviewed string SKUs; preserve all unrelated issues.
        issues=[s for s in issues if not s.startswith(('ERP包装数量/形式未明确','ERP头数未明确','双方商品净重依据不足','按头/条/包装销售','干蒜/鲜蒜品种信息不足'))]
    if fact and fact.get('pending'):
        issues.extend(fact['pending'])
    if issues:
        # Reliable explicit conflicts survive ordinary uncertainty. User-deferred
        # relations and contradictory ERP data remain pending without hiding evidence.
        state='待人工确认'
        if conflicts and not stale and not (fact and fact.get('pending')) and not any('ERP名称净重与重量字段' in s or 'ERP同码' in s for s in issues):
            state='异常（商品/规格不一致）'
    else: state='异常（商品/规格不一致）' if conflicts else '核对通过'
    if fact and fact.get('target_code') and code!=fact['target_code']:
        conflicts.append('用户已确认本SKU应对应编码：'+fact['target_code'])
        state='异常（商品/规格不一致）'
    reasons=list(dict.fromkeys([*conflicts,*issues]))
    weight_unchecked=not (fact and fact.get('relation_confirmed')) and any('未核重量' in s or '重量未核' in s for s in policy_notes)
    note='；'.join(reasons) or ('农产品品种及明示数量已核对' if weight_unchecked else '农产品品种、明示数量及同口径净重已核对')
    if not (fact and fact.get('relation_confirmed')):
        note+=''.join('；'+s for s in dict.fromkeys(policy_notes))
    if any('核重' in s or '重量' in s or '净重' in s for s in issues) and '需人工核重' not in note:
        note+='；需人工核重'
    return {'核验状态':state,'核验说明':note,'匹配依据':'农产品结构化规格核对'+('；用户局部确认有效' if fact else ''),
        '冲突项目':'；'.join(conflicts),'规格问题':'；'.join(reasons),'判定路径':'农产品规格核对；解析待确认' if state=='待人工确认' else '农产品规格核对',
        '农产品解析JSON':json.dumps({'platform':a,'erp':parsed,'conflicts':conflicts,'issues':issues,'scoped_fact':fact,'stale':stale},ensure_ascii=False)}


def suggestions(feature,result,records,by_code):
    output={k:'' for k in ('推测商家编码','推测ERP商品名称','推测依据','仍需确认的问题','其他候选编码','其他候选ERP记录','推测ERP来源')}
    output.update({'候选明细JSON':'[]','推测候选编码数':0})
    if result['核验状态']=='核对通过': return output
    a,fact,stale=prepared_spec(feature,by_code)
    if not a or stale or (fact and fact.get('pending')): return output
    candidates=[]
    for r in records:
        if len(by_code.get(r['code'],[]))!=1: continue
        b=erp_spec(r)
        if not b: continue
        c,i=compare_specs(a,b)
        confirmed=bool(fact and fact.get('target_code')==r['code'])
        if c or i or (fact and fact.get('target_code') and not confirmed): continue
        candidates.append({'code':r['code'],'name':r['name'],'source':r['source'],'source_row':r.get('source_row',''),
            'evidence':['本SKU人工确认且ERP指纹有效' if confirmed else '品种、包装组成、果径和同口径重量均可比且未见冲突']})
    candidates.sort(key=lambda r:(r['code'],r['source']))
    output['候选明细JSON']=json.dumps(candidates,ensure_ascii=False)
    output['推测候选编码数']=len(candidates)
    if len(candidates)==1:
        r=candidates[0]
        output.update({'推测商家编码':r['code'],'推测ERP商品名称':r['name'],'推测ERP来源':r['source'], '推测依据':r['evidence'][0]})
    elif candidates:
        output.update({'其他候选编码':'\n'.join(r['code'] for r in candidates),'其他候选ERP记录':'\n'.join(r['code']+'｜'+r['name'] for r in candidates),'仍需确认的问题':'存在多个同规格候选，需确认'})
    return output
