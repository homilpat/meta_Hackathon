# v5.14 §29 AI-CFG-03 — PDF/DOCX read method chosen by Meta (2026-11-03)

`EXTRACT_MODE = AI_CHOICE` (`app/intake_extract.py: ai_choice`). The default stays `WHOLE_FIRST`, by user decision on 2026-11-03.

How it works:
- **The server narrows first.** WHOLE is a candidate only when every element fits one call (context window and cost cap). With HYBRID as the only candidate, no model is asked.
- **Meta picks between two candidates.** It sees each document's structure (element counts by kind, pages, images) and both estimates (tokens, calls, USD), never the text. The answer is a strict enum, with a reason.
- **Fallback.** An answer outside the candidates, or a failed call, falls back to WHOLE_FIRST's rule.
- **Recorded.** The method, `proposed_by` (AI or SERVER_RULE) and the reason are stored on every file it applied to (`egress.files[].read_method`, `egress.auto`).
- **Policies unchanged.** Processing limits and egress policy are the same as before.

## Measured (LIVE, muse-spark-1.3)

- **Fixtures.** The 4 synthetic intake document sets (`scripts/fixture_eval.py --mode AI_CHOICE`) all read WHOLE. Extraction stayed fully right (dev 99/99, validation 51/51). Choice calls cost $0.015.
- **Decision quality on recorded outcomes** (`scripts/read_choice_eval.py`, 20 CUAD contracts read both ways in earlier LIVE runs, $0.10):

  | | WHOLE_FIRST rule | AI_CHOICE |
  |---|---|---|
  | chose the better (or a tied) method | 19/20 | 19/20 (the same choice on all 20) |
  | recall lost against the better method | 0.125 | 0.125 |
  | estimated extraction cost of the choices | $2.097 | $2.097 |

**Conclusion:** no gain here, and one extra call per document. AI_CHOICE remains an option AGENT_ADMIN can set at `POST /limits/EXTRACT_MODE`.

**Not measured:** documents where the choice would matter, i.e. long and mostly irrelevant but still fitting one call. Real company documents have not been tried.
