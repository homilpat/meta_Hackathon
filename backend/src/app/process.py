"""Process-neutral core contracts (v5 structure E) and adapters.

The D0-D8 engine only sees AffectedObject / Measurement dicts. PCB panel/board/pin/SPI/AOI stay in the PCB
adapter, read from the existing source rows (nothing is moved). `MachiningDemoAdapter` is a tiny fictional
second process used only by contract tests to show a new process needs no engine change.
"""

import hashlib
import json
from typing import Protocol, TypedDict

from sqlalchemy.orm import Session

from app import ncr


class Obj(TypedDict):
    object_type: str
    object_id: str
    parent_id: str | None
    location: str | None
    shipment_state: str  # IN_PLANT | SHIPPED | UNKNOWN
    identity_source: str


class Measurement(TypedDict):
    object_id: str
    characteristic: str
    value: float
    unit: str
    evidence_id: str
    measured_at: str
    source_version: int


class Context(TypedDict):
    process_type: str
    adapter_version: str
    operation: str
    equipment: list[str]
    recipe: str | None


class ProcessAdapter(Protocol):
    process_type: str
    adapter_version: str

    def context(self, session: Session, case_id: str) -> Context: ...

    def affected_objects(self, session: Session, case_id: str) -> list[Obj]: ...

    def measurements(self, session: Session, case_id: str) -> list[Measurement]: ...


class PcbAdapter:
    process_type, adapter_version = "PCB_SMT", "pcb-adapter-1"

    def context(self, session: Session, case_id: str) -> Context:
        items = ncr._evidence(session, case_id)
        tools = sorted({i["rec"].get("stencil_id") for i in items if i["type"] == "lots"}
                       | {i["rec"]["tool_id"] for i in items if i["type"] == "equipment_events"})
        lines = sorted({i["rec"].get("line_id") for i in items if i["type"] == "lots"})
        return {"process_type": self.process_type, "adapter_version": self.adapter_version,
                "operation": f"SMT print/SPI/AOI {','.join(lines) or '-'}", "equipment": tools, "recipe": None}

    def affected_objects(self, session: Session, case_id: str) -> list[Obj]:
        items = ncr.current(ncr._evidence(session, case_id))
        shipped = {i["rec"]["panel_id"]: i for i in items if i["type"] == "shipments"}
        out: list[Obj] = [{"object_type": "LOT", "object_id": i["rec"]["lot_id"], "parent_id": None,
                           "location": i["rec"].get("line_id"), "shipment_state": "UNKNOWN",
                           "identity_source": i["ev"]} for i in items if i["type"] == "lots"]
        def state(panel_id: str) -> str:
            ship = shipped.get(panel_id)
            return "SHIPPED" if ship and ship["rec"]["status"] == "SHIPPED" else "IN_PLANT"

        for i in items:
            r = i["rec"]
            if i["type"] == "panels":
                out.append({"object_type": "PANEL", "object_id": r["panel_id"], "parent_id": r.get("lot_id"),
                            "location": None, "shipment_state": state(r["panel_id"]), "identity_source": i["ev"]})
            elif i["type"] == "boards":  # a board ships with its panel
                out.append({"object_type": "BOARD", "object_id": f"{r['panel_id']}/{r['board_id']}",
                            "parent_id": r["panel_id"], "location": None, "shipment_state": state(r["panel_id"]),
                            "identity_source": i["ev"]})
            elif i["type"] == "shipments":
                out.append({"object_type": "SHIPMENT", "object_id": r["original_row_id"], "parent_id": r["panel_id"],
                            "location": None, "shipment_state": "SHIPPED" if r["status"] == "SHIPPED" else "IN_PLANT",
                            "identity_source": i["ev"]})
        return out

    def measurements(self, session: Session, case_id: str) -> list[Measurement]:
        return [{"object_id": "/".join(str(k) for k in i["key"]), "characteristic": "solder_paste_volume",
                 "value": float(i["rec"]["volume_mm3"]), "unit": "mm3", "evidence_id": i["ev"],
                 "measured_at": i["rec"]["event_time"], "source_version": i["version"]}
                for i in ncr.current(ncr._evidence(session, case_id)) if i["type"] == "spi_measurements"]


class MachiningDemoAdapter:
    """Fictional bore-diameter fixture (no DB, no real plant). Contract tests only."""

    process_type, adapter_version = "MACHINING_DEMO", "machining-demo-0"
    PARTS = (("M-L1", "P1", 12.002), ("M-L1", "P2", 12.004), ("M-L2", "P3", 12.019))

    def context(self, session: Session, case_id: str) -> Context:
        return {"process_type": self.process_type, "adapter_version": self.adapter_version,
                "operation": "CNC bore finish", "equipment": ["CNC-7"], "recipe": "BORE-12H7"}

    def affected_objects(self, session: Session, case_id: str) -> list[Obj]:
        lots = sorted({lot for lot, _, _ in self.PARTS})
        return ([{"object_type": "LOT", "object_id": lot, "parent_id": None, "location": "CELL-2",
                  "shipment_state": "IN_PLANT", "identity_source": f"DEMO-{lot}"} for lot in lots]
                + [{"object_type": "PART", "object_id": p, "parent_id": lot, "location": "CELL-2",
                    "shipment_state": "IN_PLANT", "identity_source": f"DEMO-{p}"} for lot, p, _ in self.PARTS])

    def measurements(self, session: Session, case_id: str) -> list[Measurement]:
        return [{"object_id": p, "characteristic": "bore_diameter", "value": v, "unit": "mm",
                 "evidence_id": f"DEMO-{p}", "measured_at": "2026-01-01T00:00:00+00:00", "source_version": 1}
                for _, p, v in self.PARTS]


ADAPTERS: dict[str, ProcessAdapter] = {a.process_type: a for a in (PcbAdapter(), MachiningDemoAdapter())}


def config_hash(ctx: Context, objects: list[Obj]) -> str:
    raw = {"context": ctx, "objects": objects}
    return hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
