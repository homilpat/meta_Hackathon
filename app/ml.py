"""S4 SPI-only risk model: synthetic training data, leak-proof features, time/group split, TreeSHAP.

The label is SYNTHETIC_LABEL (generator ground truth surfaced as an operator DEFECT_CONFIRMED).
Scores are model behaviour on synthetic data, not industrial performance, and SHAP explains the
model's output, not the physical cause of a defect.
"""

import hashlib
import json
import math
import random
from datetime import UTC, datetime, timedelta
from statistics import mean, pstdev

import lightgbm
import numpy as np
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

GENERATOR_VERSION = "s4-train-1"
FEATURE_VERSION = "spi-board-v1"
NOMINAL, SPEC = 0.12, (0.095, 0.145)  # synthetic process spec for solder volume (mm3)
FEATURES = ["n_pins", "vol_mean", "vol_std", "vol_min", "vol_max", "vol_range", "vol_abs_dev_max",
            "frac_out_of_spec"]
PREDICTOR_SOURCE = "spi_measurements"  # the only entity type allowed to feed the predictor
POST_HOC = {"aoi_inspections", "human_verifications", "repair_dispositions"}
XAI_METHOD = "lightgbm_pred_contrib_treeshap"


class LeakageError(ValueError):
    pass


def sha256_json(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def board_features(events: list[tuple[str, dict]]) -> dict:
    """Features for one board from (entity_type, record) pairs. Anything but SPI is a leak."""
    if not events:
        raise ValueError("no SPI records")
    for entity_type, _ in events:
        if entity_type != PREDICTOR_SOURCE:
            raise LeakageError(f"{entity_type} cannot feed the SPI predictor")
    vols = [float(r["volume_mm3"]) for _, r in events]
    return {
        "n_pins": float(len(vols)), "vol_mean": mean(vols), "vol_std": pstdev(vols),
        "vol_min": min(vols), "vol_max": max(vols), "vol_range": max(vols) - min(vols),
        "vol_abs_dev_max": max(abs(v - NOMINAL) for v in vols),
        "frac_out_of_spec": sum(not SPEC[0] <= v <= SPEC[1] for v in vols) / len(vols),
    }


def assert_no_leakage(feature_names: list[str]) -> None:
    if feature_names != FEATURES:
        raise LeakageError(f"feature schema differs from the audited SPI-only list: {feature_names}")


def training_boards(seed: int = 11, n_panels: int = 240) -> list[dict]:
    """Seeded SYNTHETIC boards. Post-hoc AOI/human/repair outcomes are kept apart from SPI."""
    rng = random.Random(seed)
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for p in range(n_panels):
        drift = 0.006 * p / n_panels  # slow process drift, makes the time split meaningful
        for b in range(4):
            defect = rng.random() < 0.15
            spi = []
            for pin in range(rng.randint(2, 6)):
                v = rng.gauss(NOMINAL + drift, 0.011)
                if defect and rng.random() < 0.55:
                    v += rng.choice((-1, 1)) * rng.uniform(0.02, 0.05)
                spi.append({"pin_number": pin + 1, "volume_mm3": round(v, 4)})
            aoi = "FAIL" if rng.random() < (0.9 if defect else 0.07) else "PASS"
            human = "DEFECT_CONFIRMED" if defect else ("FALSE_ALARM" if aoi == "FAIL" else "PASS_CONFIRMED")
            rows.append({
                "panel_id": f"TP{p:03d}", "board_id": f"B{b + 1:02d}", "data_origin": "SYNTHETIC",
                "produced_at": (t0 + timedelta(hours=p)).isoformat(), "spi": spi,
                "post_hoc": {"aoi_result": aoi, "human_result": human,
                             "repair": "REPAIRED" if human == "DEFECT_CONFIRMED" else "NO_REPAIR"},
                "label": int(human == "DEFECT_CONFIRMED"),
            })
    return rows


def split_by_time(rows: list[dict]) -> dict[str, list[dict]]:
    """Panels ordered by production time: 60% train, 15% validation (threshold), 25% test."""
    panels = sorted({r["panel_id"]: r["produced_at"] for r in rows}.items(), key=lambda kv: kv[1])
    order = [p for p, _ in panels]
    cut1, cut2 = int(len(order) * 0.60), int(len(order) * 0.75)
    group = {p: ("train" if i < cut1 else "valid" if i < cut2 else "test") for i, p in enumerate(order)}
    out: dict[str, list[dict]] = {"train": [], "valid": [], "test": []}
    for r in rows:
        out[group[r["panel_id"]]].append(r)
    return out


def matrix(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    feats = [board_features([(PREDICTOR_SOURCE, s) for s in r["spi"]]) for r in rows]
    return np.array([[f[k] for k in FEATURES] for f in feats]), np.array([r["label"] for r in rows])


def _metrics(y: np.ndarray, p: np.ndarray, threshold: float) -> dict:
    pred = p >= threshold
    tp, fp, fn = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum()), int((~pred & (y == 1)).sum())
    return {"n": len(y), "positives": int(y.sum()), "pr_auc": round(float(average_precision_score(y, p)), 4),
            "roc_auc": round(float(roc_auc_score(y, p)), 4), "brier": round(float(brier_score_loss(y, p)), 4),
            "threshold": round(threshold, 4), "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
            "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0}


def _best_f1_threshold(y: np.ndarray, p: np.ndarray) -> float:
    best, best_t = -1.0, 0.5
    for t in sorted(set(np.round(p, 4))):
        pred = p >= t
        tp = (pred & (y == 1)).sum()
        f1 = 2 * tp / (pred.sum() + y.sum()) if pred.sum() + y.sum() else 0.0
        if f1 > best:
            best, best_t = f1, float(t)
    return best_t


def train(seed: int = 11) -> dict:
    """Train dummy, logistic and LightGBM; LightGBM is the stored primary model."""
    assert_no_leakage(FEATURES)
    rows = training_boards(seed)
    parts = split_by_time(rows)
    (xtr, ytr), (xva, yva), (xte, yte) = (matrix(parts[k]) for k in ("train", "valid", "test"))
    candidates = {
        "dummy_prior": DummyClassifier(strategy="prior"),
        "logistic_regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)),
        "lightgbm": lightgbm.LGBMClassifier(n_estimators=150, learning_rate=0.05, num_leaves=15,
                                            min_child_samples=20, random_state=seed, deterministic=True,
                                            force_row_wise=True, n_jobs=1, verbose=-1),
    }
    metrics, thresholds = {}, {}
    for name, model in candidates.items():
        model.fit(xtr, ytr)
        thresholds[name] = _best_f1_threshold(yva, model.predict_proba(xva)[:, 1])
        metrics[name] = _metrics(yte, model.predict_proba(xte)[:, 1], thresholds[name])
    primary = candidates["lightgbm"]
    calib = []
    p = primary.predict_proba(xte)[:, 1]
    for lo in np.linspace(0, 0.9, 10):
        m = (p >= lo) & (p < lo + 0.1)
        if m.any():
            calib.append({"bin": f"{lo:.1f}-{lo + 0.1:.1f}", "n": int(m.sum()),
                          "mean_pred": round(float(p[m].mean()), 4), "observed": round(float(yte[m].mean()), 4)})
    metrics["lightgbm_calibration"] = calib
    artifact = primary.booster_.model_to_string()
    return {
        "name": "spi-board-risk", "algorithm": "lightgbm", "label_kind": "SYNTHETIC_LABEL", "seed": seed,
        "train_data_sha256": sha256_json(rows),
        "feature_schema_sha256": sha256_json({"version": FEATURE_VERSION, "features": FEATURES}),
        "features": FEATURES,
        "split": {"method": "time-ordered panels 60/15/25", "group": "panel_id",
                  "generator": GENERATOR_VERSION,
                  "panels": {k: len({r["panel_id"] for r in v}) for k, v in parts.items()},
                  "boards": {k: len(v) for k, v in parts.items()},
                  "test_from": min(r["produced_at"] for r in parts["test"])},
        "metrics": metrics, "threshold": thresholds["lightgbm"], "artifact_text": artifact,
        "artifact_sha256": hashlib.sha256(artifact.encode()).hexdigest(),
        "library_versions": {"lightgbm": lightgbm.__version__, "scikit-learn": sklearn.__version__,
                             "numpy": np.__version__},
    }


def predict_explain(artifact_text: str, features: dict) -> dict:
    """Score one board and attribute the raw (log-odds) score to features with exact TreeSHAP."""
    booster = lightgbm.Booster(model_str=artifact_text)
    x = np.array([[features[k] for k in FEATURES]])
    raw = float(booster.predict(x, raw_score=True)[0])
    contrib = booster.predict(x, pred_contrib=True)[0]
    baseline = float(contrib[-1])
    contributions = {k: float(v) for k, v in zip(FEATURES, contrib[:-1], strict=True)}
    return {"risk_score": 1 / (1 + math.exp(-raw)), "raw_score": raw, "baseline": baseline,
            "contributions": contributions,
            "additivity_error": abs(baseline + sum(contributions.values()) - raw)}


def model_card(mv: dict) -> str:
    m = mv["metrics"]
    rows = "\n".join(f"| {k} | {v['pr_auc']} | {v['roc_auc']} | {v['brier']} | {v['threshold']} | "
                     f"{v['precision']} | {v['recall']} |" for k, v in m.items() if k != "lightgbm_calibration")
    calib = "\n".join(f"| {c['bin']} | {c['n']} | {c['mean_pred']} | {c['observed']} |"
                      for c in m["lightgbm_calibration"])
    test = m["lightgbm"]
    return f"""# Model card — {mv['name']} ({mv['algorithm']})

**Synthetic only.** Label kind `{mv['label_kind']}`: generator ground truth exposed as operator
DEFECT_CONFIRMED in seeded synthetic data (`{GENERATOR_VERSION}`, seed {mv['seed']}). These numbers
describe behaviour on synthetic data and are **not** industrial performance claims.

- Purpose: rank boards for SPI-based review priority inside a quality case. Not a pass/fail decision.
- Predictor input: SPI solder volume only, as available when SPI runs. AOI, operator verification and
  repair records are post-hoc and are structurally rejected by `board_features` (leakage test).
- Features ({FEATURE_VERSION}): {', '.join(mv['features'])}
- Split: {mv['split']['method']}, grouped by {mv['split']['group']}; panels {mv['split']['panels']},
  boards {mv['split']['boards']}; test starts {mv['split']['test_from']}. Threshold = best F1 on validation.
- Test set: n={test['n']}, positives={test['positives']}.

| model | PR-AUC | ROC-AUC | Brier | threshold | precision | recall |
|---|---|---|---|---|---|---|
{rows}

Calibration (LightGBM, test):

| score bin | n | mean predicted | observed rate |
|---|---|---|---|
{calib}

Explanations: `{XAI_METHOD}` — exact TreeSHAP in log-odds; baseline = expected raw score; the server
records the additivity error per prediction. **SHAP attributes the model's score to inputs; it is not
evidence of a physical defect cause.**

Hashes: train data `{mv['train_data_sha256']}`, feature schema `{mv['feature_schema_sha256']}`,
artifact `{mv['artifact_sha256']}`. Libraries: {mv['library_versions']}.
"""
