"""Stage: rule-based metadata from marker markdown (no LLM).

Per paper: ID, year, number and series (from the file name), title, authors,
abstract and the raw reference list. Heuristics, tuned on the corpus:

- The markdown is split into blocks (blank-line separated). The *front matter*
  is everything before the abstract marker or the first body heading.
  Symposium boilerplate ("This paper was prepared for presentation...",
  running headers, corresponding-author lines) is dropped from it.
- Title: the first front-matter block, preferably a heading (consecutive
  heading blocks are joined, since marker splits long titles). A leading
  ``SCA2003-12:`` is stripped. When marker fused authors into an all-caps title
  heading, the trailing non-caps text is split off as the author line.
- Authors: the first block after the title that yields name-like segments
  after removing superscripts, footnote marks and affiliation text.
- Abstract: an "Abstract"/"Summary" heading or an inline "**Abstract.**" label,
  up to the next heading. Without a label, the first long paragraph before any
  body heading is used and flagged ``abstract_source = "first_paragraph"``.
- References: the last "References"/"Bibliography"/"Literature cited" heading
  (or bold/standalone label) up to an appendix/nomenclature/table/figure
  heading, split into entries by list markers, ``[n]`` numbers or paragraphs.

Output: ``data/metadata/papers/<id>.json`` per paper (cached; redone when the
markdown is newer or ``VERSION`` changes), ``data/metadata/metadata.json``
with every paper, and a per-year coverage report so format differences
across years show up.
"""

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sca import cache, corpus, paths
from sca.corpus import Paper

VERSION = 18  # bump when extraction rules change, to invalidate cached outputs

PAPERS_OUT = paths.METADATA_DIR / "papers"
COMBINED = paths.METADATA_DIR / "metadata.json"
REPORT = paths.METADATA_DIR / "report.txt"

MAX_FRONT_BLOCKS = 12
MAX_ABSTRACT_WORDS = 800
LONG_PARAGRAPH_WORDS = 50


@dataclass
class Metadata:
    id: str
    year: int
    number: int
    series: str
    url: str
    status: str = "ok"  # "ok" or "no_markdown"
    pages: int | None = None  # one-page files are short papers/posters, usually without refs
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    authors_raw: str | None = None
    abstract: str | None = None
    abstract_source: str | None = None  # "label", "first_paragraph" or None
    references: list[str] = field(default_factory=list)
    version: int = VERSION


# --- text cleanup -------------------------------------------------------------

_SUP_RE = re.compile(r"<sup>.*?</sup>", re.S)
_TAG_RE = re.compile(r"</?[a-z]+[^>]*>")
_SPACES_RE = re.compile(r"\s+")


def clean_inline(text: str) -> str:
    """Markdown/HTML-free single-line text (keeps sub/sup content as plain text)."""
    text = _TAG_RE.sub("", text)
    text = text.replace("\\*", "*").replace("\\_", "_").replace("\\", "")
    text = re.sub(r"\*+|__+", "", text)
    text = re.sub(r"^#+\s*", "", text.strip())
    return _SPACES_RE.sub(" ", text).strip()


def _words(text: str) -> int:
    return len(text.split())


@dataclass
class Block:
    raw: str
    heading: bool  # starts with '#', or is entirely bold

    @property
    def text(self) -> str:
        return clean_inline(self.raw)


def split_blocks(md: str) -> list[Block]:
    blocks = []
    for raw in re.split(r"\n\s*\n", md):
        raw = raw.strip()
        if not raw:
            continue
        lines = [ln.strip() for ln in raw.splitlines()]
        is_heading = lines[0].startswith("#") or (
            raw.startswith("**") and raw.endswith("**") and raw.count("**") == 2
        )
        blocks.append(Block(raw="\n".join(lines), heading=is_heading))
    return blocks


# --- block classification -------------------------------------------------------

_ABSTRACT_LABEL_RE = re.compile(r"^(?:abstract|summary|executive summary)\s*[.:\-–—]?\s*", re.I)
_BODY_HEADING_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s+|[IVX]+\.\s+)?"
    r"(?:introduction|background|theory|methods?|methodology|experimental|nomenclature)\b",
    re.I,
)
_BOILERPLATE_RE = re.compile(
    r"prepared for presentation|international symposium of the society of core analysts"
    r"|^society of core analysts|e3s web of conferences|^\(?corresponding author|e-?mail\s*:"
    r"|^sca\s*[-_]?\d{4}[-_ ]?\d+\s*(?:\d+/\d+)?$|^\d+/\d+$|^page \d+",
    re.I,
)
_SCA_PREFIX_RE = re.compile(r"^SCA\s*[-_]?\s*\d{4}\s*[-_/]\s*\d+[A-Z]*\s*[:.\-–]?\s*", re.I)


def _is_abstract_label(block: Block) -> bool:
    if block.heading:
        return bool(_ABSTRACT_LABEL_RE.match(block.text))
    # Inline label: "**Abstract.** Text...", "Abstract: Text...", "ABSTRACT" alone.
    return bool(re.match(r"^\**\s*(?:abstract|summary)\s*(?:[.:\-–—]|\*\*|$)", block.raw, re.I))


def _is_body_heading(block: Block) -> bool:
    """A short section heading such as "1. INTRODUCTION" (titles can start with
    "Experimental ..." too, hence the length limit)."""
    return block.heading and _words(block.text) <= 6 and bool(_BODY_HEADING_RE.match(block.text))


def _is_boilerplate(block: Block) -> bool:
    text = block.text
    return not text or bool(_BOILERPLATE_RE.search(text)) and _words(text) < 60


# Boilerplate fused onto the end of a useful line: cut it off instead of dropping the line.
_BOILERPLATE_TAIL_RE = re.compile(
    r"(?:\*\s*)?(?:this paper was )?prepared for presentation.*$|\be-?mail\s*:.*$", re.I
)


def _without_boilerplate(block: Block) -> Block | None:
    """The block minus boilerplate lines (an e-mail line can sit in an author block)."""
    lines = [_BOILERPLATE_TAIL_RE.sub("", ln) for ln in block.raw.splitlines()]
    lines = [ln for ln in lines if not _BOILERPLATE_RE.search(clean_inline(ln))]
    if not any(clean_inline(ln) for ln in lines):
        return None
    return Block(raw="\n".join(lines), heading=block.heading)


def _is_author_block(block: Block) -> bool:
    """A paragraph that is mostly a list of names (long author lists exceed
    the "long paragraph" threshold that otherwise ends the front matter)."""
    names = parse_authors(block.raw)
    return len(names) >= 3 and _words(block.text) <= 12 * len(names)


# --- title and authors ------------------------------------------------------------

_ORG_WORDS = re.compile(
    r"\b(?:universit\w*|univ\.?|institut\w*|company|compan\w+|corp\w*|inc\.?|ltd\.?|llc|"
    r"gmbh|s\.a\.|s\.p\.a\.?|a/?s|asa|bv|plc|research|laborator\w*|labs?|dep(?:t|artment)\.?|"
    r"faculty|school|college|cent(?:er|re)|petrol\w*|energ\w*|oil|gas|exploration|"
    r"production|services?|technolog\w*|engineering|sciences?|geoscience\w*|"
    r"schlumberger|slb|aramco|shell|statoil|equinor|totalenergies|total|elf|bp|"
    r"exxon\w*|chevron|conocophillips|halliburton|baker|weatherford|amoco|mobil|"
    r"texaco|arco|norsk|hydro|ifp|norce|iris|csiro|sintef|road|street|avenue|box|"
    r"cedex|usa|uk|france|norway|canada|china|netherlands|germany|australia|"
    r"[ée]cole|polytechn\w*|centrale|survey|tech|cnrs|umr|state key|national|ministry|"
    r"geological|foundation|council|agency|group|\w*consult\w*|limited|associates|"
    r"imaging|water|groundwater|pdvsa|intevep|petrobras|mexico|arabia|scotia|emirates)\b",
    re.I,
)
_NAME_TOKEN = re.compile(
    r"^(?:[A-ZÀ-ÖØ-Þ][\w'’.\-]*|(?:[A-Z]\.)+|de|da|van|von|der|den|le|la|á|al|el|du|di|dos|ten)$"
)


def _strip_name_marks(text: str) -> str:
    text = _SUP_RE.sub(" ", text)
    text = clean_inline(text)
    text = re.sub(r"[*†‡§¶+#]", " ", text)
    text = re.sub(r"(?<=[^\W\d_])\d+(?:[,;]\s*\d+)*\b", "", text)  # Abdobal1,2 -> Abdobal
    text = re.sub(r"\(\s*\d+\s*\)", " ", text)
    return _SPACES_RE.sub(" ", text).strip()


def _looks_like_name(segment: str) -> bool:
    tokens = segment.split()
    if not 2 <= len(tokens) <= 6 or len(segment) > 45:
        return False
    if _ORG_WORDS.search(segment) or re.search(r"\d|'s\b|\bSt\.", segment):
        return False
    if all(_INITIAL.match(t) for t in tokens):
        return False  # "D. P." alone: initials split off a "SURNAME, D. P." entry
    if segment.isupper() and not any("." in t for t in tokens):
        return False  # an all-caps run is a title fragment, not a name
    return all(_NAME_TOKEN.match(t) for t in tokens)


_INITIAL = re.compile(r"^(?:[A-Z]\.-?){1,5}$|^(?:[A-Z]\.){0,4}[A-Z]$")  # "G.M." "G.M" "J.-P." "D"


def _name_prefix(segment: str) -> str | None:
    """A name at the start of a segment fused with its affiliation.

    "Christopher M. Prince VP Imaging Technology" -> "Christopher M. Prince":
    first name, any middle initials, surname; or initials then surname.
    """
    tokens = segment.split()
    if not tokens:
        return None
    n = 1  # first name (or first initial), then middle initials, then the surname
    while n < len(tokens) and _INITIAL.match(tokens[n]):
        n += 1
    n += 1
    candidate = " ".join(tokens[:n])
    return candidate if n < len(tokens) and _looks_like_name(candidate) else None


def parse_authors(text: str) -> list[str]:
    """Name-like segments of an author line, in order, without affiliations."""
    text = _strip_name_marks(re.sub(r"\s*\n\s*", ", ", text.strip()))
    text = re.sub(r"^by\s+", "", text, flags=re.I)
    text = re.sub(r"\b(?:Dr|Prof|Mr|Mrs|Ms)\b\.?\s*", "", text)
    text = re.sub(r"\(.*?\)", ",", text)  # inline affiliations: "Name (Univ, City)"
    names: list[str] = []
    parts = [p.strip(" .-–") for p in re.split(r"\s*(?:,|;|:|\band\b|&|\s[–—]\s)\s*", text)]
    for i, part in enumerate(parts):
        if part.lower() in {"jr", "sr", "ii", "iii", "iv"} and names:
            names[-1] += f" {part}"
            continue
        tokens = part.split()
        # "TOBOLA, D. P." -> "D. P. TOBOLA" (surname first, then its initials)
        nxt = parts[i + 1].split() if i + 1 < len(parts) else []
        if len(tokens) == 1 and nxt and all(_INITIAL.match(t) for t in nxt):
            part = f"{parts[i + 1]}. {part}".replace("..", ".")
        if _looks_like_name(part):
            names.append(part)
        elif _ORG_WORDS.search(part) and (prefix := _name_prefix(part)):
            names.append(prefix)
    return list(dict.fromkeys(names))


def _split_fused_title(raw: str) -> tuple[str, str]:
    """Split a block holding both title and author line into (title, rest).

    "**TITLE** S. Abdobal1,2, M. Fourar...", "TITLE ...METHODSbyA. E. Worthington",
    or "ALL CAPS TITLE Some Author, Org".
    """
    m = re.match(r"^(?:#+\s*)?\*\*(.+?)\*\*\s*(\S.*)$", raw, re.S)
    if m and _words(clean_inline(m[1])) >= 3:
        return clean_inline(m[1]), m[2]
    text = clean_inline(raw)
    # OCR glued "by" onto an all-caps title ("METHODSbyA. E.", "DATAby Douglas"): split.
    glued = re.split(r"(?<=[A-Z0-9)]{2})by(?=\s?[A-Z])", text, maxsplit=1)
    # Otherwise only before initials: "... METHODS by A. E. Worthington", not
    # "... Sandstone by Low Salinity Water Injection" (a title that continues).
    parts = (
        glued
        if len(glued) == 2
        else re.split(r"\s+by\s+(?=(?:[A-Z][a-z]+\s)?[A-Z]\.)", text, maxsplit=1)
    )
    if len(parts) == 2 and _words(parts[0]) >= 3:
        return parts[0], parts[1]
    m = re.match(r"^((?:[^a-z]*?[A-Z]{2,}[^a-z]*?))\s+(?=[A-Z][a-z]|[A-Z]\.\s?[A-Z])", text)
    if m and _words(m.group(1)) >= 3 and m.end() < len(text):
        return m.group(1).strip(), text[m.end() :].strip()
    return text, ""


def _starts_with_name(raw: str, names: list[str]) -> bool:
    text = re.sub(r"^by\s+", "", _strip_name_marks(raw), flags=re.I)
    first = names[0].split()[-1]  # surname (or the initials of "SURNAME, X." entries)
    return first in text[: len(names[0]) + 12]


def clean_title(text: str) -> str:
    text = _SCA_PREFIX_RE.sub("", clean_inline(text))
    return text.strip(" .:")


def _title_and_authors(front: list[Block]) -> tuple[str | None, list[str], str | None]:
    blocks = [nb for b in front if (nb := _without_boilerplate(b))]
    if not blocks:
        return None, [], None
    # marker sometimes drops the title: the first block is then the author line.
    first = blocks[0]
    if (
        not first.raw.startswith("#")
        and _words(first.text) < LONG_PARAGRAPH_WORDS
        and (names := parse_authors(first.raw))
        and _starts_with_name(first.raw, names)
        and (len(names) >= 2 or "," in first.text or re.match(r"by\s", first.text, re.I))
    ):
        return None, *_collect_authors([b.raw for b in blocks[:4]])
    # Title: the first heading if there is one early on, else the first block.
    start = next((i for i, b in enumerate(blocks[:3]) if b.heading), 0)
    title_parts = [blocks[start].text]
    i = start + 1
    while (
        i < len(blocks)
        and blocks[i].heading
        and not parse_authors(blocks[i].raw)
        and _words(" ".join(title_parts)) < 30
    ):
        title_parts.append(blocks[i].text)
        i += 1
    title = " ".join(title_parts)
    rest_blocks = [b.raw for b in blocks[i : i + 4]]
    if i == start + 1:  # a single title block may carry the author line too
        fused_title, fused_rest = _split_fused_title(blocks[start].raw)
        if fused_rest and parse_authors(fused_rest):
            title = fused_title
            rest_blocks.insert(0, fused_rest)
    title = clean_title(title)
    if _words(title) > 40:  # marker lost the title; this is body text
        title = ""
    return title or None, *_collect_authors(rest_blocks)


def _name_share(raw: str, names: list[str]) -> float:
    words = _words(_strip_name_marks(raw))
    return sum(_words(n) for n in names) / words if words else 0.0


def _collect_authors(raws: list[str]) -> tuple[list[str], str | None]:
    """Names from the first author block and any author blocks right after it
    (1980s/90s papers give each author a block with their own affiliation)."""
    names: list[str] = []
    used: list[str] = []
    for raw in raws:
        found = parse_authors(raw)
        if names and not (raw.startswith("**") or _name_share(raw, found) >= 0.5):
            break  # later blocks only when they are author blocks too, not affiliations
        if not found:
            if names:
                break
            continue
        names.extend(n for n in found if n not in names)
        used.append(clean_inline(_SUP_RE.sub("", raw)))
    return names, (" / ".join(used) or None)


# --- abstract ------------------------------------------------------------------------


def _abstract(blocks: list[Block], front_end: int) -> tuple[str | None, str | None]:
    """(abstract, source) starting from the block at ``front_end``."""
    if front_end < len(blocks) and _is_abstract_label(blocks[front_end]):
        first = blocks[front_end]
        parts = []
        inline = _ABSTRACT_LABEL_RE.sub("", first.text, count=1)
        if not first.heading or _words(first.text) > 3:
            parts.append(inline)
        for b in blocks[front_end + 1 :]:
            if b.heading or (parts and _words(" ".join(parts)) >= MAX_ABSTRACT_WORDS):
                break
            parts.append(b.text)
        text = " ".join(p for p in parts if p).strip()
        return (text, "label") if _words(text) >= 15 else (None, None)
    for b in blocks[front_end:]:
        if b.heading:
            break
        if (
            _words(b.text) >= LONG_PARAGRAPH_WORDS
            and not b.raw.startswith(("- ", "* ", "|"))
            and not _is_author_block(b)
        ):
            return b.text, "first_paragraph"
    return None, None


def _front_end(blocks: list[Block]) -> int:
    """Index of the first block after the front matter."""
    for i, b in enumerate(blocks[: MAX_FRONT_BLOCKS + 1]):
        if _is_abstract_label(b) or (i > 0 and _is_body_heading(b)):
            return i
        if i > 0 and not b.heading and _words(b.text) >= LONG_PARAGRAPH_WORDS:
            if not _is_boilerplate(b) and not _is_author_block(b):
                return i
    return min(len(blocks), 3)


# --- references ------------------------------------------------------------------------

_REF_LABEL = (
    r"(?:\d+(?:\.\d+)*\.?\s*)?"
    r"(?:references?(?: cited)?|bibliography|literature(?: cited)?|reference list)"
)
_REF_HEADING_RE = re.compile(
    rf"^(?:#+\s*\**\s*{_REF_LABEL}\s*[:.]?\s*\**\s*"  # ## 6. References
    rf"|(?:-\s*)?\*\*\s*{_REF_LABEL}\s*[:.]?\s*\*\*"  # **References** alone
    rf"|{_REF_LABEL}\s*[:.]?)$"  # REFERENCES alone (OCR)
    rf"|\s\*\*\s*{_REF_LABEL}\s*[:.]?\s*\*\*\s*$",  # "... text **References**" glued on
    re.I,
)
_REF_STOP_RE = re.compile(
    r"^#+\s*\**\s*(?:[A-Z]\.?\s*|\d+\.?\s*)?(?:appendi(?:x|ces)|nomenclature|tables?|figures?|"
    r"fig\.|list of|acknowledge?ments?)\b",
    re.I,
)
# Figure/table captions or lists that follow the references in older papers.
_CAPTION_RE = re.compile(
    r"^\**\s*(?:TABLES?|FIGURES?|(?:Fig(?:ure)?s?\.?|Table|Plate)\s*\d+\s*[.:–\-—]?)", re.I
)
_ENTRY_START_RE = re.compile(r"^(?:[-*•]\s+|\[\d+\]\s*|\d{1,3}\s*[-.)]\s+)")


_SPAN_RE = re.compile(r"<span[^>]*>\s*</span>")
# A label sharing its line with the first entry: "**REFERENCES** 1- Abrams, A.: ...",
# "**References** [1] J. Kamath, ...", or OCR's "REFERENCESAHMED, G., ...".
_REF_INLINE_RE = re.compile(
    r"^(?:#+\s*)?\**\s*(?:\d+\.?\s*)?(?:REFERENCES|BIBLIOGRAPHY|(?i:references|bibliography)"
    r"(?=\s*[:.]?\s*\*\*))\s*[:.]?\s*\**\s*(?P<rest>(?:\[\d|\d{1,3}\s*[-.)\]]|[A-Z]).+)$"
)
# ... or glued after other text: "- Vw: volume of brine **References** [1] Archie, ..."
_REF_GLUED_RE = re.compile(
    r"\s\*\*\s*(?i:references|bibliography)\s*[:.]?\s*\*\*\s*(?P<rest>(?:\[\d|\d{1,3}[.)]\s).+)$"
)


def _reference_section(lines: list[str]) -> tuple[int, int, list[str]] | None:
    """The reference list in ``lines``: (first line, end line, entry lines).

    The section starts at the last references heading (or a label sharing its
    line with the first entry) and ends at the next section heading, appendix
    or caption list; tables and images inside it are skipped.
    """
    start, first = None, None
    for i, line in enumerate(lines):
        if _REF_HEADING_RE.search(line):
            start, first = i, None
        elif m := _REF_INLINE_RE.match(line) or _REF_GLUED_RE.search(line):
            start, first = i, m["rest"]
    if start is None:
        return None
    body: list[str] = [first] if first else []
    end = len(lines)
    for i in range(start + 1, len(lines)):
        s = lines[i].strip()
        if _REF_STOP_RE.match(s) or _CAPTION_RE.match(s):
            end = i
            break
        if s.startswith("#") and not _ENTRY_START_RE.match(clean_inline(s)):
            end = i
            break  # any later section heading ends the list
        if s.startswith(("|", "![")):  # tables/figures interleaved after the list
            continue
        body.append(s)
    return start, end, body


def find_references(md: str) -> list[str]:
    lines = [_SPAN_RE.sub("", ln).strip() for ln in md.splitlines()]
    section = _reference_section(lines)
    return split_references(section[2]) if section else []


def without_references(md: str) -> str:
    """``md`` with its reference list cut out (from the heading to the section end).

    If the label shares a line with other text ("... **References** [1] ..."),
    that whole line goes too.
    """
    lines = md.splitlines()
    section = _reference_section([_SPAN_RE.sub("", ln).strip() for ln in lines])
    if not section:
        return md
    start, end, _ = section
    return "\n".join(lines[:start] + lines[end:])


def split_references(lines: list[str]) -> list[str]:
    nonempty = [ln for ln in lines if ln]
    marked = sum(bool(_ENTRY_START_RE.match(ln)) for ln in nonempty)
    entries: list[list[str]] = []
    if nonempty and marked >= max(2, len(nonempty) // 3):
        for ln in nonempty:
            if _ENTRY_START_RE.match(ln) or not entries:
                entries.append([_ENTRY_START_RE.sub("", ln)])
            else:
                entries[-1].append(ln)
    else:
        current: list[str] = []
        for ln in lines + [""]:
            if ln:
                current.append(ln)
            elif current:
                entries.append(current)
                current = []
    out = []
    for parts in entries:
        for piece in _split_run_on(clean_inline(" ".join(parts))):
            piece = _ENTRY_NUMBER_RE.sub("", piece).strip()
            if len(piece) >= 20 and not _BOILERPLATE_RE.search(piece):
                out.append(piece)
    return out


_ENTRY_NUMBER_RE = re.compile(
    r"^(?:[-*•]\s*)?(?:\[\s*\d{1,3}\s*\]|\d{1,3}\s*[\].)\-–—]|\d{1,3}\s+(?=[A-ZÀ-ÖØ-Þ])|[lI][.)])\s*"
)
# Where one reference ends and the next starts inside a run-on paragraph:
# "... 1994. Bornert M., ..." or "... pp. 1-9. [12] ..." or "... 2001. Smith, J. ...".
_AUTHOR_YEAR_SPLIT_RE = re.compile(
    r"(?<=[.)\]\d])(?<![\s.,(][A-Z]\.)(?<!\bal\.)\s+(?=\[\d{1,3}\]\s"
    r"|[A-Z][\w'’\-]+(?:\s(?:van|von|de|der|da|du|le|la))?,?\s?(?:[A-Z]\.\s?-?){1,3}[,.:&;]?\s)"
)
_NUMBERED_START_RE = re.compile(r"^(?:[-*•]\s*)?\[?\s*(?:1|l)\s*[\].)\-–—]?\s*[A-ZÀ-ÖØ-Þ]")
_UPPER = "A-ZÀ-ÖØ-Þ"
RUN_ON_MIN_CHARS = 350
MAX_REFERENCE_CHARS = 1500


def _split_numbered(text: str) -> list[str]:
    """Cut "1 Smith ... 2 Jones ... 3 ..." at each next number in sequence."""
    cuts, pos, k = [], 0, 2
    while True:
        m = re.compile(
            rf"(?<=[\s.,;)\]\"'”])\[?{k}\s*[\].)\-–—]?\s*(?=[{_UPPER}][\w'’\-]*[\s,.])"
        ).search(text, pos + 1)
        if not m or m.start() - pos > MAX_REFERENCE_CHARS:
            break
        cuts.append(m.start())
        pos, k = m.start(), k + 1
    bounds = [0, *cuts, len(text)]
    return [text[i:j].strip() for i, j in zip(bounds, bounds[1:], strict=False)]


def _split_run_on(text: str) -> list[str]:
    """Split a paragraph that holds several references (no list markup)."""
    if _NUMBERED_START_RE.match(text):  # sequential numbers are strong evidence
        pieces = _split_numbered(text)
        if len(pieces) > 1:
            return pieces
    if len(text) < RUN_ON_MIN_CHARS:
        return [text]
    return [p for p in _AUTHOR_YEAR_SPLIT_RE.split(text) if p.strip()]


# --- stage -------------------------------------------------------------------------------


def _base(paper: Paper, **kwargs) -> Metadata:
    return Metadata(
        id=paper.id,
        year=paper.year,
        number=paper.number,
        series=paper.series,
        url=paper.url,
        **kwargs,
    )


def extract(paper: Paper, md: str, pages: int | None = None) -> Metadata:
    meta = _base(paper, pages=pages)
    blocks = split_blocks(md)
    end = _front_end(blocks)
    meta.title, meta.authors, meta.authors_raw = _title_and_authors(blocks[:end])
    meta.abstract, meta.abstract_source = _abstract(blocks, end)
    meta.references = find_references(md)
    return meta


def _page_count(marker_meta: Path) -> int | None:
    try:
        return len(json.loads(marker_meta.read_text(encoding="utf-8"))["page_stats"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _markdown(paper: Paper) -> Path:
    return paths.MARKDOWN_DIR / paper.id / f"{paper.id}.md"


def _cached(out: Path, md: Path) -> dict | None:
    if not cache.is_fresh(out, md):
        return None
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if data.get("version") == VERSION else None


def process(paper: Paper, force: bool = False) -> dict:
    md = _markdown(paper)
    marker_meta = md.with_name(f"{paper.id}_meta.json")
    out = PAPERS_OUT / f"{paper.id}.json"
    if not md.exists():
        return asdict(_base(paper, status="no_markdown"))
    if not force and (data := _cached(out, md)):
        return data
    text = md.read_text(encoding="utf-8", errors="replace")
    data = asdict(extract(paper, text, pages=_page_count(marker_meta)))
    cache.write_json_atomic(out, data)
    return data


FIELDS = ("title", "authors", "abstract", "references")


def report(records: list[dict]) -> str:
    """Per-year table of missing fields, so format differences across years show up.

    Missing references are counted only for papers longer than one page: the
    one-page short papers/posters (``1pg``) normally have none.
    """
    by_year: dict[int, list[dict]] = defaultdict(list)
    for r in records:
        by_year[r["year"]].append(r)
    cols = ["n", "no_md", "1pg", *(f"-{f}" for f in FIELDS), "abs_fallbk", "refs_med"]
    rows = [" ".join(f"{c:>11}" for c in ["year", *cols])]
    totals: dict[str, int] = defaultdict(int)
    for year in sorted(by_year):
        rs = by_year[year]
        ok = [r for r in rs if r["status"] == "ok"]
        long = [r for r in ok if (r.get("pages") or 2) > 1]
        refs = sorted(len(r["references"]) for r in ok if r["references"])
        counts = {
            "n": len(rs),
            "no_md": len(rs) - len(ok),
            "1pg": len(ok) - len(long),
            **{f"-{f}": sum(not r[f] for r in ok) for f in FIELDS if f != "references"},
            "-references": sum(not r["references"] for r in long),
            "abs_fallbk": sum(r["abstract_source"] == "first_paragraph" for r in ok),
        }
        for c, v in counts.items():
            totals[c] += v
        counts["refs_med"] = refs[len(refs) // 2] if refs else 0
        rows.append(" ".join(f"{v:>11}" for v in [year, *(counts[c] for c in cols)]))
    rows.append(" ".join(f"{v:>11}" for v in ["all", *(totals.get(c, "") for c in cols)]))
    rows.append(
        "-field: papers with markdown where the field came out empty "
        "(-references: excluding 1-page papers); abs_fallbk: abstract taken from the "
        "first long paragraph (no label); refs_med: median reference count"
    )
    return "\n".join(rows) + "\n"


def run(ids: list[str] | None = None, force: bool = False) -> list[dict]:
    papers = list(corpus.iter_papers())
    if ids:
        wanted = set(ids)
        papers = [p for p in papers if p.id in wanted]
    records = [process(p, force=force) for p in papers]
    if not ids:  # partial runs don't overwrite the combined outputs
        cache.write_json_atomic(COMBINED, records)
        cache.write_text_atomic(REPORT, report(records))
    return records
