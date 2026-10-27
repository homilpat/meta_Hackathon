# Model card — spi-board-risk (lightgbm)

**Synthetic only.** Label kind `SYNTHETIC_LABEL`: generator ground truth exposed as operator
DEFECT_CONFIRMED in seeded synthetic data (`s4-train-1`, seed 11). These numbers
describe behaviour on synthetic data and are **not** industrial performance claims.

- Purpose: rank boards for SPI-based review priority inside a quality case. Not a pass/fail decision.
- Predictor input: SPI solder volume only, as available when SPI runs. AOI, operator verification and
  repair records are post-hoc and are structurally rejected by `board_features` (leakage test).
- Features (spi-board-v1): n_pins, vol_mean, vol_std, vol_min, vol_max, vol_range, vol_abs_dev_max, frac_out_of_spec
- Split: time-ordered panels 60/15/25, grouped by panel_id; panels {'train': 144, 'valid': 36, 'test': 60},
  boards {'train': 576, 'valid': 144, 'test': 240}; test starts 2026-01-08T12:00:00+00:00. Threshold = best F1 on validation.
- Test set: n=240, positives=30.

| model | PR-AUC | ROC-AUC | Brier | threshold | precision | recall |
|---|---|---|---|---|---|---|
| dummy_prior | 0.125 | 0.5 | 0.1095 | 0.1372 | 0.0 | 0.0 |
| logistic_regression | 0.7223 | 0.8998 | 0.0597 | 0.3487 | 0.6786 | 0.6333 |
| lightgbm | 0.66 | 0.8463 | 0.0778 | 0.8871 | 0.7143 | 0.5 |

Calibration (LightGBM, test):

| score bin | n | mean predicted | observed rate |
|---|---|---|---|
| 0.0-0.1 | 201 | 0.0055 | 0.0448 |
| 0.1-0.2 | 4 | 0.1261 | 0.0 |
| 0.2-0.3 | 5 | 0.2401 | 0.4 |
| 0.3-0.4 | 2 | 0.3598 | 0.5 |
| 0.5-0.6 | 3 | 0.5588 | 0.6667 |
| 0.6-0.7 | 2 | 0.6049 | 0.0 |
| 0.8-0.9 | 3 | 0.8811 | 0.6667 |
| 0.9-1.0 | 20 | 0.9807 | 0.7 |

Explanations: `lightgbm_pred_contrib_treeshap` — exact TreeSHAP in log-odds; baseline = expected raw score; the server
records the additivity error per prediction. **SHAP attributes the model's score to inputs; it is not
evidence of a physical defect cause.**

Hashes: train data `0dcc4e382d7a01cf961eea594b9233c2bd5e67797afbd75bb581647973ca813e`, feature schema `b2f209215a93ae445a4492ee75eee4d60611cb3b0bf6826e786342b28a93ea6d`,
artifact `0730a401075e07655e7df123d1b71ae3893aeb04f9580528153cf1f44bb3fe1c`. Libraries: {'lightgbm': '4.7.0', 'scikit-learn': '1.9.1', 'numpy': '2.5.4'}.
