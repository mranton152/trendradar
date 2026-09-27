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
