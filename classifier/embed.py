"""Эмбеддинги запросов для классификатора этапа 1.

    python -m classifier.embed

Кодируем ТОЛЬКО `query_en` — короткий английский поисковый запрос. Поле `label`
брать нельзя: слабые сигналы заказчика подписаны длинными фразами со скобками,
зрелые технологии — короткими названиями, и одна длина строки угадывает класс
на 97%. Модель на эмбеддингах `label` выучила бы стиль разметки, а не новизну.
По `query_en` те же стилистические признаки дают 59% — около монетки.

Результат кладётся рядом со снимком признаков и коммитится: 196×1024 float32
меньше мегабайта, а обучение и CI после этого не требуют torch и сети.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

МОДЕЛЬ = "intfloat/multilingual-e5-large"
СНИМОК = Path("classifier/features_v1.json")
ВЕКТОРЫ = Path("classifier/embeddings_e5.npy")
ОПИСЬ = Path("classifier/embeddings_e5.json")


def тексты(строки: list[dict]) -> list[str]:
    # e5 обучена с префиксами; для коротких запросов нужен "query: "
    return [f"query: {r['query_en']}" for r in строки]


def подпись(строки: list[dict]) -> str:
    """SHA порядка и содержимого запросов: векторы не должны разъехаться со снимком."""
    ключ = json.dumps([[r["cand_id"], r["query_en"]] for r in строки], ensure_ascii=False)
    return hashlib.sha256(ключ.encode()).hexdigest()


def загрузить(строки: list[dict]) -> np.ndarray:
    """Векторы в порядке строк снимка. Падает, если снимок менялся после расчёта."""
    опись = json.loads(ОПИСЬ.read_text(encoding="utf-8"))
    if опись["sha"] != подпись(строки):
        raise SystemExit(f"{ВЕКТОРЫ} посчитан для другого снимка — python -m classifier.embed")
    return np.load(ВЕКТОРЫ)


def загрузить_если_есть(строки: list[dict]) -> np.ndarray | None:
    """Как `загрузить`, но без падения: нет файла или снимок другой - None."""
    if not (ВЕКТОРЫ.exists() and ОПИСЬ.exists()):
        return None
    опись = json.loads(ОПИСЬ.read_text(encoding="utf-8"))
    return np.load(ВЕКТОРЫ) if опись["sha"] == подпись(строки) else None


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--batch", type=int, default=32)
    args = ap.parse_args(argv)

    from sentence_transformers import SentenceTransformer

    строки = json.loads(СНИМОК.read_text(encoding="utf-8"))
    модель = SentenceTransformer(МОДЕЛЬ, device="cpu")
    X = модель.encode(тексты(строки), batch_size=args.batch, normalize_embeddings=True,
                      show_progress_bar=True).astype(np.float32)
    np.save(ВЕКТОРЫ, X)
    ОПИСЬ.write_text(json.dumps({"model": МОДЕЛЬ, "field": "query_en", "prefix": "query: ",
                                 "n": len(строки), "dim": int(X.shape[1]),
                                 "sha": подпись(строки)}, indent=1), encoding="utf-8")
    print(f"{ВЕКТОРЫ}: {X.shape}")


if __name__ == "__main__":
    main()
