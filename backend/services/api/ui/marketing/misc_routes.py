"""Route sparse (banner Ulixe)."""
import logging

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db

from .helpers import get_unmapped_ulixe_ids

logger = logging.getLogger('services.api.ui')
router = APIRouter(include_in_schema=False)


@router.get("/api/ui/unmapped-ulixe-ids")
async def api_unmapped_ulixe_ids(request: Request, db: Session = Depends(get_db)):
    """
    Ritorna gli msg_id presenti in ulixe_rcrm_temp ma NON in ManagedCampaign.
    Usato dalla sidebar per mostrare banner '(!) N id da mappare'.
    """
    if not request.session.get("user"):
        return JSONResponse({"ids": [], "count": 0})
    ids = get_unmapped_ulixe_ids(db)
    return JSONResponse({"ids": ids, "count": len(ids)})

