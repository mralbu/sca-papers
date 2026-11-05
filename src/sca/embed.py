"""Stage: document embeddings (local model, MPS/CUDA/CPU).

Per paper the embedded text is title + abstract + the first ~500 words of the
introduction (or of the body when there is no introduction heading), cleaned
of markdown, math, tables and images. Papers with no usable text (e.g. the
unreadable SCA2014-051) are skipped.

Output per model in ``data/embeddings/<model>/``: ``vectors.npy`` (float32,
L2-normalised, one row per paper), ``ids.json`` (row order) and
``hashes.json`` (sha of the embedded text). Re-runs only embed papers whose
text changed.

``evaluate`` compares models without labels, using signals the embeddings
never see: how similar the reference lists of each paper's nearest
neighbours are (bibliographic coupling, TF-IDF over reference strings), and
how often neighbours share an author surname.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sca import cache, metadata, paths

INTRO_WORDS = 500
BATCH_SIZE = 16


@dataclass(frozen=True)
class Model:
    name: str
    hf_id: str
    prefix: str = ""  # task prefix some models expect for documents
    max_seq_length: int = 1024


# nomic-embed was a candidate but needs trust_remote_code (runs code from the model
# repo), which this pipeline avoids for untrusted downloads.
MODELS = {
    m.name: m
    for m in [
        Model("bge-m3", "BAAI/bge-m3"),
        # The SPECTER2 base model without its task adapter (adapters need an extra
        # library); title and abstract are what it was trained on.
        Model("specter2", "allenai/specter2_base", max_seq_length=512),
    ]
}
DEFAULT_MODEL = "bge-m3"


# --- text ----------------------------------------------------------------------

_MATH_RE = re.compile(r"\$\$.*?\$\$|\$[^$\n]*\$", re.S)
_INTRO_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s*|[IVX]+\.\s*)?introduction\b", re.I)


def _clean(text: str) -> str:
    return metadata.clean_inline(_MATH_RE.sub(" ", text))


def _body_blocks(blocks: list[metadata.Block]) -> list[str]:
    """Paragraph texts of the introduction, else of everything after the abstract."""
    start = next(
        (i + 1 for i, b in enumerate(blocks) if b.heading and _INTRO_RE.match(b.text)), None
    )
    if start is None:
        end = next((i for i, b in enumerate(blocks) if metadata._is_abstract_label(b)), None)
        start = (end + 2) if end is not None else min(len(blocks), 6)
    out = []
    for b in blocks[start:]:
        if b.heading or b.raw.startswith(("|", "![", "<")):
            continue
        out.append(_clean(b.raw))
    return out


def document_text(meta: dict, md: str) -> str:
    """Title, abstract and the first ~500 words of the introduction."""
    words: list[str] = []
    for para in _body_blocks(metadata.split_blocks(md)):
        words.extend(para.split())
        if len(words) >= INTRO_WORDS:
            break
    parts = [meta.get("title") or "", meta.get("abstract") or "", " ".join(words[:INTRO_WORDS])]
    return "\n\n".join(p for p in parts if p).strip()


def load_texts() -> dict[str, str]:
    records = json.loads(metadata.COMBINED.read_text(encoding="utf-8"))
    texts = {}
    for r in records:
        if r["status"] != "ok":
            continue
        md = paths.MARKDOWN_DIR / r["id"] / f"{r['id']}.md"
        text = document_text(r, md.read_text(encoding="utf-8", errors="replace"))
        if len(text.split()) >= 30:
            texts[r["id"]] = text
    return texts


# --- embedding -------------------------------------------------------------------


def model_dir(name: str) -> Path:
    return paths.EMBEDDINGS_DIR / name


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def load(name: str) -> tuple[list[str], np.ndarray]:
    d = model_dir(name)
    ids = json.loads((d / "ids.json").read_text())
    return ids, np.load(d / "vectors.npy")


def _device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def run(name: str = DEFAULT_MODEL) -> tuple[int, int]:
    """Embed every paper with ``name``; returns (embedded now, total)."""
    model = MODELS[name]
    texts = load_texts()
    d = model_dir(name)
    old: dict[str, np.ndarray] = {}
    old_hashes: dict[str, str] = {}
    if (d / "hashes.json").exists() and (d / "vectors.npy").exists():
        old_hashes = json.loads((d / "hashes.json").read_text())
        ids, vecs = load(name)
        old = dict(zip(ids, vecs, strict=True))
    hashes = {i: _sha(model.prefix + t) for i, t in texts.items()}
    todo = [i for i in texts if old_hashes.get(i) != hashes[i] or i not in old]
    if todo:
        from sentence_transformers import SentenceTransformer

        st = SentenceTransformer(model.hf_id, device=_device())
        st.max_seq_length = model.max_seq_length
        # Longest first keeps padding low within each batch.
        todo.sort(key=lambda i: len(texts[i]), reverse=True)
        new = st.encode(
            [model.prefix + texts[i] for i in todo],
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=True,
            convert_to_numpy=True,
        )
        old.update(zip(todo, new.astype(np.float32), strict=True))
    ids = sorted(texts)
    vectors = np.stack([old[i] for i in ids]).astype(np.float32)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / ".vectors.tmp.npy"
    np.save(tmp, vectors)
    tmp.replace(d / "vectors.npy")
    cache.write_json_atomic(d / "ids.json", ids)
    cache.write_json_atomic(d / "hashes.json", {i: hashes[i] for i in ids})
    return len(todo), len(ids)


# --- evaluation --------------------------------------------------------------------

K = 10
MIN_REFS = 5


def _surnames(authors: list[str]) -> set[str]:
    return {a.split()[-1].lower() for a in authors if a.split()}


def evaluate(names: list[str]) -> str:
    """Compare models on label-free proxies of topical similarity."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    records = {r["id"]: r for r in json.loads(metadata.COMBINED.read_text(encoding="utf-8"))}
    lines = [
        f"neighbours k={K}; refsim: mean TF-IDF cosine of reference lists "
        f"(papers with >= {MIN_REFS} refs); coauthor: share of neighbours with a common "
        "author surname. Random baseline in the last row."
    ]
    lines.append(f"{'model':>10} {'refsim':>8} {'coauthor':>9}")
    baseline = None
    for name in names:
        ids, vecs = load(name)
        with_refs = [i for i in ids if len(records[i]["references"]) >= MIN_REFS]
        tfidf = TfidfVectorizer(sublinear_tf=True, min_df=2, stop_words="english")
        refs = tfidf.fit_transform([" ".join(records[i]["references"]) for i in with_refs])
        ref_row = {i: n for n, i in enumerate(with_refs)}
        sims = vecs @ vecs.T
        np.fill_diagonal(sims, -1)
        nn = np.argsort(-sims, axis=1)[:, :K]
        rng = np.random.default_rng(0)
        rand = np.array([rng.choice(len(ids), K, replace=False) for _ in ids])

        def score(neigh: np.ndarray, ids=ids, ref_row=ref_row, refs=refs) -> tuple[float, float]:
            rs, ca = [], []
            for row, cols in enumerate(neigh):
                me = ids[row]
                mine = _surnames(records[me]["authors"])
                for c in cols:
                    other = ids[c]
                    if me in ref_row and other in ref_row:
                        rs.append((refs[ref_row[me]] @ refs[ref_row[other]].T).toarray()[0, 0])
                    if mine:
                        ca.append(bool(mine & _surnames(records[other]["authors"])))
            return float(np.mean(rs)), float(np.mean(ca))

        r, c = score(nn)
        lines.append(f"{name:>10} {r:>8.3f} {c:>9.3f}")
        if baseline is None:
            baseline = score(rand)
    if baseline:
        lines.append(f"{'random':>10} {baseline[0]:>8.3f} {baseline[1]:>9.3f}")
    return "\n".join(lines) + "\n"
