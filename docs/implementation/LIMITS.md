# Operating limits: values, where they come from, who changes them

All limits live in `backend/src/app/limits.py` and are served with their basis at `GET /limits` (shown in 감사 · 보안).
Only the AI operations department (role `AGENT_ADMIN`, demo user `gina`) changes them, at `POST /limits/{name}` with a
reason. Changes are append-only (`limit_settings`, migration 0024) and replayed at start. Precedence: recorded
setting > `QO_<NAME>` environment variable > default. `MAX_FILES_PER_UPLOAD` and `MAX_REQUEST_ITEMS` are bound into
request schemas, so a change takes effect after a restart.

| Limit | Default | Basis | Source |
|---|---|---|---|
| MAX_UPLOAD_BYTES | 10 MB | DECISION | user, 2026-11-01 |
| MAX_FILES_PER_UPLOAD | 5 | DEFAULT | arbitrary starting value, set by the owner |
| MAX_COMPRESSION_RATIO | 100 | STANDARD | zip-bomb guidance "ratio < 100:1". Sonar RSPEC-5042's example uses 10, but ordinary DOCX measured here reach 24× in total and 32× per entry |
| MAX_ZIP_ENTRIES | 10,000 | STANDARD | Sonar RSPEC-5042 THRESHOLD_ENTRIES |
| MAX_UNZIPPED_BYTES | 1 GB | DERIVED | upload limit × compression ratio (= Sonar THRESHOLD_SIZE) |
| PARSE_TIME_BUDGET_S | 50 s | DERIVED | provider timeout 60 s − LIVE extraction p95 ≈ 10 s. Parsing stops there and the rest is reported as unprocessed (replaces fixed page, cell and row caps) |
| MAX_IMAGES_PER_CALL | 9 | STANDARD | Llama API documented 9 images per request. muse-spark-1.3 accepted and read 10 in a probe |
| MODEL_CONTEXT_TOKENS | 1,048,576 | STANDARD | Meta Model API docs: muse-spark context window |
| MODEL_PRICE_INPUT/OUTPUT_PER_M_USD | 1.25 / 4.25 | STANDARD | api.meta.ai published price for muse-spark-1.1 (1.3 not separately confirmed) |
| MAX_COST_PER_MODEL_CALL_USD | 0 (off) | DECISION | user, 2026-11-01: the context window is the cap; a cost cap is optional, set from the budget |
| EXTRACT_MAX_ROUNDS | 2 | DEFAULT | arbitrary starting value: round 2 asks only for missing fields with their next candidate parts; each round is a paid call |
| max input tokens | 1,040,384 | DERIVED | context − 8,192 output reserve (or the cost cap ÷ input price, when one is set). Prompt, schema, document elements (in document order) and images count against it; what is left is reported "not sent to the model from …" |
| BYTES_PER_TOKEN | 4 | STANDARD | rule of thumb (about 4 characters per token for English); conservative for Korean |
| IMAGE_TOKENS | 390 | MEASURED | one LIVE run: 2,414 prompt tokens = 790 text + 362 prompt + 481 schema + 2 images. Calibration from that run, not an independent check. Every call now records its real usage (`egress.usage`, request review events), so it can be recalibrated |
| EXTRACT_REASONING_EFFORT | minimal | MEASURED | LIVE: minimal 8/8 and 7/8 at 7–8 s, default 8/8 at 19.5 s. The owner chooses speed vs completeness |
| MODEL_TEMPERATURE | 0 | DECISION | user, 2026-11-02: as repeatable as the model allows. Muse accepts 0–2 with API default 1.0 according to the LiteLLM and promptfoo provider docs (not yet confirmed on api.meta.ai). 0 narrows run-to-run change but does not remove it |
| MODEL_SEED | 1 | DEFAULT | any fixed integer (the value does not matter, only that it stays the same); 0 = not sent, for a model that refuses it |
| MODEL_RESPONSE_REUSE | ON | DECISION | user, 2026-11-02: an identical request (model, messages, tools, schema, effort, temperature, seed) gets the stored answer (`model_responses`, migration 0025) instead of a new call; errors are never stored; OFF calls anew |
| EXTRACT_COMPLETION_TOKENS_PER_CALL | 1,274 | MEASURED | CUAD held-out LIVE: 62,409 completion tokens / 49 calls (AUTO's output estimate) |
| TOKENS_PER_ESTIMATE_TEXT | 1.34 | MEASURED | CUAD held-out LIVE, WHOLE: actual / byte-estimated prompt tokens |
| TOKENS_PER_ESTIMATE_MAP | 2.3 | MEASURED | CUAD held-out LIVE, HYBRID: maps are word lists and cost more per byte |
| MODEL_RUNS_PER_USER_HOUR | 30 | DEFAULT | arbitrary starting value, to be set from the company's model budget |
| MAX_RECOMMENDATIONS | 3 | DEFAULT | screen default |
| MIN_RECOMMENDATION_GRADE | B | DECISION (proposed) | A = matches a past case whose effect was verified, B = controlled document or unverified case, C = this case's data only (folded as 참고). Grades come from the sources, never from a model's confidence (spec §23.3) |
| MAX_INTAKE_QUESTIONS | 8 | DEFAULT | screen default |
| MAX_REQUEST_ITEMS | 20 | DEFAULT | screen default |
| ALLOWED_TIMEZONES | Asia/Seoul + US Eastern/Central/Mountain/Pacific | DECISION | user, 2026-11-01: Korea and the US. IANA names only, plus `KST`; no ambiguous abbreviations (CST, EST) |

Not limits but derived from the format: PDF table rows group runs whose baselines are less than 0.6 × the font size
apart (half a line at the usual 1.2 line height), and columns group left edges within 0.5 × the font size (about
one glyph). Renders are at one PDF point per pixel. Text lengths use the shared `app.fields` definitions. The
summary rewrite may have at most one line per server fact.

## Measurements (`python -m scripts.measure_limits` → `docs/evaluations/limits_measure.json`)

Throughput on this machine: PDF with render about 69 pages/s, XLSX about 19,000 rows/s, CSV about 300,000 rows/s.
A 10 MB XLSX (about 18 s) and CSV (about 1 s) fit the 50 s budget. A 10 MB text-only PDF (about 11,000 pages) does
not: about 3,400 pages are processed and the rest is reported as unprocessed. The measurements depend on the
machine, so run the script again on the target server before changing the budget.

## How documents reach the model (EXTRACT_MODE)

**Hybrid policy WHOLE_FIRST (default since 2026-11-02, user decision after the CUAD LIVE runs).** It chooses between the two ways of reading: full reading (WHOLE) and navigation reading (code value `HYBRID`).
- Every element is read in one call when it fits: within the model's input and, when the owner sets one, `MAX_COST_PER_MODEL_CALL_USD`.
- Only beyond that does the document go HYBRID.
- The split is the money per call the owner allows, not a page count.
- Why:
  - WHOLE read every answer page.
  - HYBRID never read about 21% of them on long contracts and sometimes lost several answers.
  - Below about 25 pages WHOLE was also cheaper.
  - Measurements: [EV_LOCAL_EVAL.md](../evaluations/EV_LOCAL_EVAL.md).

**Navigation reading (`HYBRID`; used beyond one call or when chosen).**
1. The server sends a first selection: the document head; captions, charts and scans; and per field the best BM25
   hit for its label words, with its table row, header and column.
2. It also sends a map of each document (`app/doc_map.py`):
   - the author's table of contents (PDF bookmarks, DOCX heading styles, contents pages);
   - heading candidates: lines standing alone, shorter than the document's median line, not ending like a
     sentence, and not repeated across pages (repeats are boilerplate);
   - per page or section: the first line, table headers, captions, and the words found in no other part (the
     TF-IDF idea).
3. The model asks for the parts it still needs (`need`, at most HYBRID_MAX_PARTS_PER_ROUND per round, up to
   EXTRACT_MAX_ROUNDS), and the server sends only those.
4. What stays unread is shown with the fields not found. A person can re-run the analysis reading everything
   (`POST /intakes/{id}/analyze?read=WHOLE`). Nothing is read in full automatically.

**WHOLE.** Every element, in pieces when the documents exceed the model's input.

**AUTO.** WHOLE unless HYBRID is cheaper even at its most expensive, estimated before any call; the estimate and choice are recorded with the extraction (`egress.auto`). Measured on CUAD: [EV_LOCAL_EVAL.md](../evaluations/EV_LOCAL_EVAL.md).

No hand-written value patterns decide what is sent. Values are always checked against their source location.

| Measured | Result |
|---|---|
| Offline, server first pass only, held-out H1/H2/H3 | 3/6, 6/6, 4/6 (the model's requests have to fill the rest) |
| LIVE HYBRID, held-out (never used for tuning) | H1 6/6 at 12,636 prompt tokens; H2 6/6 at 2,313; H3 6/6 at 8,729 |
| LIVE WHOLE, same documents | 6/6 each, at 51,766 / 1,542 / 38,240 |

Limits:
- The held-out documents are synthetic, one per layout.
- HYBRID takes a second call when it needs parts (about 9–10 s vs 7–8 s).
- A document whose values leave no trace in the map can still be missed. The unread notice and the whole-read
  button are for that case.
