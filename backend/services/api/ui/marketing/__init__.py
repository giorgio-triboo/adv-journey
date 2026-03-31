"""Router Marketing: sotto-moduli per pagine, API gerarchia, analysis, export, proxy creatività."""
from fastapi import APIRouter

from .analysis_routes import router as analysis_router
from .creative_proxy import router as creative_proxy_router
from .export_routes import router as export_router
from .hierarchy_routes import router as hierarchy_router
from .misc_routes import router as misc_router
from .pages_routes import router as pages_router

router = APIRouter(include_in_schema=False)
router.include_router(creative_proxy_router)
router.include_router(misc_router)
router.include_router(analysis_router)
router.include_router(pages_router)
router.include_router(hierarchy_router)
router.include_router(export_router)
