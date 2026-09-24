"""Последовательный возобновляемый сбор 100 запросов настоящего xlsx."""
import argparse
import asyncio
import hashlib
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from ingest.live import run, validate_phrases


def read_queries(path):
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as archive:
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings = [''.join(node.itertext()) for node in root.findall('s:si', ns)]
        root = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        queries = []
        for row in root.findall('.//s:row', ns):
            cells = {}
            for cell in row.findall('s:c', ns):
                column = ''.join(c for c in cell.attrib['r'] if c.isalpha())
                value = cell.findtext('s:v', default='', namespaces=ns)
                if cell.get('t') == 's':
                    value = strings[int(value)]
                elif cell.get('t') == 'inlineStr':
                    value = ''.join(cell.find('s:is', ns).itertext())
                cells[column] = value
            if cells.get('B', '').isdigit() and cells.get('C', '').strip():
                queries.append((int(cells['B']), cells['C'].strip()))
    return queries


async def sweep(xlsx, output, cache, budget):
    queries = read_queries(xlsx)
    if len(queries) != 100 or len({i for i, _ in queries}) != 100:
        raise ValueError('Ожидается 100 уникальных строк датасета')
    output.mkdir(parents=True, exist_ok=True)
    provenance = {'xlsx_sha256': hashlib.sha256(xlsx.read_bytes()).hexdigest(),
                  'queries': queries}
    source = output / 'source.json'
    encoded = json.dumps(provenance, ensure_ascii=False, indent=2)
    if source.exists() and json.loads(source.read_text(encoding='utf-8')) != json.loads(encoded):
        raise ValueError('Датасет изменился; нужен отдельный каталог результата')
    source.write_text(encoded, encoding='utf-8')
    for index, query in queries:
        target = output / f'{index:03d}'
        if (target / 'meta.json').exists() and (target / 'works.parquet').exists():
            meta = json.loads((target / 'meta.json').read_text(encoding='utf-8'))
            if meta.get('translation', {}).get('status') != 'complete':
                raise ValueError(f'Строка {index} без перевода; требуется проверка')
            validate_phrases(meta['translation'].get('response', {}))
            print(f'{index}/100: существующий результат, пропуск', flush=True)
            continue
        if target.exists():
            raise ValueError(f'Незавершённый каталог {index}: требуется проверка')
        meta = await run(query, target, budget=budget, cache=cache)
        print(f'{index}/100: {meta["n_docs"]} документов, {meta["status"]}', flush=True)
        if meta['translation']['status'] != 'complete':
            raise RuntimeError('Перевод недоступен; sweep остановлен, результат сохранён')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xlsx', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=Path('data/dataset'))
    parser.add_argument('--cache', type=Path, default=Path('data/dataset-cache'))
    parser.add_argument('--budget', type=float, default=180)
    args = parser.parse_args()
    asyncio.run(sweep(args.xlsx, args.output, args.cache, args.budget))


if __name__ == '__main__':
    main()
