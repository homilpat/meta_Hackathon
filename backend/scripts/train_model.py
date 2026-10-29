"""Train the SPI risk model reproducibly and write docs/evaluations/MODEL_CARD.md with the measured numbers.

Run from the repository root: python -m scripts.train_model [--seed 11]
"""

import argparse

from app import EVAL_DIR, ml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()
    trained = ml.train(args.seed)
    (EVAL_DIR / "MODEL_CARD.md").write_text(ml.model_card(trained), encoding="utf-8")
    print(f"artifact {trained['artifact_sha256']} data {trained['train_data_sha256']}")
    for name, m in trained["metrics"].items():
        if name != "lightgbm_calibration":
            print(f"{name}: PR-AUC {m['pr_auc']} ROC-AUC {m['roc_auc']} P {m['precision']} R {m['recall']}")


if __name__ == "__main__":
    main()
