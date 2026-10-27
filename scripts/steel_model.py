"""Real public data check of the S4 model/XAI method: UCI Steel Plates Faults (CC BY 4.0), fault TYPE classification.

Downloads the official ZIP into git-ignored data/uci/, refuses it unless the SHA-256 matches the S1 record,
trains LightGBM vs baselines on a stratified split and reports per-class TreeSHAP importance.
Writes docs/STEEL_MODEL_CARD.md and docs/steel_eval.json (metrics and aggregates only, no source rows).
Every row is a defective plate, so this cannot measure defect detection or a defect rate.
Run: python -m scripts.steel_model
"""

import hashlib
import io
import json
import zipfile
from pathlib import Path
from urllib.request import urlopen

import lightgbm
import numpy as np
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, log_loss
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

URL = "https://archive.ics.uci.edu/static/public/198/steel+plates+faults.zip"
SHA256 = "cb8eb9859198b63f053e443513036b401746fa517ef58bd17c846c6741c93919"  # recorded in S1
CACHE = Path("data/uci/steel_plates_faults.zip")
FEATURES = ["X_Minimum", "X_Maximum", "Y_Minimum", "Y_Maximum", "Pixels_Areas", "X_Perimeter", "Y_Perimeter",
            "Sum_of_Luminosity", "Minimum_of_Luminosity", "Maximum_of_Luminosity", "Length_of_Conveyer",
            "TypeOfSteel_A300", "TypeOfSteel_A400", "Steel_Plate_Thickness", "Edges_Index", "Empty_Index",
            "Square_Index", "Outside_X_Index", "Edges_X_Index", "Edges_Y_Index", "Outside_Global_Index",
            "LogOfAreas", "Log_X_Index", "Log_Y_Index", "Orientation_Index", "Luminosity_Index", "SigmoidOfAreas"]
CLASSES = ["Pastry", "Z_Scratch", "K_Scatch", "Stains", "Dirtiness", "Bumps", "Other_Faults"]
SEED = 11
ATTRIBUTION = ("Buscema, M., Terzi, S., & Tastle, W. (2010). Steel Plates Faults [Dataset]. UCI Machine Learning "
               "Repository. https://doi.org/10.24432/C5J88N — CC BY 4.0. Modified: parsed and used to train/evaluate "
               "a classifier; no rows are redistributed.")


def load() -> tuple[np.ndarray, np.ndarray, int]:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(URL, timeout=60) as r:
            CACHE.write_bytes(r.read())
    raw = CACHE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise SystemExit(f"SHA-256 mismatch for {CACHE}; not using it (expected the S1-recorded archive)")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = next(n for n in z.namelist() if n.endswith("Faults.NNA"))
        rows = np.loadtxt(io.StringIO(z.read(name).decode()))
    if rows.shape != (1941, 34) or not (rows[:, 27:].sum(axis=1) == 1).all():
        raise SystemExit(f"unexpected layout {rows.shape}; expected 1941x34 with one-hot labels")
    return rows[:, :27], rows[:, 27:].argmax(axis=1), len(raw)


def main() -> None:
    x, y, size = load()
    x_tmp, x_test, y_tmp, y_test = train_test_split(x, y, test_size=0.2, stratify=y, random_state=SEED)
    x_train, x_valid, y_train, y_valid = train_test_split(x_tmp, y_tmp, test_size=0.25, stratify=y_tmp,
                                                          random_state=SEED)
    models = {
        "majority_class": DummyClassifier(strategy="most_frequent"),
        "logistic_regression": make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000)),
        "lightgbm": lightgbm.LGBMClassifier(n_estimators=400, learning_rate=0.05, num_leaves=15,
                                            random_state=SEED, verbose=-1),
    }
    metrics, preds = {}, {}
    for name, m in models.items():
        fit = {"eval_set": [(x_valid, y_valid)], "callbacks": [lightgbm.early_stopping(30, verbose=False)]} \
            if name == "lightgbm" else {}
        m.fit(x_train, y_train, **fit)
        p = m.predict_proba(x_test)
        preds[name] = p.argmax(axis=1)
        metrics[name] = {"accuracy": round(accuracy_score(y_test, preds[name]), 4),
                         "macro_f1": round(f1_score(y_test, preds[name], average="macro"), 4),
                         "log_loss": round(log_loss(y_test, p, labels=range(7)), 4)}
    lgb = models["lightgbm"]
    per_class_f1 = dict(zip(CLASSES, (round(v, 4) for v in f1_score(y_test, preds["lightgbm"], average=None)),
                            strict=True))
    contrib = lgb.booster_.predict(x_test, pred_contrib=True).reshape(len(x_test), 7, 28)
    additivity = float(np.abs(contrib.sum(axis=2) - lgb.booster_.predict(x_test, raw_score=True)).max())
    shap = {c: sorted(((FEATURES[f], round(float(np.abs(contrib[:, k, f]).mean()), 4)) for f in range(27)),
                      key=lambda kv: -kv[1])[:5] for k, c in enumerate(CLASSES)}
    result = {
        "source": URL, "archive_sha256": SHA256, "archive_bytes": size, "attribution": ATTRIBUTION,
        "data_origin": "REAL", "task": "7-class steel plate fault TYPE classification (all rows are faulty)",
        "rows": {"total": len(y), "train": len(y_train), "valid": len(y_valid), "test": len(y_test)},
        "class_counts": dict(zip(CLASSES, np.bincount(y, minlength=7).tolist(), strict=True)),
        "split": f"stratified random 60/20/20, seed {SEED} (no timestamps or plate ids in the source)",
        "metrics_test": metrics, "lightgbm_per_class_f1": per_class_f1,
        "lightgbm_best_iteration": int(lgb.best_iteration_ or lgb.n_estimators),
        "confusion_matrix_test": {"labels": CLASSES, "rows_true_cols_pred":
                                  confusion_matrix(y_test, preds["lightgbm"], labels=range(7)).tolist()},
        "shap": {"method": "lightgbm_pred_contrib_treeshap", "max_additivity_error": additivity,
                 "top5_mean_abs_by_class": shap},
        "versions": {"lightgbm": lightgbm.__version__, "scikit-learn": sklearn.__version__, "numpy": np.__version__},
    }
    Path("docs/steel_eval.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    mrows = "\n".join(f"| {k} | {v['accuracy']} | {v['macro_f1']} | {v['log_loss']} |" for k, v in metrics.items())
    srows = "\n".join(f"| {c} | {per_class_f1[c]} | {result['class_counts'][c]} | "
                      + ", ".join(f"{f} {v}" for f, v in shap[c]) + " |" for c in CLASSES)
    Path("docs/STEEL_MODEL_CARD.md").write_text(f"""# Model card — steel fault type classifier (REAL public data)

Generated by `python -m scripts.steel_model`. Raw output: `docs/steel_eval.json`.

**Purpose:** show that the S4 method (LightGBM + TreeSHAP, baselines, held-out test) works on real manufacturing
inspection data, not only on the synthetic PCB generator. It is a separate reference model: it is not used on
PCB cases, and its data never enters a case or a Meta prompt (`data_origin=REAL` is blocked by the egress gate).

**Data:** {ATTRIBUTION}
Archive SHA-256 `{SHA256}` ({size} bytes, verified against the S1 record; the ZIP stays in git-ignored `data/`).
{len(y)} plates, 27 numeric features, 7 fault types. **Every row is a faulty plate**, so the task is fault *type*
classification; it says nothing about detecting faulty vs good plates or about defect rates.

**Split:** {result['split']}. Train {len(y_train)}, validation {len(y_valid)} (early stopping only), test {len(y_test)}.
The source has no plate or time ids, so rows from the same plate or period may sit on both sides of the split;
test scores may be optimistic for a new production period.

## Test metrics

| model | accuracy | macro F1 | log loss |
|---|---|---|---|
{mrows}

## Per class (LightGBM) and largest mean |SHAP| (log-odds of that class)

| fault type | test F1 | rows (all) | top features by mean abs SHAP |
|---|---|---|---|
{srows}

SHAP max additivity error {additivity:.2e}. SHAP shows which inputs moved this model's class score; it is not a
physical cause of the fault. Versions: {result['versions']}.
""", encoding="utf-8")
    print(json.dumps({"bytes": size, "test": metrics, "per_class_f1": per_class_f1}))


if __name__ == "__main__":
    main()
