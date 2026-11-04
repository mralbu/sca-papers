import json
import os

from sca import cache


def test_is_fresh(tmp_path):
    src, out = tmp_path / "in.pdf", tmp_path / "out.md"
    src.touch()
    assert not cache.is_fresh(out, src)
    out.touch()
    os.utime(src, (1, 1))
    assert cache.is_fresh(out, src)
    os.utime(src, (out.stat().st_mtime + 10,) * 2)
    assert not cache.is_fresh(out, src)


def test_write_json_atomic_creates_dirs_and_leaves_no_temp(tmp_path):
    target = tmp_path / "a" / "b.json"
    cache.write_json_atomic(target, {"x": "é"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"x": "é"}
    assert [p.name for p in target.parent.iterdir()] == ["b.json"]
