"""S1 source contract and deterministic, non-causal integrity checks."""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.synthetic import sha256

KEYS = {
    "panels": ("panel_id",),
    "boards": ("panel_id", "board_id"),
    "components": ("panel_id", "board_id", "component_id"),
    "pins": ("panel_id", "board_id", "component_id", "pin_number"),
    "spi_measurements": ("panel_id", "board_id", "component_id", "pin_number"),
    "aoi_inspections": ("panel_id", "board_id"),
    "human_verifications": ("panel_id", "board_id"),
    "repair_dispositions": ("panel_id", "board_id"),
    "equipment_events": ("tool_id",),
    "source_revisions": ("old_asset_id", "new_asset_id"),
    "historical_quality_cases": ("historical_case_id",),
}


class SourceAssetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    source_system: str
    entity_type: str
    source_version: int = Field(ge=1)
    supersedes_asset_id: str | None = None
    license_id: str
    data_origin: Literal["SYNTHETIC"]
    sensitivity: Literal["APPROVED_FOR_EXTERNAL"]
    captured_at: datetime
    ingested_at: datetime
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    records: list[dict]


class SyntheticBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generator_version: str
    seed: int
    data_origin: Literal["SYNTHETIC"]
    assets: list[SourceAssetInput] = Field(min_length=1)


def entity_key(kind: str, record: dict) -> tuple:
    try:
        key = tuple(record[field] for field in KEYS[kind])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Missing manufacturing key for {kind}") from exc
    if any(type(value) not in (str, int) or value == "" for value in key):
        raise ValueError(f"Empty manufacturing key for {kind}")
    if "pin_number" in KEYS[kind] and (type(key[-1]) is not int or key[-1] < 1):
        raise ValueError("Invalid pin number")
    return key


def normalize(bundle: SyntheticBundle) -> tuple[list[dict], list[dict]]:
    assets = {asset.asset_id: asset for asset in bundle.assets}
    if len(assets) != len(bundle.assets):
        raise ValueError("Duplicate source asset ID")
    events: list[dict] = []
    issues: list[dict] = []

    def issue(code: str, event_id: str, detail: str, severity: str = "WARNING") -> None:
        issues.append({"code": code, "event_id": event_id, "detail": detail, "severity": severity})

    for asset in bundle.assets:
        if asset.entity_type not in KEYS or asset.source_system != f"SYNTHETIC_{asset.entity_type.upper()}":
            raise ValueError("Unsupported source type or system")
        if asset.license_id != "SELF_GENERATED" or sha256(asset.records) != asset.content_sha256:
            raise ValueError("Source license or content hash mismatch")
        if asset.captured_at.tzinfo is None or asset.ingested_at.tzinfo is None:
            raise ValueError("Source asset timezone required")
        if asset.supersedes_asset_id:
            old = assets.get(asset.supersedes_asset_id)
            if old is None or old.entity_type != asset.entity_type or old.source_version >= asset.source_version:
                raise ValueError("Invalid source revision")
        row_ids: set[str] = set()
        for index, record in enumerate(asset.records):
            if record.get("data_origin") != "SYNTHETIC":
                raise ValueError("Mixed or unclassified source origin")
            row_id = record.get("original_row_id")
            if not isinstance(row_id, str) or not row_id:
                raise ValueError("Missing original row ID")
            key = entity_key(asset.entity_type, record)
            if (
                asset.entity_type in ("spi_measurements", "aoi_inspections", "human_verifications", "repair_dispositions")
                and (not isinstance(record.get("inspection_id"), str) or not record["inspection_id"])
            ):
                raise ValueError("Missing inspection ID")
            try:
                event_time = datetime.fromisoformat(record["event_time"])
                ingested_at = datetime.fromisoformat(record["ingested_at"])
                if event_time.tzinfo is None or ingested_at.tzinfo is None:
                    raise ValueError("Timezone required")
                if record.get("source_updated_at"):
                    updated_at = datetime.fromisoformat(record["source_updated_at"])
                    if updated_at.tzinfo is None:
                        raise ValueError("Timezone required")
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Invalid source event timestamp") from exc
            event_id = hashlib.sha256(f"{asset.asset_id}:{index}".encode()).hexdigest()[:20]
            event = {
                "id": event_id,
                "asset_id": asset.asset_id,
                "entity_type": asset.entity_type,
                "entity_key": list(key),
                "original_row_id": row_id,
                "event_time": record["event_time"],
                "source_updated_at": record.get("source_updated_at"),
                "ingested_at": record["ingested_at"],
                "data_origin": "SYNTHETIC",
                "sensitivity": asset.sensitivity,
                "raw_json": json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            }
            events.append(event)
            if row_id in row_ids:
                issue("DUPLICATE_ROW", event_id, f"{asset.asset_id}:{row_id}")
            row_ids.add(row_id)
            if ingested_at - event_time > timedelta(days=1):
                issue("LATE_ARRIVAL", event_id, f"{asset.asset_id}:{row_id}", "INFO")
            if asset.supersedes_asset_id:
                issue("SOURCE_CORRECTION", event_id, asset.supersedes_asset_id, "INFO")

    by_type: dict[str, dict[tuple, list[dict]]] = {kind: {} for kind in KEYS}
    for event in events:
        by_type[event["entity_type"]].setdefault(tuple(event["entity_key"]), []).append(event)

    parent = {
        "boards": "panels",
        "components": "boards",
        "pins": "components",
        "spi_measurements": "pins",
        "aoi_inspections": "boards",
        "human_verifications": "boards",
        "repair_dispositions": "boards",
    }
    for kind, parent_kind in parent.items():
        for event in (e for e in events if e["entity_type"] == kind):
            parent_key = tuple(event["entity_key"][: len(KEYS[parent_kind])])
            if parent_key not in by_type[parent_kind]:
                issue("MISSING_PARENT", event["id"], f"{parent_kind}:{parent_key}", "ERROR")

    aoi_by_inspection = {}
    for event in (e for e in events if e["entity_type"] == "aoi_inspections"):
        inspection_key = (*event["entity_key"], json.loads(event["raw_json"])["inspection_id"])
        if inspection_key in aoi_by_inspection:
            issue("DUPLICATE_INSPECTION", event["id"], str(inspection_key))
        else:
            aoi_by_inspection[inspection_key] = event
    human_by_inspection = {
        (*e["entity_key"], json.loads(e["raw_json"])["inspection_id"]): e
        for e in events
        if e["entity_type"] == "human_verifications"
    }
    for event in events:
        kind = event["entity_type"]
        if kind not in ("human_verifications", "repair_dispositions"):
            continue
        record = json.loads(event["raw_json"])
        inspection_key = (*event["entity_key"], record.get("inspection_id"))
        aoi = aoi_by_inspection.get(inspection_key)
        if aoi is None:
            issue("MISSING_AOI_REFERENCE", event["id"], str(inspection_key), "ERROR")
            continue
        if kind == "repair_dispositions" and inspection_key not in human_by_inspection:
            issue("MISSING_HUMAN_REFERENCE", event["id"], str(inspection_key), "ERROR")
        if kind == "human_verifications":
            aoi_result = json.loads(aoi["raw_json"])["result"]
            if aoi_result == "FAIL" and record["result"] == "FALSE_ALARM":
                issue("INSPECTION_DISAGREEMENT", event["id"], str(inspection_key), "INFO")

    aoi_boards = set(by_type["aoi_inspections"])
    for board_key, board_events in by_type["boards"].items():
        if board_key not in aoi_boards:
            issue("MISSING_AOI", board_events[0]["id"], str(board_key))
    for event in (e for e in events if e["entity_type"] == "source_revisions"):
        old_id, new_id = event["entity_key"]
        if old_id not in assets or new_id not in assets or assets[new_id].supersedes_asset_id != old_id:
            issue("INVALID_REVISION_LINK", event["id"], f"{old_id}:{new_id}", "ERROR")

    invalid_ids = {item["event_id"] for item in issues if item["severity"] == "ERROR"}
    for event in events:
        event["validation_status"] = "INVALID_LINK" if event["id"] in invalid_ids else "CHECKED"
    return events, issues
