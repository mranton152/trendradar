"""Контракт локальных документных эмбеддингов."""
import numpy as np
import pytest

from semantic.embed import encode_resumable


class Encoder:
    def encode(self, texts, **kwargs):
        assert all(t.startswith("passage: ") for t in texts)
        result = np.zeros((len(texts), 1024), dtype=np.float32)
        result[:, 0] = 1
        return result


def test_resume_checks_corpus_and_does_not_reencode(tmp_path):
    rows = [{"doc_id": "W1", "title": "quantum", "abstract": None}]
    first, meta = encode_resumable(rows, tmp_path, "hash-one", Encoder(), batch_size=2)
    assert first.shape == (1, 1024) and meta["completed"] == 1

    class Fail:
        def encode(self, *args, **kwargs):
            raise AssertionError("Завершённый кэш не должен перекодироваться")

    second, _ = encode_resumable(rows, tmp_path, "hash-one", Fail(), batch_size=2)
    np.testing.assert_array_equal(first, second)
    with pytest.raises(ValueError, match="корпус"):
        encode_resumable(rows, tmp_path, "hash-two", Fail(), batch_size=2)


def test_bad_dimension_rejected(tmp_path):
    class Wrong:
        def encode(self, texts, **kwargs):
            return np.ones((len(texts), 768), dtype=np.float32)

    with pytest.raises(ValueError, match="1024"):
        encode_resumable([{"title": "x", "abstract": "y", "doc_id": "W1"}],
                         tmp_path, "one", Wrong())


def test_interrupted_batch_resumes_without_reencoding_finished_rows(tmp_path):
    rows = [{"doc_id": f"W{i}", "title": str(i), "abstract": None} for i in range(2)]

    class Interrupted(Encoder):
        def encode(self, texts, **kwargs):
            if texts == ["passage: 1. "]:
                raise RuntimeError("interrupted")
            return super().encode(texts, **kwargs)

    with pytest.raises(RuntimeError, match="interrupted"):
        encode_resumable(rows, tmp_path, "same", Interrupted(), batch_size=1)

    class Resume(Encoder):
        def encode(self, texts, **kwargs):
            assert texts == ["passage: 1. "]
            return super().encode(texts, **kwargs)

    array, state = encode_resumable(rows, tmp_path, "same", Resume(), batch_size=1)
    assert state["completed"] == 2
    np.testing.assert_allclose(np.linalg.norm(array, axis=1), [1, 1])
