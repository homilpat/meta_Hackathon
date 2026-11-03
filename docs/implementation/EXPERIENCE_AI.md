# Experience Memory with Meta (user decision 2026-11-03)

The rule path is unchanged:
1. scope and access first;
2. BM25 over the earlier case's text, with the multilingual glossary;
3. the structured factor gate (SPI pattern / equipment condition);
4. modes from records: KNOWN only when the effect is verified, there is no recurrence and every applicability check passes now.

`POST /cases/{c}/experience/retrievals {"ai": true}` adds two steps (`app/experience.py: ai_retrieve`):

| Step | Meta | Server |
|---|---|---|
| Read what words missed | Reads only the entries that passed scope, access and the factor gate but share no word with the case (`NO_SHARED_WORD`, at most `MAX_MISSES`=20). It picks those that describe the same problem, by server id (strict enum), with a reason. | Keeps only ids it listed and retrieves again with them (`include`). Their mode still comes from their records. Each match is marked `found_by` RULES / AI_MATCH. |
| Compare | For each match: which listed conditions hold or differ, KNOWN/ANALOGICAL, a note. | Compares each claim with its own applicability checks and names every disagreement. The mode is never changed by the AI. |

- **What is sent:** the case's structured factors, the problem text and the candidates' texts. They are masked except the language's terms when the case is not synthetic.
- **Model failure:** the rule result stands.
- **UI:** "AI로 넓혀 찾기 · 비교" on the Experience card, with an "AI가 같은 문제로 고름" badge and reason, and a "기록과 다름" badge with the disagreements.

## Why not search-term expansion

It was tried first and measured LIVE: recall stayed at 2/6. Meta gave standard terms (솔더 부족, ペースト不足) while the records use shop-floor wording (땜이 덜 묻어나옴, ペースト塗布が薄い). Japanese and Chinese have no spaces, so BM25 compares whole runs. Reading the missed candidates removes both problems.

## Result

Reproduce from `backend/`: `python -m scripts.experience_eval --live`. Reports: `docs/evaluations/ev/experience_eval_LIVE.json` (and `_TEST_DOUBLE`).

The set is the synthetic line case L plus 7 earlier cases written first with their gold:
- **K1–K5:** same problem. K1/K2/K4 are in Korean, Japanese or English shop-floor wording with no shared word. K3/K5 share glossary terms.
- **N1:** same problem, but the response recurred (negative precedent).
- **D1:** similar words, different conditions; it must not appear.

| | rules alone | rules + Meta |
|---|---|---|
| same-problem cases found | 2/6 | 6/6 |
| false KNOWN | 0 | 0 |
| D1 shown | no | no |
| N1 kept as a warning | not found | yes |

- **Cost:** 2 calls, $0.036.
- **The compare step:** Meta proposed KNOWN for 4 negative or recurred precedents, and the server held all of them at ANALOGICAL with "기록과 다름". Meta's own mode is not reliable, which is why the server keeps it.

## Not verified

- Real case history: none was provided, and 7 synthetic entries is a small denominator.
- A case history larger than `MAX_MISSES` per retrieval.
