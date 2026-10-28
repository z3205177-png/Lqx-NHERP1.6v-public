"""Conservative syntax helpers shared by platform and ERP quantity parsing."""
import re


def packaging_products(text, units):
    atoms = list(re.finditer(rf'(\d+)\s*({units})', text))
    products, issues, used = [], [], set()
    for op in re.finditer(r'[*×x]\s*(\d+)\s*(包|袋|盒)?', text):
        before = [a for a in atoms if a.end() <= op.start()]
        if not before:
            continue
        atom = before[-1]
        gap = text[atom.end():op.start()]
        if re.search(r'型号|批次|编号|货号|尺寸|cm|mm', gap):
            continue
        if len(gap) > 60 or re.search(r'\d|[+＋*×]|送|赠|搭配', gap):
            issues.append('包装倍数对应的基础数量不明确')
            continue
        if atom.start() in used:
            issues.append('连续包装倍数尚未建立对应关系')
            continue
        multiplier = int(op[1])
        if not op[2] and re.match(rf'\s*(?:{units})', text[op.end():]):
            issues.append('包装倍数后带有非包装计数单位，关系需确认')
            continue
        if not 1 <= multiplier <= 100:
            issues.append('包装倍数超出支持范围，需确认')
            continue
        products.append((int(atom[1]) * multiplier, atom[2]))
        used.add(atom.start())
    return products, list(dict.fromkeys(issues))


def without_rates(text):
    return re.sub(r'\d+\s*(?:片|对|只|个)\s*[/／]\s*(?:盒|包|袋)', '', text)


def unresolved_gifts(text, units, families, scalar):
    problems = []
    for gift in re.split(r'送|赠(?:送)?|搭配', text)[1:]:
        gift = re.sub(rf'(?:到手|共|合计|总计)\s*\d+\s*(?:{units})', '', gift)
        gift = re.sub(r'^[\s【\[(（]+|[\s【】\[\]()（）,，;；]+$', '', gift)
        numeric_offer = re.sub(r'同款|更划算|超划算|超值划算|热销[款装]|经济装|划算装|推荐装|量贩装|盒装', '', gift)
        numeric_offer = re.sub(r'[\s【】\[\]()（）{}，,;；]', '', numeric_offer)
        bare_quantity = re.fullmatch(rf'\d+(?:{units})?', numeric_offer)
        if bare_quantity and re.search(rf'\d+\s*(?:{units})',text):
            continue  # the ordinary same-product buy/get quantity expression
        fs = families(gift)
        apparel = re.search(r'护膝|护腰',gift)
        if not fs and not apparel:
            problems.append('赠品品类未明确：' + gift)
        quantity, _ = scalar(gift)
        # Existing buy40/get40 foot-patch wording uses a separately stated total.
        declared_unit = re.search(rf'(?:到手|共|合计|总计)\s*\d+\s*({units})',text)
        unit_from_total = declared_unit and fs and re.match(r'\d+',gift)
        if quantity is None and not unit_from_total and not (apparel and re.search(r'(?i)\b(?:[sml]|x{1,4}l|[2-5]xl)\b',gift)):
            problems.append('赠品数量未明确：' + gift)
    return list(dict.fromkeys(problems))


def additive_quantities(text, scalar, families, variants, units, pair_families):
    """Keep every parallel term; a scalar total never replaces composition."""
    normalized = text
    def recipe(match):
        inner = match[1]
        names = [n for n in ('艾草', '益母草', '生姜') if n in inner]
        prefix = normalized[:match.start()]
        if len(names) >= 2 and re.search(rf'\d+\s*({units})', prefix) and not any(w in inner for w in ('足贴', '鞋垫', '护膝', '护腰')):
            return '(' + '/'.join(names) + ')'
        return match[0]
    normalized = re.sub(r'\(([^()]*)\)', recipe, normalized)
    # A total field belongs to the entire bundle, never the nearest component.
    explicit = [(int(m[1]), m[2]) for m in re.finditer(rf'(?:到手|共|合计|总计|片数[:：])\s*(\d+)\s*({units})', normalized)]
    body = re.sub(rf'(?:到手|共|合计|总计|片数[:：])\s*\d+\s*({units})', '', normalized)
    body = re.sub(rf'(?<=[片对只个盒包袋])加(?=[^+＋]*\d+\s*(?:{units}))', '+', body)
    pieces = re.split(r'[+＋]', body)
    if len(pieces) < 2:
        return None
    ingredients = {n for n in ('艾草', '益母草', '生姜') if n in normalized}
    atoms = re.findall(rf'\d+\s*({units})', body)
    # The already-approved three-in-one policy compares only the stated total.
    if ('三合一' in normalized or len(ingredients) == 3) and (len(atoms) <= 1 or families(normalized) == {'暖贴'}):
        return None
    if not atoms and not explicit and not (sum(bool(families(p)) for p in pieces) >= 2 or re.search('套装|组合装', body)):
        return None
    parts, problems = [], []
    for number, piece in enumerate(pieces):
        quantity, issues = scalar(piece)
        fs = families(piece)
        vs = variants(piece)
        if not fs and len(families(normalized)) == 1:
            # Only inherit an omitted product name, not an unknown named gift.
            remainder = re.sub(rf'\d+\s*(?:{units})|[*×x]\s*\d+', '', piece)
            remainder = re.sub(r'艾草|益母草|生姜|经典|升级|增强|同款|袋装|盒装', '', remainder)
            if not re.search(r'[\w\u4e00-\u9fff]', remainder):
                fs = families(normalized)
        label = next((label for label,words in [('鞋垫',('鞋垫',)),('足贴',('足贴','暖足贴')),
            ('护膝',('护膝',)),('护腰',('护腰',)),('暖膝',('暖膝',)),('暖腰',('暖腰',)),
            ('暖颈',('暖颈',)),('暖手',('暖手','手机宝'))] if any(w in piece for w in words)), '')
        label = label or (next(iter(fs)) if len(fs) == 1 else '/'.join(sorted(fs)) or '未明确品类')
        label = {'发热鞋垫':'鞋垫','暖手用品':'暖手','暖手足宝':'暖手'}.get(label,label)
        traits = sorted(set(vs.get('formula', set())) | set(vs.get('style', set())) |
                        {x for x in ('经典', '升级', '增强') if x in piece})
        key = label + ('(' + '/'.join(traits) + ')' if traits else '')
        optional_count = bool(label in {'护膝', '护腰'} and vs.get('size'))
        if quantity is None and not optional_count:
            problems.append('组成数量未明确：' + piece.strip())
        if len(fs) != 1 and label not in {'护膝', '护腰', '暖膝', '暖腰', '暖颈', '暖手'}:
            problems.append('组成品类未明确：' + piece.strip())
        parts.append({'key': key, 'text': piece, 'qty': quantity, 'families': sorted(fs), 'issues': issues})
        if any('包装倍数' in issue for issue in issues):
            problems.extend(issues)
    comparable = []
    for part in parts:
        qty = part['qty']
        if qty and qty[1] == '对' and set(part['families']) & set(pair_families):
            qty = (qty[0] * 2, '片')
        comparable.append(qty)
    total = None
    if all(comparable) and len({q[1] for q in comparable}) == 1:
        total = (sum(q[0] for q in comparable), comparable[0][1])
    elif all(comparable):
        # Different known products may be compared separately without a total.
        # Repeated instances of one product must not lose an incompatible unit.
        grouped = {}
        for part, qty in zip(parts, comparable):
            grouped.setdefault(part['key'], set()).add(qty[1])
        if any(len(values) > 1 for values in grouped.values()):
            problems.append('同款组成单位不可直接相加，未执行未授权换算')
    if explicit:
        distinct = list(dict.fromkeys(explicit))
        if len(distinct) > 1:
            problems.append('明示总数量相互冲突')
        declared = distinct[0]
        if total and total != declared:
            problems.append('明示总数与组成数量不一致')
        total = declared
    return {'raw': text, 'qty': None if problems else total, 'parsed_total': total, 'parts': parts,
            'issues': list(dict.fromkeys(problems)), 'incomplete': bool(problems), 'additive': True}
