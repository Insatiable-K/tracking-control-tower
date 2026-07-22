"""
The narrow contract every output format implements (ARCHITECTURE.md
§08). A renderer only ever receives ShipmentReportRow objects - adding
a new output format (CSV for SPS bulk-import, an HTML dashboard, an
email digest) means a new file here, never a change upstream.
"""
from abc import ABC, abstractmethod

from tracking_control_tower.reporting.models import OtherCarrierRow, ShipmentReportRow


class ReportRenderer(ABC):
    @abstractmethod
    def render(
        self,
        rows: list[ShipmentReportRow],
        output_path: str,
        other_carrier_rows: list[OtherCarrierRow] | None = None,
    ) -> None: ...
