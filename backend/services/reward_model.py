"""Learned reward model — the first *trained* model in the translator (Phase C / ladder 4).

The hand-tuned reward blends fixed weights (0.4·script, 0.7·length, …). This
module LEARNS those weights from your own accept/reject data: a tiny logistic
regression over the reward features [bt, script, length], fit by gradient descent
(pure numpy, no GPU, no new deps). It's pointwise — predicts P(good translation)
— trained on preference examples logged by the loop (auto_accept=1, auto_flag=0,
corrections chosen=1/rejected=0).

Once trained and saved, `score_translation` uses it in place of the hand blend.
Gated on data: `readiness()` says when enough preferences have accumulated.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from backend.vault import agentic_os_dir

FEATURES = ("bt", "script", "length")
_MIN_EXAMPLES = 20            # don't train on noise; need a modest labeled set
_MIN_PER_CLASS = 5           # ...with both positives and negatives


def _model_path() -> Path:
    return agentic_os_dir() / "data" / "kb" / "reward_model.json"


def _vec(components: dict) -> list[float]:
    return [float(components.get(f, 0.0) or 0.0) for f in FEATURES]


def _sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


@dataclass
class RewardModel:
    weights: list[float] = field(default_factory=lambda: [0.0] * len(FEATURES))
    bias: float = 0.0
    n_train: int = 0

    def score(self, components: dict) -> float:
        x = _vec(components)
        z = self.bias + sum(w * xi for w, xi in zip(self.weights, x))
        return _sigmoid(z)

    def to_dict(self) -> dict:
        return {"features": list(FEATURES), "weights": self.weights,
                "bias": self.bias, "n_train": self.n_train}

    def save(self, path: Optional[Path] = None) -> Path:
        p = Path(path) if path else _model_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: Optional[Path] = None) -> Optional["RewardModel"]:
        p = Path(path) if path else _model_path()
        if not p.is_file():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if list(d.get("features", [])) != list(FEATURES):
                return None  # feature schema changed → ignore stale model
            return cls(weights=[float(w) for w in d["weights"]],
                       bias=float(d.get("bias", 0.0)), n_train=int(d.get("n_train", 0)))
        except (ValueError, KeyError, TypeError):
            return None


def train(examples: list[tuple[list[float], int]], *, epochs: int = 400,
          lr: float = 0.3, l2: float = 1e-3) -> RewardModel:
    """Fit logistic regression on (feature-vector, label∈{0,1}) via gradient
    descent. Standardizes nothing (features are already 0..1). Deterministic."""
    n_f = len(FEATURES)
    w = [0.0] * n_f
    b = 0.0
    n = len(examples)
    if n == 0:
        return RewardModel(w, b, 0)
    for _ in range(epochs):
        gw = [0.0] * n_f
        gb = 0.0
        for x, y in examples:
            z = b + sum(w[j] * x[j] for j in range(n_f))
            err = _sigmoid(z) - y
            for j in range(n_f):
                gw[j] += err * x[j]
            gb += err
        for j in range(n_f):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
        b -= lr * (gb / n)
    return RewardModel(w, b, n)


def _label_for(pref: dict) -> Optional[int]:
    label = pref.get("label")
    if label in ("auto_accept", "correction_chosen"):
        return 1
    if label in ("auto_flag", "correction_rejected"):
        return 0
    # A "correction" record is a paired example; handled by expansion below.
    return None


def build_examples(prefs: list[dict]) -> list[tuple[list[float], int]]:
    """Turn logged preferences into (features, label) rows. Uses records that
    carry reward `components` in meta (auto_accept/flag). Corrections without
    components are skipped (no back-translation feature was computed for them)."""
    rows: list[tuple[list[float], int]] = []
    for p in prefs:
        comp = (p.get("meta") or {}).get("components")
        lab = _label_for(p)
        if comp and lab is not None:
            rows.append((_vec(comp), lab))
    return rows


def readiness(prefs: list[dict]) -> dict:
    rows = build_examples(prefs)
    pos = sum(1 for _, y in rows if y == 1)
    neg = len(rows) - pos
    ready = len(rows) >= _MIN_EXAMPLES and pos >= _MIN_PER_CLASS and neg >= _MIN_PER_CLASS
    return {"usable_examples": len(rows), "positives": pos, "negatives": neg,
            "ready": ready, "need": max(0, _MIN_EXAMPLES - len(rows))}


def train_from_log(*, pref_path: Optional[Path] = None,
                   model_path: Optional[Path] = None) -> dict:
    """Train the reward model from the logged preferences and save it. Returns a
    report. Refuses to train (and leaves any existing model untouched) until the
    readiness threshold is met — training on noise would hurt the loop."""
    from backend.services.preferences import load_preferences
    prefs = load_preferences(path=pref_path)
    r = readiness(prefs)
    if not r["ready"]:
        return {**r, "trained": False,
                "message": f"not enough preference data yet — {r['usable_examples']} usable "
                           f"(need ≥{_MIN_EXAMPLES}, ≥{_MIN_PER_CLASS}/class). Keep using the loop."}
    model = train(build_examples(prefs))
    path = model.save(model_path)
    return {**r, "trained": True, "model_path": str(path),
            "weights": dict(zip(FEATURES, [round(w, 3) for w in model.weights])),
            "bias": round(model.bias, 3)}


# Cached loaded model (so score_translation doesn't re-read the file each call).
_CACHE: dict = {"mtime": None, "model": None}


def score_with_model(components: dict, *, model_path: Optional[Path] = None) -> Optional[float]:
    """Score reward features with the trained model, or None if none is trained
    yet (caller falls back to the hand blend). Hot-reloads when the file changes."""
    p = Path(model_path) if model_path else _model_path()
    try:
        mtime = p.stat().st_mtime if p.is_file() else None
    except OSError:
        mtime = None
    if mtime is None:
        return None
    if _CACHE["mtime"] != mtime:
        _CACHE["model"] = RewardModel.load(p)
        _CACHE["mtime"] = mtime
    model = _CACHE["model"]
    return model.score(components) if model else None
