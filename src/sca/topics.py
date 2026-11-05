"""Stage: 2D map and topics from the embeddings (BERTopic-style, no LLM).

- UMAP (cosine) to 2D for the map, and to ``CLUSTER_DIMS`` dimensions for
  clustering; both with a fixed seed so a re-run on the same inputs is stable.
- HDBSCAN on the clustering projection. Outliers keep ``outlier: true`` but are
  assigned to the nearest cluster centroid, so every paper has a topic filter.
- c-TF-IDF over each topic's titles + abstracts gives keyword labels.
- ``topics.yaml`` (repo root, committed) holds hand overrides applied last:
  ``merge`` lists of topic ids to fold into the first id, and ``rename``
  ``{id: "Name"}``. Topic ids are only stable while the inputs are unchanged,
  so check the printed table after the corpus or the embeddings change.

Output: ``data/topics/topics.json`` with the topics and per-paper x, y, topic.
"""

import json
from pathlib import Path

import numpy as np

from sca import cache, embed, metadata, paths

OUTPUT = paths.TOPICS_DIR / "topics.json"
OVERRIDES = paths.ROOT / "topics.yaml"

SEED = 42
CLUSTER_DIMS = 10
MIN_CLUSTER_SIZE = 20
MIN_SAMPLES = 5
N_KEYWORDS = 10

# Words common to nearly every SCA paper; they say nothing about a topic.
DOMAIN_STOPWORDS = {
    "paper", "study", "studies", "results", "result", "used", "using", "use", "based",
    "method", "methods", "data", "measurements", "measured", "measurement", "analysis",
    "core", "cores", "sample", "samples", "work", "presented", "present", "new", "different",
    "obtained", "shown", "shows", "show", "also", "however", "case", "cases", "test",
    "tests", "approach", "laboratory", "experimental", "experiments", "experiment",
    "properties", "property", "rock", "rocks", "reservoir", "reservoirs", "values", "value",
    "high", "low", "large", "small", "important", "effect", "effects", "conditions",
    "number", "order", "well", "various", "fig", "figure", "table", "et", "al",
}  # fmt: skip


def _umap(vectors: np.ndarray, dims: int, min_dist: float) -> np.ndarray:
    import umap

    reducer = umap.UMAP(
        n_components=dims, n_neighbors=15, min_dist=min_dist, metric="cosine", random_state=SEED
    )
    return reducer.fit_transform(vectors)


def cluster(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(labels with outliers reassigned to the nearest centroid, outlier mask)."""
    from sklearn.cluster import HDBSCAN

    labels = HDBSCAN(min_cluster_size=MIN_CLUSTER_SIZE, min_samples=MIN_SAMPLES).fit_predict(points)
    outlier = labels < 0
    ids = sorted(set(labels[~outlier]))
    if ids and outlier.any():
        centroids = np.stack([points[labels == c].mean(axis=0) for c in ids])
        dist = ((points[outlier, None, :] - centroids[None]) ** 2).sum(-1)
        labels = labels.copy()
        labels[outlier] = np.array(ids)[dist.argmin(axis=1)]
    return labels, outlier


def ctfidf_keywords(docs: list[str], labels: np.ndarray, n: int = N_KEYWORDS) -> dict[int, list]:
    """Top c-TF-IDF terms per class: tf within the class x log(1 + A / f_term)."""
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer

    classes = sorted(set(labels))
    joined = [" ".join(d for d, lab in zip(docs, labels, strict=True) if lab == c) for c in classes]
    vec = CountVectorizer(
        ngram_range=(1, 2),
        stop_words=sorted(ENGLISH_STOP_WORDS | DOMAIN_STOPWORDS),
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9\-]+\b",
    )
    counts = vec.fit_transform(joined).toarray().astype(float)
    # Drop terms seen only once in the whole corpus (typos, OCR noise). Not min_df:
    # that counts topics, and would drop exactly the terms unique to one topic.
    counts[:, counts.sum(axis=0) < 2] = 0
    tf = counts / np.maximum(counts.sum(axis=1, keepdims=True), 1)
    avg_words = counts.sum() / len(classes)
    idf = np.log(1 + avg_words / np.maximum(counts.sum(axis=0), 1))
    scores = tf * idf
    terms = vec.get_feature_names_out()
    out = {}
    for row, c in enumerate(classes):
        top = np.argsort(-scores[row])
        picked: list[str] = []
        for t in top:
            term = terms[t]
            # A bigram replaces a picked unigram it contains ("relative" ->
            # "relative permeability"); a unigram inside a picked bigram is skipped.
            inside = [k for k, p in enumerate(picked) if p in term.split()]
            if inside:
                picked[inside[0]] = term
                picked = [p for k, p in enumerate(picked) if k not in inside[1:]]
                continue
            if any(term in p.split() for p in picked):
                continue
            picked.append(term)
            if len(picked) == n:
                break
        out[int(c)] = picked
    return out


def load_overrides(path: Path = OVERRIDES) -> dict:
    if not path.exists():
        return {}
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "merge": [[int(i) for i in group] for group in data.get("merge") or []],
        "rename": {int(k): str(v) for k, v in (data.get("rename") or {}).items()},
    }


def apply_merges(labels: np.ndarray, merges: list[list[int]]) -> np.ndarray:
    labels = labels.copy()
    for group in merges:
        for other in group[1:]:
            labels[labels == other] = group[0]
    return labels


def _doc(r: dict) -> str:
    return f"{r.get('title') or ''}. {r.get('abstract') or ''}"


def run(model: str = embed.DEFAULT_MODEL, force: bool = False) -> dict:
    vectors_path = embed.model_dir(model) / "vectors.npy"
    inputs = [vectors_path, metadata.COMBINED] + ([OVERRIDES] if OVERRIDES.exists() else [])
    if not force and cache.is_fresh(OUTPUT, *inputs):
        data = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if data.get("model") == model:
            return data
    ids, vectors = embed.load(model)
    records = {r["id"]: r for r in json.loads(metadata.COMBINED.read_text(encoding="utf-8"))}
    xy = _umap(vectors, 2, min_dist=0.1)
    labels, outlier = cluster(_umap(vectors, CLUSTER_DIMS, min_dist=0.0))
    overrides = load_overrides()
    labels = apply_merges(labels, overrides.get("merge", []))
    keywords = ctfidf_keywords([_doc(records[i]) for i in ids], labels)
    rename = overrides.get("rename", {})
    # Normalise the map to [0, 1] so the site does not depend on UMAP's scale.
    xy = (xy - xy.min(axis=0)) / np.maximum(xy.max(axis=0) - xy.min(axis=0), 1e-9)
    topics = []
    for c in sorted(keywords):
        members = labels == c
        topics.append(
            {
                "id": c,
                "label": rename.get(c) or " / ".join(keywords[c][:3]),
                "keywords": keywords[c],
                "size": int(members.sum()),
                "x": round(float(xy[members, 0].mean()), 4),
                "y": round(float(xy[members, 1].mean()), 4),
            }
        )
    data = {
        "model": model,
        "topics": topics,
        "papers": {
            i: {
                "x": round(float(xy[n, 0]), 4),
                "y": round(float(xy[n, 1]), 4),
                "topic": int(labels[n]),
                "outlier": bool(outlier[n]),
            }
            for n, i in enumerate(ids)
        },
    }
    cache.write_json_atomic(OUTPUT, data)
    return data


def table(data: dict) -> str:
    rows = [f"{'id':>3} {'size':>5}  label  [keywords]"]
    for t in sorted(data["topics"], key=lambda t: -t["size"]):
        rows.append(f"{t['id']:>3} {t['size']:>5}  {t['label']}  [{', '.join(t['keywords'][3:8])}]")
    n_out = sum(p["outlier"] for p in data["papers"].values())
    rows.append(f"{len(data['topics'])} topics, {len(data['papers'])} papers, {n_out} outliers")
    return "\n".join(rows) + "\n"
