"""Phase 5 — Path Analyzer. Wires the `/path-analyzer` nav placeholder to
`POST /path/simulate`, the read-only "would this be allowed today?" check
called out by name in claude/firewall-policy-automation-design.md §3.8
("Ship it first") and docs/ROADMAP.md's top next-session candidate. See
app/services/path_analyzer.py for the actual resolution/verdict logic —
this module is request handling + persistence only.

Reuses the "path" RBAC resource area (already seeded, already granted to
NETWORK_ENGINEER/SECURITY_ENGINEER) — view for reading history, create for
running a new simulation (it's a read-only call against the *firewall*,
but it creates a new PathSimulationRun record in *this* app, matching the
verb convention "create" already uses elsewhere for "this makes a new row
here" rather than "this changes state elsewhere").
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_permission
from app.models.network import Network
from app.models.path_analyzer import PathSimulationRun
from app.models.user import User
from app.schemas.path_analyzer import HopOut, NetworkRefOut, PathSimulateRequest, PathSimulateResponse
from app.services import path_analyzer as analyzer
from app.services.audit import record as audit_record

router = APIRouter(prefix="/path", tags=["path-analyzer"])


def _network_ref(net: Network | None) -> NetworkRefOut | None:
    if not net:
        return None
    return NetworkRefOut(id=str(net.id), name=net.name, cidr=net.cidr)


def _run_out(row: PathSimulationRun, networks_by_id: dict[uuid.UUID, Network]) -> PathSimulateResponse:
    return PathSimulateResponse(
        id=str(row.id), source=row.source, destination=row.destination, protocol=row.protocol,
        port_low=row.port_low, port_high=row.port_high,
        source_network=_network_ref(networks_by_id.get(row.source_network_id)) if row.source_network_id else None,
        destination_network=(
            _network_ref(networks_by_id.get(row.destination_network_id)) if row.destination_network_id else None
        ),
        hops=[HopOut(**h) for h in row.hops_json],
        overall_verdict=row.overall_verdict, notes=row.notes_json, created_at=row.created_at,
    )


@router.post("/simulate", response_model=PathSimulateResponse)
def simulate(
    payload: PathSimulateRequest, db: Session = Depends(get_db),
    user: User = Depends(require_permission("path:create")),
) -> PathSimulateResponse:
    port_low = payload.port_low if payload.port_low is not None else payload.port
    port_high = payload.port_high if payload.port_high is not None else payload.port
    if port_low is None or port_high is None:
        raise HTTPException(status_code=400, detail="provide either `port` or both `port_low`/`port_high`")
    if port_low > port_high:
        raise HTTPException(status_code=400, detail="port_low must be <= port_high")

    try:
        result = analyzer.simulate(db, payload.source, payload.destination, payload.protocol, port_low, port_high)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    run = PathSimulationRun(
        source=payload.source, destination=payload.destination, protocol=payload.protocol,
        port_low=port_low, port_high=port_high, overall_verdict=result.overall_verdict,
        hops_json=[h.to_dict() for h in result.hops], notes_json=result.notes,
        source_network_id=result.source_network.id if result.source_network else None,
        destination_network_id=result.destination_network.id if result.destination_network else None,
        triggered_by_id=user.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    audit_record(
        db, user_id=user.id, action="simulate", resource_type="path_simulation_run", resource_id=str(run.id),
        after={"overall_verdict": run.overall_verdict, "hops": len(result.hops)},
    )

    return PathSimulateResponse(
        id=str(run.id), source=run.source, destination=run.destination, protocol=run.protocol,
        port_low=run.port_low, port_high=run.port_high,
        source_network=_network_ref(result.source_network), destination_network=_network_ref(result.destination_network),
        hops=[HopOut(**h.to_dict()) for h in result.hops], overall_verdict=run.overall_verdict, notes=run.notes_json,
        created_at=run.created_at,
    )


@router.get("/runs", response_model=list[PathSimulateResponse])
def list_runs(
    db: Session = Depends(get_db), _: User = Depends(require_permission("path:view")),
) -> list[PathSimulateResponse]:
    rows = db.execute(select(PathSimulationRun).order_by(PathSimulationRun.created_at.desc()).limit(100)).scalars().all()
    net_ids = {r.source_network_id for r in rows if r.source_network_id} | {
        r.destination_network_id for r in rows if r.destination_network_id
    }
    networks_by_id = {n.id: n for n in db.execute(select(Network).where(Network.id.in_(net_ids))).scalars().all()} if net_ids else {}
    return [_run_out(r, networks_by_id) for r in rows]
