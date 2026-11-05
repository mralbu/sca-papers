import os

import pytest

from sca import convert, corpus, paths


@pytest.fixture
def paper(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PAPERS_DIR", tmp_path / "papers")
    monkeypatch.setattr(paths, "MARKDOWN_DIR", tmp_path / "markdown")
    pdf = tmp_path / "papers" / "2014" / "SCA2014-051.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.touch()
    os.utime(pdf, (1, 1))
    return corpus.parse_name(pdf)


def write_output(paper, md_text, images=()):
    out = convert.output_dir(paper)
    out.mkdir(parents=True)
    convert.markdown_path(paper).write_text(md_text)
    (out / f"{paper.id}_meta.json").write_text("{}")
    for name in images:
        (out / name).touch()


def test_missing_output_is_pending(paper):
    assert not convert.is_converted(paper)


def test_complete_output_is_converted(paper):
    write_output(paper, "# T\n![](_page_1_Figure_2.jpeg)\n", ["_page_1_Figure_2.jpeg"])
    assert convert.is_converted(paper)


def test_missing_image_means_interrupted(paper):
    write_output(paper, "# T\n![](_page_1_Figure_2.jpeg)\n")
    assert not convert.is_converted(paper)


def test_missing_meta_means_interrupted(paper):
    write_output(paper, "# T\n")
    (convert.output_dir(paper) / f"{paper.id}_meta.json").unlink()
    assert not convert.is_converted(paper)


def test_pdf_newer_than_markdown_is_stale(paper):
    write_output(paper, "# T\n")
    os.utime(paper.pdf, (convert.markdown_path(paper).stat().st_mtime + 10,) * 2)
    assert not convert.is_converted(paper)


def test_save_output_drops_empty_images(tmp_path, monkeypatch):
    from PIL import Image

    from sca import marker_batch

    class Rendered:
        metadata = {"ok": True}

    images = {"a.jpeg": Image.new("RGB", (4, 4)), "b.jpeg": Image.new("RGB", (0, 3))}
    text = "x ![](a.jpeg) y ![](b.jpeg) z"
    monkeypatch.setattr(marker_batch, "text_from_rendered", lambda r: (text, "md", images))
    marker_batch.save_output(Rendered(), str(tmp_path), "P")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["P.md", "P_meta.json", "a.jpeg"]
    assert (tmp_path / "P.md").read_text() == "x ![](a.jpeg) y  z"
