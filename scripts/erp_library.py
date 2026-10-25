"""Read the registered ERP library; a normal audit never updates it."""
import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / 'config/erp_library.json'


def resolve_erp_inputs(combo=None, single=None, manifest_path=None):
    if bool(combo) != bool(single):
        raise ValueError('如指定本次ERP文件，必须同时提供组合装和单品；都省略则使用固定标准库。')
    if combo and single:
        paths = [Path(combo).resolve(), Path(single).resolve()]
        return str(paths[0]), str(paths[1]), {'mode':'one_run_override', 'version':None,
            'sources':[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]}
    manifest_path = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    root = manifest_path.resolve().parent.parent
    paths = []
    for key in ('combo','single'):
        source = manifest['erp'][key]
        path = (root/source['path']).resolve()
        if not path.is_file():
            raise FileNotFoundError(f'固定ERP标准库文件缺失：{path}')
        if hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
            raise ValueError(f'固定ERP文件与登记版本不一致：{path.name}；请在明确通知更新后登记新版本，不自动更换标准库。')
        paths.append(str(path))
    return paths[0], paths[1], {'mode':'registered_library','version':manifest['version'],
        'manifest':str(manifest_path.resolve()),'sources':manifest['erp']}
