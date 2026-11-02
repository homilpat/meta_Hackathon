# Plan: measuring the document reading on real documents (CUAD)

Status: implemented as `backend/scripts/cuad_eval.py` (spec §26.7); results and what is NOT_RUN in [EV_LOCAL_EVAL.md](EV_LOCAL_EVAL.md).

## Why

The held-out documents H1–H3 are synthetic and were written by the same author as the selector, so they may favour
it. CUAD (Contract Understanding Atticus Dataset, CC BY 4.0) gives real, long documents with expert-marked answer
spans:
- 510 contract PDFs
- 41 clause categories each
- SQuAD-style JSON with the answer texts

Source: zenodo.org/record/4595826 (CUAD_v1.zip, 105.9 MB). The data is kept outside the repository. Only result
numbers are committed, and CUAD is credited.

## Sample

- 10 contracts, chosen by a fixed seed from those with at least 10 PDF pages (so finding parts matters).
- 5 categories per contract: Parties, Agreement Date, Governing Law, Expiration Date, Termination For Convenience.
- Each category gets its own label words for the server's first pass (`FIELD_LABELS`-style, kept in the evaluation
  script and not added to the product).

## Conditions (ablation)

| | Map given to the model | What it shows |
|---|---|---|
| A | full map: author contents, heading candidates, per part first line, table headers, captions, unique words | the product as it runs |
| B | map without contents and heading candidates (unique words, first lines, table headers only) | documents without structure. Contract clause titles often name the category, so A may look better than the search really is |
| C | WHOLE (every element) | the accuracy ceiling and the token cost |

## Metrics (deterministic, no LLM grading)

- **Page recall:** the share of answer spans whose page was among the parts the model read (round 1 and later),
  for A and B. The answer page is found by matching the normalised answer text to the parsed lines.
- **Round found:** the round in which the answer page was first read (1 = server first pass, 2+ = the model asked),
  reported like MRR.
- **Extraction:** overlap of the extracted value with the expert span (token F1; exact containment as a strict
  measure). A category with no answer counts as correct when the model returns none.
- **Cost:** prompt and completion tokens and seconds per contract.

## Cost and calls

About 10 × (A up to 2 calls + B up to 2 calls + C 1 call), roughly 50–60 LIVE calls. Estimated $2–3 at the
published muse-spark-1.1 price. Every call is recorded in META_LIVE_LOG.

## Out of scope

LLM-judged evaluation tools (RAGAS, DeepEval, TruLens): the expert spans make an LLM judge unnecessary. Their
metric ideas (context recall) are covered by page recall.
