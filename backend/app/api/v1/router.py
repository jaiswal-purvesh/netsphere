from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    automation_hub,
    cloud_integrations,
    cloud_networks,
    connectivity,
    dashboard,
    devices,
    discovery,
    fw_intents,
    fw_poa_documents,
    fw_policy,
    health,
    integrations,
    ipam,
    ipam_integrations,
    naming,
    orgs,
    path_analyzer,
    poa,
    routing,
    security_policy,
    topology,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(orgs.router)
api_router.include_router(ipam.router)
api_router.include_router(ipam_integrations.router)
api_router.include_router(devices.router)
api_router.include_router(discovery.router)
api_router.include_router(dashboard.router)
api_router.include_router(poa.router)
api_router.include_router(automation_hub.router)
api_router.include_router(integrations.router)
api_router.include_router(cloud_integrations.router)
api_router.include_router(fw_intents.router)
api_router.include_router(fw_poa_documents.router)
api_router.include_router(fw_policy.router)
api_router.include_router(topology.router)
api_router.include_router(path_analyzer.router)
api_router.include_router(routing.router)
api_router.include_router(cloud_networks.router)
api_router.include_router(connectivity.router)
api_router.include_router(security_policy.router)
api_router.include_router(naming.router)
