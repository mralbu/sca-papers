"""Stage: PDF -> markdown with marker (balanced mode, shared Surya vLLM server).

marker's batch CLI takes a flat folder and names outputs after the file stem,
so this stage builds ``data/convert-input/<paper id>.pdf`` symlinks for papers
that still need converting and hands that folder to ``marker``. Output lands in
``data/markdown/<id>/<id>.md`` with ``<id>_meta.json`` and the extracted
figures next to it.

Resumable: a paper counts as converted only when its markdown, its meta JSON
and every image the markdown references exist, and the markdown is newer than
the PDF. Anything else (missing, stale, half-written by an interrupted run) is
cleared and converted again. PDFs that pdfium cannot open are repaired with
``mutool clean`` first; if that fails too (e.g. the truncated ``SCA2014-051``,
whose page tree is gone), the paper is reported as unreadable and skipped.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pypdfium2

from sca import cache, corpus, paths
from sca.corpus import Paper

INPUT_DIR = paths.DATA_DIR / "convert-input"
REPAIRED_DIR = paths.DATA_DIR / "repaired-pdfs"

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")


def output_dir(paper: Paper) -> Path:
    return paths.MARKDOWN_DIR / paper.id


def markdown_path(paper: Paper) -> Path:
    return output_dir(paper) / f"{paper.id}.md"


def is_converted(paper: Paper) -> bool:
    md = markdown_path(paper)
    meta = output_dir(paper) / f"{paper.id}_meta.json"
    if not (meta.exists() and cache.is_fresh(md, paper.pdf)):
        return False
    images = _IMAGE_RE.findall(md.read_text(encoding="utf-8", errors="replace"))
    return all((md.parent / img).exists() for img in images if "://" not in img)


def _opens(pdf: Path) -> bool:
    try:
        pypdfium2.PdfDocument(pdf).close()
        return True
    except pypdfium2.PdfiumError:
        return False


def readable_pdf(paper: Paper) -> Path | None:
    """The PDF to feed marker: the original, a mutool-repaired copy, or None."""
    if _opens(paper.pdf):
        return paper.pdf
    repaired = REPAIRED_DIR / f"{paper.id}.pdf"
    if not cache.is_fresh(repaired, paper.pdf):
        repaired.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["mutool", "clean", str(paper.pdf), str(repaired)], capture_output=True
        )
        if result.returncode != 0:
            repaired.unlink(missing_ok=True)
            return None
    return repaired if _opens(repaired) else None


def pending(papers: list[Paper]) -> list[Paper]:
    return [p for p in papers if not is_converted(p)]


def stage_inputs(todo: list[Paper]) -> list[Paper]:
    """Point INPUT_DIR at the readable papers in ``todo`` and clear their old
    output. Returns the papers that could not be read."""
    shutil.rmtree(INPUT_DIR, ignore_errors=True)
    INPUT_DIR.mkdir(parents=True)
    unreadable = []
    for paper in todo:
        pdf = readable_pdf(paper)
        if pdf is None:
            unreadable.append(paper)
            continue
        shutil.rmtree(output_dir(paper), ignore_errors=True)
        (INPUT_DIR / f"{paper.id}.pdf").symlink_to(pdf.resolve())
    return unreadable


def run(ids: list[str] | None = None, workers: int | None = None, limit: int | None = None) -> int:
    """Convert pending papers (optionally only ``ids``). Returns failures."""
    papers = list(corpus.iter_papers())
    if ids:
        wanted = set(ids)
        unknown = wanted - {p.id for p in papers}
        if unknown:
            raise SystemExit(f"unknown paper id(s): {', '.join(sorted(unknown))}")
        papers = [p for p in papers if p.id in wanted]
    missing = pending(papers)
    todo = missing[:limit] if limit else missing
    done = len(papers) - len(missing)
    print(
        f"{done}/{len(papers)} already converted; {len(missing)} pending, {len(todo)} in this run"
    )
    if not todo:
        return 0

    unreadable = stage_inputs(todo)
    for paper in unreadable:
        print(f"UNREADABLE {paper.id} ({paper.rel_path}): skipped")
    if len(unreadable) == len(todo):
        return len(unreadable)
    cmd = ["marker", str(INPUT_DIR), "--output_dir", str(paths.MARKDOWN_DIR)]
    cmd += ["--output_format", "markdown", "--skip_existing"]
    if workers:
        cmd += ["--workers", str(workers)]
    subprocess.run(cmd, check=True)

    failed = [p for p in pending(todo) if p not in unreadable]
    for paper in failed:
        print(f"FAILED {paper.id} ({paper.rel_path})")
    n_bad = len(failed) + len(unreadable)
    print(f"converted {len(todo) - n_bad}/{len(todo)}; ", end="")
    print(f"{len(failed)} failed, {len(unreadable)} unreadable")
    return n_bad
