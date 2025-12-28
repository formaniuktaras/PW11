from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set

from inventorylite import db


@dataclass
class CandidateProduct:
    product_id: int
    sku: str
    name: str
    priority_score: int
    coverage: Set[int]
    stock: float
    allocated: float = 0.0


def resolve_components_for_product(product_id: int, warehouse_id: int, qty: float) -> dict:
    requirements = db.list_product_requirements(product_id)
    slot_need: Dict[int, float] = {}
    slot_meta: Dict[int, dict] = {}
    for req in requirements:
        slot_id = int(req["slot_id"])
        slot_meta[slot_id] = {
            "slot_code": req.get("slot_code"),
            "slot_name": req.get("slot_name"),
        }
        slot_need[slot_id] = slot_need.get(slot_id, 0.0) + float(req.get("qty", 0) or 0) * qty

    groups_in_requirements = {int(req["group_id"]) for req in requirements if req.get("group_id") is not None}
    candidates: Dict[int, CandidateProduct] = {}
    for group_id in groups_in_requirements:
        members = db.list_group_members(group_id)
        for member in members:
            pid = int(member["product_id"])
            existing = candidates.get(pid)
            priority = int(member.get("priority") or 0)
            if existing:
                existing.priority_score = min(existing.priority_score, priority)
                continue
            coverage = db.list_product_coverage_slot_ids(pid)
            stock = db.get_stock_quantity(pid, warehouse_id)
            candidates[pid] = CandidateProduct(
                product_id=pid,
                sku=str(member.get("sku") or ""),
                name=str(member.get("name") or ""),
                priority_score=priority,
                coverage=coverage,
                stock=stock,
            )

    components: Dict[int, dict] = {}
    while True:
        needed_slots = {slot for slot, amount in slot_need.items() if amount > 0}
        if not needed_slots:
            break

        best_candidate: CandidateProduct | None = None
        best_key = ()
        best_covers: Set[int] = set()
        for candidate in candidates.values():
            if candidate.stock <= 0:
                continue
            covers = candidate.coverage & needed_slots
            if not covers:
                continue
            score = (-len(covers), candidate.priority_score, -candidate.stock)
            if best_candidate is None or score < best_key:
                best_candidate = candidate
                best_key = score
                best_covers = covers

        if best_candidate is None:
            break

        take_qty = min(best_candidate.stock, min(slot_need[slot] for slot in best_covers))
        if take_qty <= 0:
            break

        best_candidate.stock -= take_qty
        best_candidate.allocated += take_qty
        for slot_id in best_covers:
            slot_need[slot_id] = max(0.0, slot_need[slot_id] - take_qty)

        comp_entry = components.get(best_candidate.product_id)
        if comp_entry:
            comp_entry["qty"] += take_qty
        else:
            components[best_candidate.product_id] = {
                "product_id": best_candidate.product_id,
                "sku": best_candidate.sku,
                "name": best_candidate.name,
                "qty": take_qty,
            }

    missing_slots = [
        {
            "slot_code": slot_meta[slot]["slot_code"],
            "slot_name": slot_meta[slot]["slot_name"],
            "missing_qty": slot_need.get(slot, 0.0),
        }
        for slot, needed in slot_need.items()
        if needed > 0
    ]

    return {
        "components": list(components.values()),
        "missing_slots": missing_slots,
        "debug": {"requirements": requirements, "remaining_need": slot_need},
    }
