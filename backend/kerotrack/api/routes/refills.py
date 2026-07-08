"""Manual refill cost entries (actual_refill_costs)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, desc, select

from kerotrack.clock import ensure_canonical_timestamp
from kerotrack.models.refill import ActualRefillCost

router = APIRouter(prefix="/api/refills", tags=["refills"])


class RefillBody(BaseModel):
    refill_date: str
    actual_volume_litres: float | None = None
    actual_ppl: float | None = None
    total_cost: float | None = None
    invoice_ref: str | None = None
    notes: str | None = None
    order_date: str | None = None
    order_ref: str | None = None

    @field_validator("refill_date")
    @classmethod
    def _refill_date_canonical(cls, value: str) -> str:
        # A free-form string used to silently break _match_actual_cost and
        # the manual-refill anchor (parse_local → None → skipped). Fail
        # loudly at entry instead (KERO-L6).
        return ensure_canonical_timestamp(value)


def _to_dict(row: ActualRefillCost) -> dict[str, Any]:
    cols = row.__table__.columns.keys()
    return {c: getattr(row, c) for c in cols}


@router.get("")
async def list_refills(request: Request) -> dict[str, Any]:
    sf = request.app.state.session_factory
    async with sf() as session:
        rows = (
            await session.execute(
                select(ActualRefillCost).order_by(desc(ActualRefillCost.refill_date))
            )
        ).scalars().all()
    return {"items": [_to_dict(r) for r in rows]}


@router.post("")
async def create_refill(body: RefillBody, request: Request) -> dict[str, Any]:
    sf = request.app.state.session_factory
    async with sf() as session:
        existing = (
            await session.execute(
                select(ActualRefillCost).where(
                    ActualRefillCost.refill_date == body.refill_date
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail="refill_exists")
        row = ActualRefillCost(**body.model_dump())
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return _to_dict(row)


@router.delete("/{refill_date}")
async def delete_refill(refill_date: str, request: Request) -> dict[str, Any]:
    sf = request.app.state.session_factory
    async with sf() as session:
        result = await session.execute(
            delete(ActualRefillCost).where(
                ActualRefillCost.refill_date == refill_date
            )
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="not_found")
        await session.commit()
    return {"ok": True}
