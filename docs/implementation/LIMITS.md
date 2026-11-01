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
| MAX_COST_PER_MODEL_CALL_USD | 0.10 | DEFAULT | arbitrary starting value, set from the company's model budget |
| max input tokens | 80,000 | DERIVED | min(context − 8,192 output reserve, cost cap ÷ input price). Prompt, schema, document elements (in document order) and images count against it; what is left is reported "not sent to the model from …" |
| BYTES_PER_TOKEN | 4 | STANDARD | rule of thumb (about 4 characters per token for English); conservative for Korean |
| IMAGE_TOKENS | 390 | MEASURED | one LIVE run: 2,414 prompt tokens = 790 text + 362 prompt + 481 schema + 2 images. Calibration from that run, not an independent check. Every call now records its real usage (`egress.usage`, request review events), so it can be recalibrated |
| EXTRACT_REASONING_EFFORT | minimal | MEASURED | LIVE: minimal 8/8 and 7/8 at 7–8 s, default 8/8 at 19.5 s. The owner chooses speed vs completeness |
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
