"""Кандидаты от LLM: модель только предлагает, решают заголовки корпуса."""
from semantic.live import extract_live
from semantic.llm_terms import _чистый, заголовки_корпуса, предложить, шаблон


class ФейкLLM:
    model, backend = "fake", "fake"

    def __init__(self, ответ=None, сбой=False):
        self.ответ, self.сбой = ответ or {}, сбой

    def json(self, prompt, schema=None):
        if self.сбой:
            raise ConnectionError("нет Ollama")
        return self.ответ


def _row(i, title, source="gnews"):
    return {"doc_id": f"d{i}", "title": title, "source": source, "date": f"2026-09-{i + 1:02d}"}


ROWS = [
    _row(0, "Interchecks raises $50m to accelerate instant payments - FinTech Global"),
    _row(1, "Banks race to launch instant payments in Europe - Reuters"),
    _row(2, "Stablecoin settlement pilot goes live - CoinDesk"),
    _row(3, "Why stablecoin settlement matters for banks - FT"),
    _row(4, "Quarterly fintech funding report - TechCrunch"),
]


def test_выдуманная_технология_не_становится_кандидатом():
    """Модель назвала 'quantum ledger' — в заголовках его нет, кандидата нет."""
    термины, _ = предложить(заголовки_корпуса(ROWS), ФейкLLM(
        {"technologies": ["instant payments", "stablecoin settlement", "quantum ledger"]}))
    cands, links, _ = extract_live(ROWS, "live-x", min_docs=2, extra_terms=термины)
    метки = {c["label"] for c in cands}
    assert {"instant payments", "stablecoin settlement"} <= метки
    assert "quantum ledger" not in метки
    по_id = {c["cand_id"]: c["label"] for c in cands}
    док = {x["doc_id"] for x in links if по_id[x["cand_id"]] == "instant payments"}
    assert док == {"d0", "d1"}


def test_издатель_google_news_не_считается_упоминанием():
    rows = [_row(0, "Chip news - Stablecoin Settlement Weekly"),
            _row(1, "Other news - Stablecoin Settlement Weekly")]
    cands, _, _ = extract_live(rows, "live-x", min_docs=2, extra_terms=["stablecoin settlement"])
    assert not cands


def test_бизнес_хроника_отбрасывается():
    assert _чистый("ai startups") is None
    assert _чистый("pre-seed round") is None
    assert _чистый("Physical AI") == "physical ai"
    assert _чистый("a") is None


def test_отказ_модели_не_роняет_живой_режим():
    термины, аудит = предложить(["x"], ФейкLLM(сбой=True))
    assert термины == [] and аудит["errors"] == ["ConnectionError"]


def test_шаблон_целого_слова_и_множественного_числа():
    assert шаблон("stablecoin").search("New stablecoins launch")
    assert not шаблон("ai chip").search("Mainland ai chipset")


def test_lmstudio_uses_technology_schema_and_records_response(monkeypatch):
    import httpx

    from semantic.llm_terms import create_llm

    monkeypatch.setenv('LLM_BACKEND', 'lmstudio')
    monkeypatch.setenv('LLM_BASE_URL', 'http://localhost:1234')
    monkeypatch.setenv('LLM_MODEL', 'local-test')
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    requests = []

    def post(url, **kwargs):
        requests.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'message': {'content': '{"technologies": ["gene editing"]}'}}]})

    monkeypatch.setattr(httpx, 'post', post)
    terms, audit = предложить(['Gene editing platform', 'Gene editing improves'], create_llm())
    assert terms == ['gene editing']
    payload = requests[0][1]['json']['response_format']
    assert payload['type'] == 'json_schema'
    assert 'technologies' in payload['json_schema']['schema']['properties']
    assert audit['responses'][0]['response'] == {'technologies': ['gene editing']}
    assert 'Gene editing platform' in audit['responses'][0]['prompt']


def test_invalid_technology_payload_is_audited_without_character_candidates():
    terms, audit = предложить(['Gene editing'], ФейкLLM({'technologies': 'gene editing'}))
    assert terms == []
    assert audit['errors'] == ['invalid_technologies_payload']


def test_build_passes_dates_to_recent_headline_selection(tmp_path, monkeypatch):
    import json
    import sys

    import pyarrow as pa
    import pyarrow.parquet as pq
    import pytest

    from semantic import build, llm_terms

    works = tmp_path / 'works.parquet'
    rows = [{**_row(0, 'Old biotechnology headline'), 'date': '2016-01-01'},
            {**_row(1, 'New biotechnology headline'), 'date': '2026-09-27'}]
    for row in rows:
        row.update(abstract=None, domain='bio', year=int(row['date'][:4]))
    pq.write_table(pa.Table.from_pylist(rows), works)
    works.with_name('meta.json').write_text(json.dumps({
        'domain': 'bio', 'n_docs': 2, 'corpus_sha256': build.fingerprint(works)}))

    class Captured(Exception):
        pass

    def capture(headlines, llm):
        assert headlines == ['New biotechnology headline', 'Old biotechnology headline']
        raise Captured

    monkeypatch.setenv('TRENDRADAR_LLM_TERMS', '1')
    monkeypatch.setattr(llm_terms, 'предложить', capture)
    monkeypatch.setattr(llm_terms, 'create_llm', lambda: object())
    monkeypatch.setattr(sys, 'argv', ['build', '--scope', 'live', '--domain', 'bio',
                                    '--works', str(works), '--output', str(tmp_path / 'index'),
                                    '--cache', str(tmp_path / 'cache'), '--as-of', '2026'])
    with pytest.raises(Captured):
        build.main()


def test_термин_модели_в_другом_регистре_не_даёт_повтор_cand_id():
    """Правила нашли «AI agent», модель предложила «ai agent» — один кандидат."""
    rows = [_row(0, "AI agent platform launches - TechCrunch"),
            _row(1, "Banks test AI agent for payments - Reuters"),
            _row(2, "Why every AI agent needs identity - Wired")]
    cands, _, _ = extract_live(rows, "live-x", min_docs=2, extra_terms=["ai agent"])
    ids = [c["cand_id"] for c in cands]
    assert len(ids) == len(set(ids))
    assert sum(c["label"].casefold() == "ai agent" for c in cands) == 1
