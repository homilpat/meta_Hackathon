"""Seeded, fictional PCB records. No source data is copied from PHME or a factory."""

import hashlib
import json
import random

VERSION = "s1.0"
T0 = "2026-01-01T08:00:00+00:00"
INGESTED = "2026-01-01T09:00:00+00:00"
LATE = "2026-01-03T09:00:00+00:00"


def canonical(records: list[dict]) -> str:
    return json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(records: list[dict]) -> str:
    return hashlib.sha256(canonical(records).encode("utf-8")).hexdigest()


def generate(seed: int = 7) -> dict:
    rng = random.Random(seed)

    def row(row_id: str, **fields: object) -> dict:
        return {
            "original_row_id": row_id,
            "data_origin": "SYNTHETIC",
            "event_time": T0,
            "source_updated_at": None,
            "ingested_at": INGESTED,
            **fields,
        }

    panels = [row(f"PANEL-{p}", panel_id=p) for p in ("P01", "P02")]
    boards = [
        row(f"BOARD-{p}-{b}", panel_id=p, board_id=b)
        for p in ("P01", "P02")
        for b in ("B01", "B02")
    ]
    components = [
        row(f"COMP-{p}-{b}-C01", panel_id=p, board_id=b, component_id="C01")
        for p in ("P01", "P02")
        for b in ("B01", "B02")
    ]
    pins = [
        row(
            f"PIN-{p}-{b}-C01-{pin}",
            panel_id=p,
            board_id=b,
            component_id="C01",
            pin_number=pin,
        )
        for p in ("P01", "P02")
        for b in ("B01", "B02")
        for pin in (1, 2)
    ]
    spi = [
        row(
            f"SPI-{p}-{b}-{pin}",
            panel_id=p,
            board_id=b,
            component_id="C01",
            pin_number=pin,
            inspection_id="S01",
            volume_mm3=round(rng.uniform(0.08, 0.16), 4),
        )
        for p in ("P01", "P02")
        for b in ("B01", "B02")
        for pin in (1, 2)
    ]
    spi.append(dict(spi[1]))  # Deliberate duplicate original row.
    corrected = dict(spi[0])
    corrected["volume_mm3"] = round(spi[0]["volume_mm3"] + 0.01, 4)
    corrected["source_updated_at"] = "2026-01-02T08:00:00+00:00"
    corrected["ingested_at"] = LATE
    aoi = [
        row("AOI-P01-B01-A01", panel_id="P01", board_id="B01", inspection_id="A01", result="FAIL"),
        row("AOI-P01-B01-A02", panel_id="P01", board_id="B01", inspection_id="A02", result="PASS"),
        row("AOI-P02-B01-A01", panel_id="P02", board_id="B01", inspection_id="A01", result="FAIL"),
        row("AOI-P02-B02-A01", panel_id="P02", board_id="B02", inspection_id="A01", result="PASS"),
    ]
    humans = [
        row("H-P01-B01-A01", panel_id="P01", board_id="B01", inspection_id="A01", result="FALSE_ALARM"),
        row("H-P01-B01-A02", panel_id="P01", board_id="B01", inspection_id="A02", result="PASS_CONFIRMED"),
        row("H-P02-B01-A01", panel_id="P02", board_id="B01", inspection_id="A01", result="DEFECT_CONFIRMED"),
        row("H-P02-B02-A01", panel_id="P02", board_id="B02", inspection_id="A01", result="PASS_CONFIRMED"),
    ]
    repairs = [
        row("R-P01-B01-A01", panel_id="P01", board_id="B01", inspection_id="A01", disposition="NO_REPAIR"),
        row("R-P02-B01-A01", panel_id="P02", board_id="B01", inspection_id="A01", disposition="REPAIRED"),
    ]
    equipment = [row("EQ-1", tool_id="EQ-1", status="MAINTENANCE_NOTE")]
    revisions = [
        row(
            "REV-SPI-01",
            old_asset_id="synthetic:spi_measurements:v1",
            new_asset_id="synthetic:spi_measurements:v2",
            reason="CORRECTED_MEASUREMENT",
        )
    ]
    historical = [
        row("HIST-01", historical_case_id="HIST-01", process="PCB_ASSEMBLY", site="SYNTHETIC_SITE_A",
            defect_type="SOLDER_BRIDGE", action="STENCIL_RECHECK", outcome="EFFECTIVE_REPORTED",
            validation_status="UNVERIFIED", outcome_evidence_id=None),
        row("HIST-02", historical_case_id="HIST-02", process="PCB_ASSEMBLY", site="SYNTHETIC_SITE_A",
            defect_type="SOLDER_BRIDGE", action="STENCIL_RECHECK", outcome="INEFFECTIVE_REPORTED",
            validation_status="UNVERIFIED", outcome_evidence_id=None),
    ]

    def asset(kind: str, records: list[dict], version: int = 1, supersedes: str | None = None) -> dict:
        return {
            "asset_id": f"synthetic:{kind}:v{version}",
            "source_system": f"SYNTHETIC_{kind.upper()}",
            "entity_type": kind,
            "source_version": version,
            "supersedes_asset_id": supersedes,
            "license_id": "SELF_GENERATED",
            "data_origin": "SYNTHETIC",
            "sensitivity": "APPROVED_FOR_EXTERNAL",
            "captured_at": T0,
            "ingested_at": LATE if version == 2 else INGESTED,
            "content_sha256": sha256(records),
            "records": records,
        }

    tables = {
        "panels": panels,
        "boards": boards,
        "components": components,
        "pins": pins,
        "spi_measurements": spi,
        "aoi_inspections": aoi,
        "human_verifications": humans,
        "repair_dispositions": repairs,
        "equipment_events": equipment,
        "source_revisions": revisions,
        "historical_quality_cases": historical,
    }
    assets = [asset(kind, records) for kind, records in tables.items()]
    assets.append(asset("spi_measurements", [corrected], 2, "synthetic:spi_measurements:v1"))
    return {"generator_version": VERSION, "seed": seed, "data_origin": "SYNTHETIC", "assets": assets}
