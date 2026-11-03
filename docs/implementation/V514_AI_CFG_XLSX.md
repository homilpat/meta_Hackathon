# v5.14 §29 AI-CFG-01/02 — unregistered inspection XLSX (2026-11-03)

## Flow

1. **Upload.** No form needs to be registered first.
2. **Route.** The server finds the table candidates (`app/inspection_layout.tables`). It covers visible sheets, merged cells filled across their range, two- and three-row headers joined with ` / `, and blocks separated by blank rows. "Supplier: ACME" lines above a table are not a header. The preview then takes one of three routes:
   - **`REUSED`** — a mapping a person confirmed for exactly this structure. The structure sha covers the sheet, the header rows and each column's header words, not the data.
   - **`FORM`** — exactly one table, and a registered form's header words name all required fields.
   - **`NEEDS_AI`** — none of the above. The reasons are `NO_HEADER`, `REQUIRED_NOT_MAPPED`, `MULTIPLE_TABLES`, `STRUCTURE_CHANGED` or `REUSE_CONFLICT`.
3. **AI proposal** (`POST /intakes/{i}/files/{f}/inspection/proposals`). One Meta call under a strict JSON schema.
   - **Sent:** header texts and per-column type counts, never cell values. Headers are masked when the file is protected.
   - **Allowed in the reply:** the candidate ids found by the server, that candidate's columns plus `NONE`, and the known fields.
   - **Server checks:** an unknown candidate gives `INVALID`. A column outside the candidate gives `OUT_OF_RANGE`. A column used twice gives `DUPLICATE_MAPPING`, and both fields are held. Missing required fields give `REQUIRED_NOT_MAPPED`.
   - **Record:** every call is kept in `inspection_mapping_proposals` (append-only), with what was sent, the reply, the verdict and the usage.
   - **No model or a failed call:** the status is `OFFLINE` or `FAILED`, and the manual mapping on the best candidate stays open.
4. **Fields a person must confirm** (`layout.uncertain`). These are only the fields a count check cannot decide:
   - an accepted/good column mapped to defective;
   - a defective header without a reject meaning;
   - an accepted or rejected column mapped to inspected;
   - anything the model left unresolved.

   Each one shows its header context and the original cells side by side with the other count columns. LOT leading zeros and cell addresses are kept, because `inspection_xlsx.read` reads the file again.
5. **Save** (`POST …/inspection/mapping`, AUTHOR). The server refuses unconfirmed uncertain fields and re-checks the mapping. It saves a new `inspection_forms` version with source `CONFIRMED`, the structure and its sha, the mapping, the proposal id and `edits` (fields changed from the proposal).
6. **Next file with the same structure.** It is `REUSED` with no model call. A saved mapping is never applied to another structure (422). A changed structure or two saved mappings go back to review.
7. **Import into a case.** This is unchanged (§28 confirm). The screen allows it only after the mapping is saved.

## Reproduce

Run from `backend/`.

**Tests**

```
python -m pytest tests/test_inspection_ai_mapping.py      # TEST_DOUBLE: flow, reuse, review, failures
```

**Demo**

```
python -m scripts.xlsx_samples fixtures                    # (already committed) demo files A and B
python -m scripts.xlsx_map_eval demo --double              # upload A -> NEEDS_AI -> proposal -> save -> B REUSED
QO_EVAL_LIVE_BUDGET_USD=0.1 python -m scripts.xlsx_map_eval demo --live
```

**Comparison**

```
python -m scripts.xlsx_map_eval collect --live             # (budget env as above) 12 samples, one call each
python -m scripts.xlsx_map_eval score
```

**On screen**

1. In 접수, upload `src/app/fixtures/intake/unregistered_inspection_SN-0300_A.xlsx`.
2. Click "검사 결과로 읽기". The badge shows "AI 제안·검토 필요".
3. Click "AI 열 연결 제안 받기".
4. Check the cells of any asked field.
5. Give a reason and click "확인한 열 연결 저장".
6. Link the rows to a case.
7. Upload `…_B.xlsx`. The badge shows "저장된 매핑 재사용".

## Results (LIVE, muse-spark-1.3, 12 synthetic samples, 36 required fields)

The gold mapping was written in `scripts/xlsx_samples.py` before any run. Reports are `docs/evaluations/ev/xlsx_map_eval_LIVE.json` and `xlsx_demo_LIVE.json`. TEST_DOUBLE results are in separate files.

| | rules alone | AI proposal |
|---|---|---|
| required accuracy | 0.389 (14/36) | 1.000 (36/36) |
| hold rate | 0.611 | 0.028 (1/36: the file has no defective column, so holding it is right) |
| edits a person must make | 22 | 0 |
| right table | 10/12 | 12/12 |

- **Cost:** $0.11 for the comparison and about $0.01 for the demo. One call took 25 s.
- **Where rules alone failed:** headers with punctuation, abbreviations, Japanese, `Batch`/`Checked`/`NG`, merged two-row headers, a second table, and a second sheet.
- **Demo (LIVE):** A was `NEEDS_AI` (`REQUIRED_NOT_MAPPED`). Meta proposed lot A, date B, inspected C and defective E (불합격). Nothing was asked and 0 edits were made. After the save, B was `REUSED` with the same mapping and no second proposal. B's own values (LOT 00521–00523, defective 9/0/5) were read, not A's.

## Protected files: header language read on the server (user decision 2026-11-03)

- **What leaves:** a protected file's headers still go masked, but the server first reads their languages by script
  (Hangul, kana, kanji, Latin). It never sends a header to find out. The inspection terms of those languages stay
  readable, and so do words built only from terms ("검사일자" = 검사 + 일자). The terms are the limits
  `XLSX_HEADER_TERMS_EN/KO/JA/ZH` (DECISION; AGENT_ADMIN may change them at `POST /limits`). Every other word becomes
  a token, CJK included.
- **Gap found and fixed:** `egress.Masker` did not mask kana or kanji, so Japanese and Chinese words in protected
  intake documents left the server as they were. It masks them now.

Same 12 samples, LIVE, protected (headers masked):

| | allow list only (before) | language + terms (now) | not masked |
|---|---|---|---|
| required accuracy | 0.944 | 1.000 | 1.000 |
| hold rate | 0.333 | 0.028 | 0.028 |
| edits | 2 (defective mapped to an Accepted column, twice; both were asked) | 0 | 0 |
| cost | $0.21 | $0.13 | $0.11 |

Reports: `xlsx_map_eval_MASKED_LIVE_allowlist.*` (before) and `xlsx_map_eval_MASKED_LIVE.*` (now).

## Not verified

- **Review time:** needs people.
- **Real company files:** none were provided. Twelve samples is a small denominator.
- **Languages beyond KO, EN, JA and ZH:** their headers are masked whole, so the proposal falls back to column types.
- **AI-CFG-03 (PDF/DOCX reading choice) and AI-CFG-04 (operations-setting proposals):** follow-ups, not built.
