"""Stage: in-corpus citation graph and importance scores.

Each reference string from the metadata stage is matched to a corpus paper:

1. ``id``: an explicit SCA paper number. Forms seen in the corpus:
   ``SCA2003-12`` / ``SCA 2017-011`` (year-number), ``SCA 8809`` /
   ``SCA paper 9114`` (pre-2000: two-digit year + number, i.e. 1988 #09), and
   ``SCA-08`` with the year elsewhere in the reference. A bare ``SCA 2004`` is a
   year, not an ID. 1990-1992 references that mention "Europe" map to the EURO
   series.
2. ``title``: a corpus title (>= 4 words) fuzzily contained in the reference
   (rapidfuzz partial ratio), considered only when the reference also contains
   that paper's year and first-author surname; or, for long titles (>= 6 words),
   the year alone with a near-exact match.

An ID match is dropped when the reference quotes a title that does not match
the paper with that ID (a mistyped number pointing at an unrelated paper).
When an ID and a title point to different papers, the title wins (IDs are
often mistyped). Edges must point back in time (target year <= source year)
and never to the citing paper itself.

Scores per paper: ``cited_by`` (in-corpus citation count), ``pagerank``
(damping 0.85, scaled so the mean is 1) and ``cites_per_year`` (cited_by over
the years since publication, so recent papers are not buried).

Output: ``data/citations/citations.json`` (edges + scores),
``data/citations/report.txt`` (match statistics) and
``data/citations/sample.txt`` (random matched edges per method, for checking
precision by hand).
"""

import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np

from sca import cache, metadata, paths

OUTPUT = paths.CITATIONS_DIR / "citations.json"
REPORT = paths.CITATIONS_DIR / "report.txt"
SAMPLE = paths.CITATIONS_DIR / "sample.txt"

TITLE_MIN_WORDS = 4
TITLE_SCORE = 88  # with year + first-author surname in the reference
TITLE_YEAR_ONLY_WORDS = 6
TITLE_YEAR_ONLY_SCORE = 95
DAMPING = 0.85
QUOTED_TITLE_MIN = 60
# A quoted title of at least ~6 words: "...", “...”, ''...'' or '...'.
_QUOTED_RE = re.compile(r"[\"“”']{1,2}\s*([^\"“”]{40,}?)\s*[\"“”']{1,2}")
CURRENT_YEAR = 2026


def norm(text: str) -> str:
    """Lowercase ASCII words only (accents folded), single-spaced."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


@dataclass(frozen=True)
class Target:
    id: str
    year: int
    number: int
    series: str
    title: str  # normalised
    surname: str  # normalised first-author surname, "" if unknown


# --- explicit IDs -------------------------------------------------------------------

_SCA_WORD = r"\bSCA(?![A-Za-z])"  # "SCA1993-22" has no word boundary after "SCA"
_SCA = _SCA_WORD + r"[\s\-_#:]*(?:(?:paper|manuscript)\s*)?(?:no\.?\s*)?"
_ID_YEAR_NUM_RE = re.compile(_SCA + r"((?:19|20)\d{2})\s*[-_/]\s*(\d{1,4})(?!\d)", re.I)
_ID_COMPACT_RE = re.compile(_SCA + r"((?:8[7-9]|9\d))(\d{2})(?![\d\-])", re.I)
# "SCA-08 ... 2004", "SCA 35, 2005", "SCA A46, 2006", "SCA Manuscript 40 (2022)"
_ID_NUM_ONLY_RE = re.compile(
    _SCA_WORD + r"[\s\-#:]*(?:(?:paper|manuscript)\s*)?(?:no\.?\s*)?[A-Z]?(\d{1,3})(?![\d\-/.])",
    re.I,
)
# "Society of Core Analysts ... paper 9529" / "Conference paper 9007"
_PAPER_COMPACT_RE = re.compile(r"\bpaper\s*(?:no\.?\s*)?((?:8[7-9]|9\d))(\d{2})(?![\d\-])", re.I)
_MENTIONS_SCA_RE = re.compile(_SCA_WORD + r"|society of core analysts", re.I)
_YEAR_RE = re.compile(r"(?<!\d)(19[89]\d|20[0-2]\d)(?!\d)")


def ref_years(ref: str) -> set[int]:
    return {int(y) for y in _YEAR_RE.findall(ref) if 1987 <= int(y) <= CURRENT_YEAR}


def explicit_id(ref: str) -> tuple[int, int] | None:
    """(year, number) from an explicit SCA paper number in the reference."""
    if m := _ID_YEAR_NUM_RE.search(ref):
        return int(m[1]), int(m[2])
    if m := _ID_COMPACT_RE.search(ref):
        return 1900 + int(m[1]), int(m[2])
    if _MENTIONS_SCA_RE.search(ref) and (m := _PAPER_COMPACT_RE.search(ref)):
        return 1900 + int(m[1]), int(m[2])
    if m := _ID_NUM_ONLY_RE.search(ref):
        years = ref_years(ref)
        if len(years) == 1:
            return years.pop(), int(m[1])
    return None


# --- matching -----------------------------------------------------------------------


class Matcher:
    def __init__(self, records: list[dict]):
        self.targets: list[Target] = []
        self.by_number: dict[tuple[int, int, str], Target] = {}
        self.by_year: dict[int, list[Target]] = defaultdict(list)
        for r in records:
            if r["status"] != "ok":
                continue
            surname = norm(r["authors"][0].split()[-1]) if r["authors"] else ""
            if surname and len(surname) < 3:  # "D. P. TOBOLA" style already gives surname last
                surname = ""
            t = Target(
                r["id"], r["year"], r["number"], r["series"], norm(r["title"] or ""), surname
            )
            self.targets.append(t)
            self.by_number[(t.year, t.number, t.series)] = t
            if len(t.title.split()) >= TITLE_MIN_WORDS:
                self.by_year[t.year].append(t)

    def by_id(self, ref: str) -> Target | None:
        found = explicit_id(ref)
        if not found:
            return None
        year, number = found
        series = "euro" if year <= 1992 and re.search(r"europ|euro\b", ref, re.I) else "main"
        return self.by_number.get((year, number, series)) or self.by_number.get(
            (year, number, "main")
        )

    def by_title(self, ref: str) -> tuple[Target, float] | None:
        from rapidfuzz import fuzz

        nref = norm(ref)
        words = set(nref.split())
        best: tuple[Target, float] | None = None
        for year in ref_years(ref):
            for t in self.by_year.get(year, []):
                has_author = bool(t.surname) and t.surname in words
                long_title = len(t.title.split()) >= TITLE_YEAR_ONLY_WORDS
                if not (has_author or long_title):
                    continue
                score = fuzz.partial_ratio(t.title, nref)
                needed = TITLE_SCORE if has_author else TITLE_YEAR_ONLY_SCORE
                if score >= needed and (best is None or score > best[1]):
                    best = (t, score)
        return best

    def match(self, ref: str) -> tuple[Target, str] | None:
        id_hit = self.by_id(ref)
        title_hit = self.by_title(ref)
        if title_hit and id_hit and title_hit[0].id != id_hit.id:
            return title_hit[0], "title_over_id"
        if id_hit:
            quoted = _QUOTED_RE.search(ref)
            if quoted and id_hit.title:
                from rapidfuzz import fuzz

                if fuzz.partial_ratio(id_hit.title, norm(quoted[1])) < QUOTED_TITLE_MIN:
                    return None  # mistyped ID: the quoted title names another paper
            return id_hit, "id"
        if title_hit:
            return title_hit[0], "title"
        return None


# --- graph scores ---------------------------------------------------------------------


def pagerank(ids: list[str], edges: list[tuple[str, str]], damping: float = DAMPING) -> dict:
    """PageRank by power iteration; dangling nodes spread uniformly. Mean = 1."""
    index = {i: n for n, i in enumerate(ids)}
    n = len(ids)
    out_deg = np.zeros(n)
    src = np.array([index[s] for s, _ in edges], dtype=int)
    dst = np.array([index[t] for _, t in edges], dtype=int)
    np.add.at(out_deg, src, 1)
    rank = np.full(n, 1 / n)
    for _ in range(200):
        contrib = np.zeros(n)
        if len(edges):
            np.add.at(contrib, dst, rank[src] / out_deg[src])
        dangling = rank[out_deg == 0].sum()
        new = (1 - damping) / n + damping * (contrib + dangling / n)
        if np.abs(new - rank).sum() < 1e-12:
            rank = new
            break
        rank = new
    return {i: float(rank[index[i]] * n) for i in ids}


# --- stage ---------------------------------------------------------------------------------


def run(force: bool = False) -> dict:
    if not force and cache.is_fresh(OUTPUT, metadata.COMBINED):
        return json.loads(OUTPUT.read_text(encoding="utf-8"))
    records = json.loads(metadata.COMBINED.read_text(encoding="utf-8"))
    matcher = Matcher(records)
    year_of = {r["id"]: r["year"] for r in records}
    edges: dict[tuple[str, str], dict] = {}
    stats: Counter = Counter()
    unmatched_sca: list[str] = []
    for r in records:
        for ref in r["references"]:
            stats["references"] += 1
            mentions_sca = bool(_MENTIONS_SCA_RE.search(ref))
            stats["mention_sca"] += mentions_sca
            hit = matcher.match(ref)
            if hit is None:
                if mentions_sca:
                    unmatched_sca.append(ref)
                continue
            target, method = hit
            if target.id == r["id"] or year_of[target.id] > r["year"]:
                stats["rejected_time"] += 1
                continue
            key = (r["id"], target.id)
            if key in edges:
                stats["duplicate"] += 1
                continue
            edges[key] = {"source": r["id"], "target": target.id, "method": method, "ref": ref}
            stats[f"method_{method}"] += 1
            stats["matched_mention_sca" if mentions_sca else "matched_no_sca"] += 1
    ids = [r["id"] for r in records]
    cited_by = Counter(t for _, t in edges)
    pr = pagerank(ids, list(edges))
    scores = {
        i: {
            "cited_by": cited_by[i],
            "pagerank": round(pr[i], 4),
            "cites_per_year": round(cited_by[i] / max(1, CURRENT_YEAR - year_of[i]), 3),
        }
        for i in ids
    }
    data = {
        "edges": [{k: v for k, v in e.items() if k != "ref"} for e in edges.values()],
        "scores": scores,
    }
    cache.write_json_atomic(OUTPUT, data)
    cache.write_text_atomic(REPORT, _report(stats, edges, unmatched_sca, scores, records))
    cache.write_text_atomic(SAMPLE, _sample(list(edges.values()), records))
    return data


def _report(stats, edges, unmatched_sca, scores, records) -> str:
    titles = {r["id"]: r["title"] for r in records}
    lines = [
        f"references: {stats['references']}",
        f"edges: {len(edges)} (duplicates within a paper: {stats['duplicate']}, "
        f"rejected as self/future: {stats['rejected_time']})",
        "by method: "
        + ", ".join(f"{k[7:]}={v}" for k, v in sorted(stats.items()) if k.startswith("method_")),
        f"references mentioning SCA / Society of Core Analysts: {stats['mention_sca']}; "
        f"matched: {stats['matched_mention_sca']}; unmatched: {len(unmatched_sca)}",
        f"matched without an SCA mention: {stats['matched_no_sca']}",
        f"papers cited at least once: {sum(s['cited_by'] > 0 for s in scores.values())}",
        "",
        "most cited:",
    ]
    for i, s in sorted(scores.items(), key=lambda kv: -kv[1]["cited_by"])[:15]:
        lines.append(f"  {s['cited_by']:>3}  pr={s['pagerank']:<7} {i}  {(titles[i] or '')[:70]}")
    lines += ["", "unmatched references mentioning SCA (random 25):"]
    rng = random.Random(0)
    for ref in rng.sample(unmatched_sca, min(25, len(unmatched_sca))):
        lines.append(f"  - {ref[:200]}")
    return "\n".join(lines) + "\n"


def _sample(edges: list[dict], records: list[dict], per_method: int = 30) -> str:
    by_id = {r["id"]: r for r in records}
    rng = random.Random(1)
    lines = []
    for method in sorted({e["method"] for e in edges}):
        pool = [e for e in edges if e["method"] == method]
        lines.append(f"=== {method} ({len(pool)} edges, {min(per_method, len(pool))} shown)")
        for e in rng.sample(pool, min(per_method, len(pool))):
            t = by_id[e["target"]]
            lines.append(f"{e['source']} -> {e['target']}")
            lines.append(f"  ref:    {e['ref'][:220]}")
            lines.append(f"  target: {t['title']} | {', '.join(t['authors'][:3])} | {t['year']}")
    return "\n".join(lines) + "\n"
