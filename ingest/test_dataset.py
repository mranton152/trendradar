"""Датасет: извлекаем реальные строки, без генерации отсутствующих запросов."""
import zipfile

from ingest.dataset import read_queries


def test_read_inline_queries(tmp_path):
    path = tmp_path / 'dataset.xlsx'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('xl/worksheets/sheet1.xml', '''
        <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
        <sheetData><row r="3"><c r="B3"><v>1</v></c>
        <c r="C3" t="inlineStr"><is><t>Роботизированные сенсоры</t></is></c>
        </row></sheetData></worksheet>''')
    assert read_queries(path) == [(1, 'Роботизированные сенсоры')]
