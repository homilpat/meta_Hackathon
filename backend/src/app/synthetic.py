"""Seeded, fictional PCB records. No source data is copied from PHME or a factory."""

import hashlib
import json
import random
from datetime import UTC, datetime, timedelta

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


LINE_VERSION = "line1.0"
LINE_T0 = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


def generate_line(seed: int = 7, lots: int = 3, panels_per_lot: int = 12, boards: int = 4, comps: int = 4,
                  first_lot: int = 1, t0: datetime = LINE_T0, worn_lots: tuple[int, ...] = (2,),
                  tag: str = "") -> dict:
    """Production-scale fictional SMT line: lots -> panels -> boards -> components -> pins, shipments.

    Lot L02 runs on a worn stencil: paste volume drifts down panel by panel, so true insufficient-solder
    defects concentrate there late in the lot. AOI also raises random false calls, a few boards skip AOI,
    and early panels of each lot have already shipped. Every value is generated; none is measured.
    """
    rng = random.Random(seed)
    t = {"lots": [], "panels": [], "boards": [], "components": [], "pins": [], "spi_measurements": [],
         "aoi_inspections": [], "human_verifications": [], "repair_dispositions": [], "shipments": [],
         "equipment_events": []}

    def row(row_id: str, at: datetime, **fields: object) -> dict:
        return {"original_row_id": row_id, "data_origin": "SYNTHETIC", "event_time": at.isoformat(),
                "source_updated_at": None, "ingested_at": (at + timedelta(hours=2)).isoformat(), **fields}

    for li in range(first_lot, first_lot + lots):
        lot, worn = f"L{li:02d}", li in worn_lots
        start = t0 + timedelta(hours=8 * (li - first_lot))
        t["lots"].append(row(f"LOT-{lot}", start, lot_id=lot, line_id="SMT-1", stencil_id=f"STN-{li}",
                             paste_lot=f"PST-{100 + li}"))
        if worn:
            t["equipment_events"].append(row(f"EQ-STN-{li}", start, tool_id=f"STN-{li}",
                                             status="CLEANING_INTERVAL_EXCEEDED"))
        for pi in range(1, panels_per_lot + 1):
            panel, at = f"{lot}-P{pi:02d}", start + timedelta(minutes=12 * pi)
            t["panels"].append(row(f"PANEL-{panel}", at, panel_id=panel, lot_id=lot))
            shipped = pi <= panels_per_lot // 3
            t["shipments"].append(row(f"SHIP-{panel}", at + timedelta(hours=6), panel_id=panel, lot_id=lot,
                                      status="SHIPPED" if shipped else "IN_WIP"))
            drift = 0.0025 * pi if worn else 0.0
            for bi in range(1, boards + 1):
                board = f"B{bi}"
                t["boards"].append(row(f"BOARD-{panel}-{board}", at, panel_id=panel, board_id=board))
                vols = []
                for ci in range(1, comps + 1):
                    comp = f"C{ci:02d}"
                    t["components"].append(row(f"COMP-{panel}-{board}-{comp}", at, panel_id=panel, board_id=board,
                                               component_id=comp))
                    for pin in (1, 2):
                        key = {"panel_id": panel, "board_id": board, "component_id": comp, "pin_number": pin}
                        t["pins"].append(row(f"PIN-{panel}-{board}-{comp}-{pin}", at, **key))
                        v = round(max(0.02, rng.gauss(0.12 - drift, 0.008)), 4)
                        vols.append(v)
                        t["spi_measurements"].append(row(f"SPI-{panel}-{board}-{comp}-{pin}", at, **key,
                                                         inspection_id="S01", volume_mm3=v))
                if rng.random() < 0.02:
                    continue  # AOI skipped: a missing record is not a PASS
                defect = min(vols) < 0.092
                fail = defect or rng.random() < 0.04  # false calls happen
                aoi_at = at + timedelta(minutes=25)
                ref = {"panel_id": panel, "board_id": board, "inspection_id": "A01"}
                t["aoi_inspections"].append(row(f"AOI-{panel}-{board}-A01", aoi_at, **ref,
                                                result="FAIL" if fail else "PASS"))
                if fail:
                    t["human_verifications"].append(row(f"H-{panel}-{board}-A01", aoi_at + timedelta(minutes=40),
                                                        **ref, result="DEFECT_CONFIRMED" if defect else "FALSE_ALARM"))
                    t["repair_dispositions"].append(row(f"R-{panel}-{board}-A01", aoi_at + timedelta(hours=1), **ref,
                                                        disposition="REPAIRED" if defect else "NO_REPAIR"))

    def asset(kind: str, records: list[dict]) -> dict:
        return {"asset_id": f"synthetic:{kind}{tag}:v1", "source_system": f"SYNTHETIC_{kind.upper()}",
                "entity_type": kind, "source_version": 1, "supersedes_asset_id": None, "license_id": "SELF_GENERATED",
                "data_origin": "SYNTHETIC", "sensitivity": "APPROVED_FOR_EXTERNAL",
                "captured_at": t0.isoformat(), "ingested_at": (t0 + timedelta(days=1)).isoformat(),
                "content_sha256": sha256(records), "records": records}

    return {"generator_version": LINE_VERSION, "seed": seed, "data_origin": "SYNTHETIC",
            "assets": [asset(k, v) for k, v in t.items() if v]}


POST_VERSION = "line1.0-post"


def generate_post_window(seed: int, after: datetime, effective: bool = True) -> dict:
    """D6 monitoring fixture: one further lot (L04) produced after a corrective action was executed, on a fresh
    stencil (effective) or with the same paste-volume drift (not effective). Every value is generated."""
    bundle = generate_line(seed, lots=1, first_lot=4, t0=after + timedelta(hours=1),
                           worn_lots=() if effective else (4,), tag=":post")
    return {**bundle, "generator_version": POST_VERSION}


def spi_correction(seed: int = 7, row_id: str = "SPI-P02-B01-1", delta: float = -0.03, version: int = 3,
                   line: bool = False) -> dict:
    """Demo S6 source fix: SPI asset v<version> re-measures one row of the fixture (or of the line dataset)."""
    bundle = generate_line(seed) if line else generate(seed)
    spi = next(a for a in bundle["assets"] if a["asset_id"] == "synthetic:spi_measurements:v1")
    rec = dict(next(r for r in spi["records"] if r["original_row_id"] == row_id))
    rec.update(volume_mm3=round(rec["volume_mm3"] + delta, 4), source_updated_at="2026-01-04T08:00:00+00:00",
               ingested_at="2026-01-04T09:00:00+00:00")
    return {**spi, "asset_id": f"synthetic:spi_measurements:v{version}", "source_version": version,
            "supersedes_asset_id": f"synthetic:spi_measurements:v{version - 1}",
            "ingested_at": rec["ingested_at"], "records": [rec], "content_sha256": sha256([rec])}
