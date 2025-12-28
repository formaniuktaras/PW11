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


def resolve_components_for_product(
    product_id: int,
    warehouse_id: int,
    qty: float,
    *,
    conn=None,
    allow_negative: bool = False,
) -> dict:
    owns_conn = conn is None
    if owns_conn:
        conn = db.get_connection()
    try:
        requirements = db.list_product_requirements(product_id, conn=conn)
        slot_need: Dict[int, float] = {}
        slot_meta: Dict[int, dict] = {}
        slot_allowed_group: Dict[int, int | None] = {}
        for req in requirements:
            slot_id = int(req["slot_id"])
            slot_meta[slot_id] = {
                "slot_code": req.get("slot_code"),
                "slot_name": req.get("slot_name"),
            }
            slot_allowed_group[slot_id] = req.get("group_id")
            slot_need[slot_id] = slot_need.get(slot_id, 0.0) + float(req.get("qty", 0) or 0) * qty

        groups_in_requirements = {
            int(req["group_id"]) for req in requirements if req.get("group_id") is not None
        }
        candidates: Dict[int, CandidateProduct] = {}
        unlimited_stock = float("inf") if allow_negative else None
        for group_id in groups_in_requirements:
            members = db.list_group_members(group_id, conn=conn)
            for member in members:
                pid = int(member["product_id"])
                existing = candidates.get(pid)
                priority = int(member.get("priority") or 0)
                if existing:
                    existing.priority_score = min(existing.priority_score, priority)
                    continue
                coverage = db.list_product_coverage_slot_ids(pid, conn=conn)
                stock = unlimited_stock if unlimited_stock is not None else db.get_stock_quantity(
                    pid, warehouse_id, conn=conn
                )
                candidates[pid] = CandidateProduct(
                    product_id=pid,
                    sku=str(member.get("sku") or ""),
                    name=str(member.get("name") or ""),
                    priority_score=priority,
                    coverage=coverage,
                    stock=stock,
                )

        # Extra candidates for slots without group restriction: any product covering these slots.
        unrestricted_slots = {slot_id for slot_id, grp in slot_allowed_group.items() if grp is None}
        if unrestricted_slots:
            covering = db.list_products_covering_slots(unrestricted_slots, conn=conn)
            for row in covering:
                pid = int(row["product_id"])
                if pid in candidates:
                    continue
                coverage = set(row.get("coverage", set()))
                stock = unlimited_stock if unlimited_stock is not None else db.get_stock_quantity(
                    pid, warehouse_id, conn=conn
                )
                candidates[pid] = CandidateProduct(
                    product_id=pid,
                    sku=str(row.get("sku") or ""),
                    name=str(row.get("name") or ""),
                    priority_score=1000,
                    coverage=coverage,
                    stock=stock,
                )

        memberships_raw = db.get_product_group_memberships(list(candidates.keys()), conn=conn)
        memberships = {pid: set(groups.keys()) for pid, groups in memberships_raw.items()}

        components: Dict[int, dict] = {}
        while True:
            needed_slots = {slot for slot, amount in slot_need.items() if amount > 0}
            if not needed_slots:
                break

            best_candidate: CandidateProduct | None = None
            best_key = ()
            best_covers: Set[int] = set()
            for candidate in candidates.values():
                if candidate.stock <= 0 and unlimited_stock is None:
                    continue
                allowed_covers = {
                    slot
                    for slot in candidate.coverage & needed_slots
                    if slot_allowed_group[slot] is None
                    or slot_allowed_group[slot] in memberships.get(candidate.product_id, set())
                }
                if not allowed_covers:
                    continue
                stock_score = 0 if candidate.stock == float("inf") else -candidate.stock
                score = (-len(allowed_covers), candidate.priority_score, stock_score)
                if best_candidate is None or score < best_key:
                    best_candidate = candidate
                    best_key = score
                    best_covers = allowed_covers

            if best_candidate is None:
                break

            target_need = min(slot_need[slot] for slot in best_covers)
            take_qty = target_need if unlimited_stock is not None else min(best_candidate.stock, target_need)
            if take_qty <= 0:
                break

            if unlimited_stock is None:
                best_candidate.stock -= take_qty
            best_candidate.allocated += take_qty
            for slot_id in best_covers:
                slot_need[slot_id] = max(0.0, slot_need[slot_id] - take_qty)

            comp_entry = components.get(best_candidate.product_id)
            if comp_entry:
                comp_entry["qty"] += take_qty
                comp_entry["covered_slots"].update(best_covers)
            else:
                components[best_candidate.product_id] = {
                    "product_id": best_candidate.product_id,
                    "sku": best_candidate.sku,
                    "name": best_candidate.name,
                    "qty": take_qty,
                    "covered_slots": set(best_covers),
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

        for comp in components.values():
            comp["covered_slots"] = sorted(comp.get("covered_slots", []))

        return {
            "components": list(components.values()),
            "missing_slots": missing_slots,
            "debug": {"requirements": requirements, "remaining_need": slot_need},
        }
    finally:
        if owns_conn and conn is not None:
            conn.close()
