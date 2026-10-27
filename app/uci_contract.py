"""Interface only. UCI Steel Plates Faults is never mixed with PCB records in S1."""

from collections.abc import Mapping
from typing import Literal, Protocol, TypedDict


class SteelFaultEvent(TypedDict):
    source_asset_id: str
    original_row_id: str
    data_origin: Literal["REAL"]
    defect_type: str
    features: dict[str, int | float]


class SteelFaultAdapter(Protocol):
    def normalize_row(
        self, row: Mapping[str, int | float], source_asset_id: str, original_row_id: str
    ) -> SteelFaultEvent: ...
