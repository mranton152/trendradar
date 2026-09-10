"""Документные e5-эмбеддинги с атомарной контрольной точкой."""
import hashlib
import json
import time
from pathlib import Path

import numpy as np

MODEL = "intfloat/multilingual-e5-large"
REVISION = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"


def atomic_json(path, payload):
    path = Path(path)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_encoder(device="cuda", cache_folder=None):
    import torch
    from sentence_transformers import SentenceTransformer

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA недоступна; установите CUDA-сборку PyTorch")
    torch.manual_seed(42)
    model = SentenceTransformer(MODEL, revision=REVISION, device=device,
                                cache_folder=cache_folder, trust_remote_code=False)
    model.max_seq_length = 512
    return model


def encode_resumable(rows, output, corpus_hash, encoder=None, batch_size=64,
                     device="cuda", cache_folder=None):
    if not rows or batch_size < 1:
        raise ValueError("Нужен непустой корпус и положительный batch_size")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    state_file = output / "document_embeddings.json"
    array_file = output / "document_embeddings.npy"
    order_hash = hashlib.sha256("\n".join(r["doc_id"] for r in rows).encode()).hexdigest()
    config = {"corpus_sha256": corpus_hash, "order_sha256": order_hash,
              "model": MODEL, "revision": REVISION, "n_docs": len(rows), "dimension": 1024}
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        if any(state.get(k) != v for k, v in config.items()):
            raise ValueError("Изменён корпус или модель; используйте другой каталог кэша")
        array = np.load(array_file, mmap_mode="r+")
        if array.shape != (len(rows), 1024) or array.dtype != np.float32:
            raise ValueError("Повреждён массив документных эмбеддингов")
    else:
        if array_file.exists():
            raise ValueError("Массив без checkpoint; используйте новый каталог кэша")
        array = np.lib.format.open_memmap(array_file, mode="w+", dtype=np.float32,
                                         shape=(len(rows), 1024))
        state = {**config, "completed": 0, "encoding_seconds": 0.0, "device": device}
        atomic_json(state_file, state)
    if not 0 <= state["completed"] <= len(rows):
        raise ValueError("Некорректная позиция checkpoint")
    while state["completed"] < len(rows):
        if encoder is None:
            encoder = load_encoder(device, cache_folder)
        begin = state["completed"]
        end = min(begin + batch_size, len(rows))
        texts = ["passage: " + r["title"] + ". " + (r.get("abstract") or "")
                 for r in rows[begin:end]]
        started = time.perf_counter()
        try:
            vectors = encoder.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                                     convert_to_numpy=True, show_progress_bar=False)
        except RuntimeError as error:
            if "out of memory" not in str(error).lower() or batch_size == 1:
                raise
            batch_size = max(1, batch_size // 2)
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            continue
        vectors = np.asarray(vectors, dtype=np.float32)
        if vectors.shape != (end - begin, 1024):
            raise ValueError("Модель должна возвращать размерность 1024")
        norms = np.linalg.norm(vectors, axis=1)
        if not np.isfinite(vectors).all() or np.any(norms <= 0):
            raise ValueError("Модель вернула нулевые/нечисловые векторы")
        array[begin:end] = vectors / norms[:, None]
        array.flush()
        state.update(completed=end, batch_size=batch_size,
                     encoding_seconds=state["encoding_seconds"] + time.perf_counter() - started)
        state["documents_per_second"] = end / max(state["encoding_seconds"], 1e-9)
        atomic_json(state_file, state)
        print(f"embeddings: {end}/{len(rows)}", flush=True)
    return array, state
