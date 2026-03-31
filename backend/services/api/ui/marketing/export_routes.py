"""Export CSV marketing (email)."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from models import User

from tasks.exports import generate_and_email_csv_task

router = APIRouter(include_in_schema=False)

@router.get("/api/marketing/export-request")
async def marketing_export_request(request: Request, db: Session = Depends(get_db)):
    """Enqueue export CSV marketing e invio email al richiedente."""
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    if not db.query(User).filter(User.email == user.get("email")).first():
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)

    requester_email = user.get("email") or ""
    if not requester_email:
        return JSONResponse({"error": "Email utente non disponibile"}, status_code=400)

    filters = {
        "account_id": request.query_params.get("account_id") or "",
        "status": request.query_params.get("status") or "all",
        "platform": request.query_params.get("platform") or "all",
        "campaign_name": request.query_params.get("campaign_name") or "",
        "adset_name": request.query_params.get("adset_name") or "",
        "ad_name": request.query_params.get("ad_name") or "",
        "date_from": request.query_params.get("date_from") or "",
        "date_to": request.query_params.get("date_to") or "",
    }

    generate_and_email_csv_task.delay("marketing", requester_email, filters, "")
    return JSONResponse({
        "ok": True,
        "message": "Export avviato. Riceverai il CSV via email appena pronto.",
    })


@router.get("/api/marketing/analysis-export-request")
async def marketing_analysis_export_request(request: Request, db: Session = Depends(get_db)):
    """
    Accoda export CSV con righe giornaliere da meta_marketing_placement (breakdown),
    stessi filtri della pagina /marketing/analysis — separato dall'export /marketing (lead-centrico).
    """
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)
    if not db.query(User).filter(User.email == user.get("email")).first():
        return JSONResponse({"error": "Non autorizzato"}, status_code=401)

    requester_email = user.get("email") or ""
    if not requester_email:
        return JSONResponse({"error": "Email utente non disponibile"}, status_code=400)

    params = request.query_params
    filters = {
        "account_id": params.get("account_id") or "",
        "campaign_id": params.get("campaign_id") or "",
        "adset_id": params.get("adset_id") or "",
        "campaign_name": params.get("campaign_name") or "",
        "adset_name": params.get("adset_name") or "",
        "creative_name": params.get("creative_name") or "",
        "date_from": params.get("date_from") or "",
        "date_to": params.get("date_to") or "",
    }

    generate_and_email_csv_task.delay("marketing_analysis_placement", requester_email, filters, "")
    return JSONResponse({
        "ok": True,
        "message": "Export breakdown avviato. Riceverai il CSV via email (placement giornalieri).",
    })

