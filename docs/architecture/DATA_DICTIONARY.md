# S1 synthetic PCB source contract

`python -m scripts.generate_synthetic_pcb --seed 7` emits one deterministic JSON bundle. Every asset and record has `data_origin=SYNTHETIC`. Each asset has `source_system`, `source_version`, `license_id=SELF_GENERATED`, `content_sha256` of canonical `records` JSON, capture/ingest time, and optional `supersedes_asset_id`. Every record has `original_row_id`, `event_time`, nullable `source_updated_at`, and `ingested_at`. Timezone offsets are explicit. Generated history is fictional and its outcomes are `UNVERIFIED` reports.

| Source | Manufacturing key | Relationship |
|---|---|---|
| panels | `panel_id` | Parent panel; not a lot |
| boards | `panel_id`, `board_id` | One panel has multiple boards; `board_id` repeats across panels |
| components | `panel_id`, `board_id`, `component_id` | Component under one board |
| pins | Above + `pin_number` | Pin under one component |
| spi_measurements | Pin key; `inspection_id` distinguishes inspection | Many measurements per board/pin; v2 preserves v1 |
| aoi_inspections | Board key; `inspection_id` distinguishes inspection | Zero or many inspections per board |
| human_verifications | Board key + `inspection_id` | Refers to an AOI inspection on the *same* panel and board |
| repair_dispositions | Board key + `inspection_id` | Refers to AOI and human records; not a document approval |
| equipment_events | `tool_id` | Separate equipment observation; no invented board link |
| source_revisions | `old_asset_id`, `new_asset_id` | Explicit v1 to v2 source link |
| historical_quality_cases | `historical_case_id` | Fictional process/site/defect/action and reported outcome; `outcome_evidence_id=null`, `validation_status=UNVERIFIED`; no S5 retrieval or eligibility claim |

The default bundle has a normal AOI PASS, a board with no AOI, a repeated SPI source row, two AOI inspections on one board, AOI FAIL vs human FALSE_ALARM, and a late corrected SPI source. Validation records `MISSING_AOI`, `DUPLICATE_ROW`, `INSPECTION_DISAGREEMENT`, `LATE_ARRIVAL`, and `SOURCE_CORRECTION`. Parent/reference failures get `INVALID_LINK`; disagreement remains an observed distinction. `source_assets.raw_json` stores the canonical original record list and its SHA-256. `source_events.raw_json` stores each canonical original row; `evidence` hashes that row separately. No label or absence is promoted to a verified cause or PASS.
