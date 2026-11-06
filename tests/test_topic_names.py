from sca import site, topic_names


def _topic_data(members):
    papers = {pid: {"topic": t, "x": 0, "y": 0, "outlier": False} for pid, t in members.items()}
    topics = [
        {"id": t, "label": f"k{t}a / k{t}b / k{t}c", "keywords": [f"k{t}a", f"k{t}b", f"k{t}c"]}
        for t in sorted(set(members.values()))
    ]
    return {"papers": papers, "topics": topics}


def test_signature_follows_membership_not_order():
    a = _topic_data({"P1": 0, "P2": 0, "P3": 1})
    b = _topic_data({"P3": 1, "P2": 0, "P1": 0})
    c = _topic_data({"P1": 0, "P2": 1, "P3": 1})
    assert topic_names.signature(a) == topic_names.signature(b) != topic_names.signature(c)


def test_topic_labels_precedence(monkeypatch, tmp_path):
    data = _topic_data({"P1": 0, "P2": 1, "P3": 2})
    data["topics"][0]["label"] = "Hand name"  # topics.yaml rename already applied
    monkeypatch.setattr(site.topics, "load_overrides", lambda: {"rename": {0: "Hand name"}})
    names = {0: {"name": "LLM zero", "short": "Z"}, 1: {"name": "LLM one", "short": "One"}}
    monkeypatch.setattr(site.topic_names, "names_for", lambda _: names)
    out = {t["id"]: t for t in site.topic_labels(data)}
    assert (out[0]["label"], out[0]["short"]) == ("Hand name", "Hand name")
    assert (out[1]["label"], out[1]["short"]) == ("LLM one", "One")
    assert out[2]["label"] == "k2a / k2b / k2c" and "short" not in out[2]
    assert out[1]["keyword_label"] == "k1a / k1b / k1c"


def test_names_for_ignores_stale_cache(monkeypatch, tmp_path):
    path = tmp_path / "names.json"
    monkeypatch.setattr(topic_names, "NAMES", path)
    data = _topic_data({"P1": 0})
    path.write_text('{"signature": "stale", "names": {"0": {"name": "X", "short": "X"}}}')
    assert topic_names.names_for(data) == {}
