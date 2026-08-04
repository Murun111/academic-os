"""Tests for the learned reward model (Phase C ladder 4 — the first trained model)."""
from __future__ import annotations

import json

from backend.services.reward_model import (
    RewardModel,
    build_examples,
    readiness,
    score_with_model,
    train,
    train_from_log,
)


def test_train_separates_good_from_bad():
    # label 1 = good (high bt/script/length), label 0 = bad (low)
    pos = [([0.9, 1.0, 1.0], 1)] * 10
    neg = [([0.1, 0.0, 0.5], 0)] * 10
    model = train(pos + neg)
    assert model.score({"bt": 0.9, "script": 1.0, "length": 1.0}) > 0.5
    assert model.score({"bt": 0.1, "script": 0.0, "length": 0.5}) < 0.5
    assert model.n_train == 20


def test_learns_script_matters():
    # only the script feature distinguishes the classes → its weight should dominate
    pos = [([0.6, 1.0, 1.0], 1)] * 12
    neg = [([0.6, 0.0, 1.0], 0)] * 12  # same bt/length, wrong script
    model = train(pos + neg)
    w = dict(zip(("bt", "script", "length"), model.weights))
    assert w["script"] > w["bt"] and w["script"] > w["length"]
    # a Cyrillic candidate now outscores a romanized one with identical bt/length
    assert model.score({"bt": 0.6, "script": 1.0, "length": 1.0}) > \
           model.score({"bt": 0.6, "script": 0.0, "length": 1.0})


def test_save_load_roundtrip(tmp_path):
    m = train([([0.9, 1.0, 1.0], 1)] * 8 + [([0.1, 0.0, 0.2], 0)] * 8)
    p = m.save(tmp_path / "rm.json")
    loaded = RewardModel.load(p)
    assert loaded is not None
    assert loaded.score({"bt": 0.9, "script": 1.0, "length": 1.0}) > 0.5
    # stale-schema guard
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"features": ["x"], "weights": [1.0], "bias": 0.0}))
    assert RewardModel.load(bad) is None


def _prefs(n_pos, n_neg):
    prefs = []
    for _ in range(n_pos):
        prefs.append({"label": "auto_accept",
                      "meta": {"components": {"bt": 0.85, "script": 1.0, "length": 1.0}}})
    for _ in range(n_neg):
        prefs.append({"label": "auto_flag",
                      "meta": {"components": {"bt": 0.2, "script": 0.0, "length": 0.6}}})
    return prefs


def test_readiness_gate():
    assert readiness(_prefs(3, 3))["ready"] is False        # too few
    assert readiness(_prefs(2, 20))["ready"] is False       # too few positives
    r = readiness(_prefs(12, 12))
    assert r["ready"] and r["positives"] == 12 and r["negatives"] == 12


def test_build_examples_skips_componentless():
    prefs = _prefs(2, 2) + [{"label": "correction", "chosen": "x", "rejected": "y"}]
    rows = build_examples(prefs)
    assert len(rows) == 4  # the correction (no components) is skipped


def test_train_from_log_gated_and_trains(tmp_path, monkeypatch):
    pref_file = tmp_path / "prefs.jsonl"
    model_file = tmp_path / "rm.json"
    # not enough yet
    pref_file.write_text("\n".join(json.dumps(p) for p in _prefs(3, 3)) + "\n", encoding="utf-8")
    r1 = train_from_log(pref_path=pref_file, model_path=model_file)
    assert r1["trained"] is False and not model_file.exists()
    # enough → trains + saves
    pref_file.write_text("\n".join(json.dumps(p) for p in _prefs(12, 12)) + "\n", encoding="utf-8")
    r2 = train_from_log(pref_path=pref_file, model_path=model_file)
    assert r2["trained"] is True and model_file.exists()
    # the saved model scores good > bad
    assert score_with_model({"bt": 0.85, "script": 1.0, "length": 1.0}, model_path=model_file) > \
           score_with_model({"bt": 0.2, "script": 0.0, "length": 0.6}, model_path=model_file)


def test_score_with_model_none_when_absent(tmp_path):
    assert score_with_model({"bt": 0.5, "script": 1.0, "length": 1.0},
                            model_path=tmp_path / "nope.json") is None
