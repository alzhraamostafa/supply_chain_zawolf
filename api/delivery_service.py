"""The delivery agent behind the API: adds plant context, runs the agent, wraps the result in the envelope."""
import sqlite3
from datetime import date

from common.access import BUYER_ROLES, Principal
from common.audit import AuditLog
from delivery.agent import Shipment, evaluate_all
from delivery.api_payload import build_delivery_payload, input_completeness
from delivery.envelope import delivery_envelope
from risk.adapter import load_histories

from .service import Forbidden


class DeliveryService:
    def __init__(self, audit: AuditLog, plant_db_path: str | None = None):
        self.audit = audit
        self.plant_db_path = plant_db_path

    def _plant_context(self) -> tuple[dict, dict]:
        """material -> criticality (only items found in the BOM) and number of alternative suppliers."""
        if not self.plant_db_path:
            return {}, {}
        con = sqlite3.connect(f"file:{self.plant_db_path}?mode=ro", uri=True)
        try:
            loaded = load_histories(con, "")
        finally:
            con.close()
        unmatched = set(loaded.unmatched_skus)
        criticality = {h.material: h.criticality for h in loaded.histories if h.material not in unmatched}
        alternatives = {h.material: h.n_suppliers - 1 for h in loaded.histories if h.n_suppliers >= 1}
        return criticality, alternatives

    def assess(self, principal: Principal, shipments: list[dict], today: date | None = None) -> dict:
        if principal.role not in BUYER_ROLES:
            self.audit.record(principal.user_id, "forbidden:read_delivery")
            raise Forbidden(f"role '{principal.role}' cannot read_delivery")
        if not shipments:
            raise ValueError("at least one shipment is required")
        today = today or date.today()
        criticality, alternatives = self._plant_context()
        prepared = []
        for raw in shipments:
            data = dict(raw)
            if data.get("criticality") is None:
                data["criticality"] = criticality.get(data.get("material"))
            if data.get("alternative_suppliers") is None:
                data["alternative_suppliers"] = alternatives.get(data.get("material"))
            try:
                prepared.append(Shipment(**data))
            except TypeError as exc:
                raise ValueError(f"invalid shipment: {exc}") from exc
        reports = evaluate_all(prepared, today)
        payload = build_delivery_payload(reports, today)
        sources = ["shipments supplied by the caller"]
        if self.plant_db_path:
            sources += ["fact_procurement_rfq", "product_bom_items"]
        envelope = delivery_envelope(payload, input_completeness(prepared), sources)
        self.audit.record(principal.user_id, "delivery_assessed", output_ref=envelope.id)
        return envelope.model_dump(mode="json")