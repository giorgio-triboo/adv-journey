"""Helper condivisi: pay/ricavo, filtri lead, Sankey lavorazioni, parse importi."""
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from models import (
    Lead,
    ManagedCampaign,
    MetaAccount,
    MetaAd,
    MetaAdSet,
    MetaCampaign,
    MetaMarketingData,
    MetaMarketingPlacement,
    StatusCategory,
    UlixeRcrmTemp,
)

def _get_mag_to_pay(db: Session) -> dict:
    """Mappa magellano_campaign_id -> pay_level da ManagedCampaign attive."""
    managed = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()
    mag_to_pay = {}
    for mc in managed:
        if mc.magellano_ids and mc.pay_level:
            try:
                pay_val = float(str(mc.pay_level).replace(',', '.'))
                for mid in mc.magellano_ids:
                    mag_to_pay[str(mid)] = pay_val
            except (ValueError, TypeError):
                pass
    return mag_to_pay


def _get_pay_for_leads(
    db: Session, leads: list, mag_to_pay: dict | None = None
) -> float | None:
    """
    Ottiene il pay più frequente tra le lead (moda).
    Usato per pay_level di riferimento; per ricavo effettivo usare _compute_ricavo_for_leads.
    Se mag_to_pay è passato, evita query ripetute su ManagedCampaign (batch API).
    """
    if not leads:
        return None
    mtp = mag_to_pay if mag_to_pay is not None else _get_mag_to_pay(db)
    pays = []
    for l in leads:
        if l.magellano_campaign_id and str(l.magellano_campaign_id) in mtp:
            pays.append(mtp[str(l.magellano_campaign_id)])
    if not pays:
        return None
    from collections import Counter
    counts = Counter(pays)
    return counts.most_common(1)[0][0]


def _compute_ricavo_for_leads(
    db: Session, leads: list, mag_to_pay: dict | None = None
) -> float:
    """
    Ricavo = somma del pay di ogni lead (ogni lead ha magellano_campaign_id -> campagna -> pay).
    Se mag_to_pay è passato, evita query ripetute su ManagedCampaign (batch API).
    """
    if not leads:
        return 0.0
    mtp = mag_to_pay if mag_to_pay is not None else _get_mag_to_pay(db)
    total = 0.0
    for l in leads:
        if l.magellano_campaign_id and str(l.magellano_campaign_id) in mtp:
            total += mtp[str(l.magellano_campaign_id)]
    return total


def _get_msg_to_pay(db: Session) -> dict:
    """Mappa msg_id (Ulixe) -> pay_level da ManagedCampaign.msg_ids."""
    managed = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()
    msg_to_pay = {}
    for mc in managed:
        if not mc.msg_ids or not mc.pay_level:
            continue
        try:
            pay_val = float(str(mc.pay_level).replace(',', '.'))
        except (ValueError, TypeError):
            continue
        for item in mc.msg_ids:
            if isinstance(item, dict):
                vid = item.get("id")
            else:
                vid = str(item)
            if vid:
                msg_to_pay[str(vid)] = pay_val
    return msg_to_pay


def _get_ricavo_from_rcrm_temp(db: Session, date_from, date_to) -> float:
    """
    Ricavo da ulixe_rcrm_temp: somma di (rcrm_count × pay per msg_id) per periodi nel range.
    Usato quando le approvate provengono da RCRM e non dalle lead.
    """
    date_from_d = date_from.date() if hasattr(date_from, "date") else date_from
    date_to_d = date_to.date() if hasattr(date_to, "date") else date_to
    periods = []
    y, m = date_from_d.year, date_from_d.month
    end_y, end_m = date_to_d.year, date_to_d.month
    while (y, m) <= (end_y, end_m):
        periods.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    if not periods:
        return 0.0
    msg_to_pay = _get_msg_to_pay(db)
    if not msg_to_pay:
        return 0.0
    rows = db.query(UlixeRcrmTemp.msg_id, UlixeRcrmTemp.rcrm_count).filter(
        UlixeRcrmTemp.period.in_(periods),
        UlixeRcrmTemp.msg_id.in_(list(msg_to_pay.keys())),
    ).all()
    total = 0.0
    for msg_id, rcrm_count in rows:
        pay = msg_to_pay.get(str(msg_id))
        if pay is not None and rcrm_count:
            total += rcrm_count * pay
    return total


def default_marketing_filter_date_range(now: datetime | None = None) -> tuple[datetime, datetime]:
    """
    Periodo predefinito filtri marketing: dal primo giorno del mese corrente a ieri (fine giornata).
    Il 1° del mese, «inizio mese» è dopo ieri: si usa solo ieri come estremo inferiore (intervallo di un giorno).
    """
    n = now or datetime.now()
    yesterday_d = n.date() - timedelta(days=1)
    month_start_d = n.replace(day=1, hour=0, minute=0, second=0, microsecond=0).date()
    from_d = month_start_d
    if from_d > yesterday_d:
        from_d = yesterday_d
    date_from = datetime.combine(from_d, datetime.min.time())
    date_to = datetime.combine(yesterday_d, datetime.max.time()).replace(microsecond=999999)
    return date_from, date_to


def _lead_date_filter(date_from_obj, date_to_obj):
    """Filtra lead per data: usa SEMPRE magellano_subscr_date (lead senza data subscr. escluse)."""
    date_from_d = date_from_obj.date() if hasattr(date_from_obj, "date") else date_from_obj
    date_to_d = date_to_obj.date() if hasattr(date_to_obj, "date") else date_to_obj
    return and_(
        Lead.magellano_subscr_date.isnot(None),
        Lead.magellano_subscr_date >= date_from_d,
        Lead.magellano_subscr_date <= date_to_d,
    )


def _parse_optional_int_param(params, key: str) -> int | None:
    raw = params.get(key)
    if raw is None or raw == "":
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def _meta_account_id_candidates(meta_account_id: str) -> list[str]:
    """Varianti stringa account Meta (come in URL / form), per filtri su MetaAccount.account_id."""
    raw = (meta_account_id or "").strip()
    if not raw:
        return []
    variants = [raw]
    if raw.lower().startswith("act_"):
        variants.append(raw[4:])
    else:
        variants.append(f"act_{raw}")
    seen: set[str] = set()
    out: list[str] = []
    for x in variants:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _resolve_meta_account_db_ids(db: Session, meta_account_id: str) -> list[int] | None:
    """
    PK interne meta_accounts per l'Ad Account Meta richiesto.
    Prova match esatto e variante act_<id> (come export_leads_by_account).
    Include tutte le righe attive con lo stesso account_id (stesso account, utenti diversi).
    """
    raw = (meta_account_id or "").strip()
    if not raw:
        return None
    candidates = [raw]
    if raw.lower().startswith("act_"):
        candidates.append(raw[4:])
    else:
        candidates.append(f"act_{raw}")
    acc = (
        db.query(MetaAccount)
        .filter(MetaAccount.account_id.in_(candidates), MetaAccount.is_active == True)
        .first()
    )
    if not acc:
        return None
    rows = (
        db.query(MetaAccount)
        .filter(MetaAccount.account_id == acc.account_id, MetaAccount.is_active == True)
        .all()
    )
    return [r.id for r in rows]


def _resolve_ad_meta_ids_for_sankey_name_scope(
    db: Session,
    campaign_name_q: str,
    adset_name_q: str,
    creative_name_q: str,
    analysis_status: str,
    meta_account_id: str | None,
) -> list[str] | None:
    """
    Se campagna/adset/creatività/stato campagna sono valorizzati, restituisce gli ad_id Meta (stringhe)
    per intersecare Lead.meta_ad_id. None = nessun filtro nome (non applicare).
    """
    cn = (campaign_name_q or "").strip()
    an = (adset_name_q or "").strip()
    cr = (creative_name_q or "").strip()
    st = (analysis_status or "all").strip().lower()
    if not cn and not an and not cr and st in ("", "all"):
        return None

    account_db_ids: list[int] | None = None
    if meta_account_id:
        account_db_ids = _resolve_meta_account_db_ids(db, meta_account_id)
        if not account_db_ids:
            return []

    q = (
        db.query(MetaAd.ad_id)
        .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
        .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
        .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
        .filter(MetaAccount.is_active == True)
    )
    if account_db_ids is not None:
        q = q.filter(MetaCampaign.account_id.in_(account_db_ids))
    if cn:
        q = q.filter(MetaCampaign.name.ilike(f"%{cn}%"))
    if an:
        q = q.filter(MetaAdSet.name.ilike(f"%{an}%"))
    if cr:
        q = q.filter(MetaAd.name.ilike(f"%{cr}%"))
    if st == "active":
        q = q.filter(MetaCampaign.status == "ACTIVE")
    elif st == "inactive":
        q = q.filter(MetaCampaign.status != "ACTIVE")

    out = [str(r[0]).strip() for r in q.distinct().all() if r[0]]
    return out


def _leads_for_lavorazioni_sankey(
    db: Session,
    date_from,
    date_to,
    meta_account_id: str | None,
    meta_campaign_id: str | None,
    adset_db_id: int | None,
    ad_db_id: int | None,
    campaign_name_q: str = "",
    adset_name_q: str = "",
    creative_name_q: str = "",
    analysis_status: str = "all",
    analysis_platform: str = "all",
) -> list:
    """
    Lead per Sankey lavorazioni: magellano_subscr_date nel periodo.
    Stessi filtri della pagina /marketing/analysis: account_id (stringa Meta), campaign_id (Meta),
    adset_id (PK riga MetaAdSet), opzionale ad_db_id (PK MetaAd).
    Senza filtri gerarchici: tutte le lead nel periodo (vista aggregata).
    """
    q = db.query(Lead).filter(_lead_date_filter(date_from, date_to))

    if meta_account_id:
        acc_db_ids = _resolve_meta_account_db_ids(db, meta_account_id)
        if not acc_db_ids:
            return []
        cands = _meta_account_id_candidates(meta_account_id)
        cids: set[str] = set()
        ad_ids: set[str] = set()

        for row in db.query(MetaCampaign.campaign_id).filter(MetaCampaign.account_id.in_(acc_db_ids)).all():
            if row[0]:
                cids.add(str(row[0]).strip())
        for row in (
            db.query(MetaAd.ad_id)
            .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
            .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
            .filter(MetaCampaign.account_id.in_(acc_db_ids))
            .distinct()
            .all()
        ):
            if row[0]:
                ad_ids.add(str(row[0]).strip())

        # Allineamento a Marketing Analysis: scope anche da metriche nel periodo (layer A + B),
        # con stesso account_id stringa del form (evita mismatch se la gerarchia campaign/ad è parziale).
        if cands:
            for tbl in (MetaMarketingData, MetaMarketingPlacement):
                mq = (
                    db.query(MetaCampaign.campaign_id, MetaAd.ad_id)
                    .select_from(tbl)
                    .join(MetaAd, tbl.ad_id == MetaAd.id)
                    .join(MetaAdSet, MetaAd.adset_id == MetaAdSet.id)
                    .join(MetaCampaign, MetaAdSet.campaign_id == MetaCampaign.id)
                    .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
                    .filter(
                        MetaAccount.is_active == True,
                        MetaAccount.account_id.in_(cands),
                        tbl.ad_id.isnot(None),
                        tbl.date >= date_from,
                        tbl.date <= date_to,
                    )
                )
                if meta_campaign_id:
                    mq = mq.filter(MetaCampaign.campaign_id == meta_campaign_id)
                if adset_db_id is not None:
                    mq = mq.filter(MetaAdSet.id == adset_db_id)
                for cid, aid in mq.distinct().all():
                    if cid:
                        cids.add(str(cid).strip())
                    if aid:
                        ad_ids.add(str(aid).strip())

        scope_parts = []
        if cids:
            scope_parts.append(Lead.meta_campaign_id.in_(list(cids)))
        if ad_ids:
            scope_parts.append(Lead.meta_ad_id.in_(list(ad_ids)))
        if not scope_parts:
            return []
        q = q.filter(or_(*scope_parts))

    if meta_campaign_id:
        q = q.filter(Lead.meta_campaign_id == meta_campaign_id)

    if adset_db_id is not None:
        adset = db.query(MetaAdSet).filter(MetaAdSet.id == adset_db_id).first()
        if not adset:
            return []
        q = q.filter(Lead.meta_adset_id == adset.adset_id)

    if ad_db_id is not None:
        ad = db.query(MetaAd).filter(MetaAd.id == ad_db_id).first()
        if not ad:
            return []
        q = q.filter(Lead.meta_ad_id == ad.ad_id)

    scope_ad_ids = _resolve_ad_meta_ids_for_sankey_name_scope(
        db,
        campaign_name_q,
        adset_name_q,
        creative_name_q,
        analysis_status,
        meta_account_id,
    )
    if scope_ad_ids is not None:
        if not scope_ad_ids:
            return []
        q = q.filter(Lead.meta_ad_id.in_(scope_ad_ids))

    ap = (analysis_platform or "all").strip().lower()
    if ap in ("facebook", "instagram"):
        q = q.filter(Lead.platform == ap)

    return q.all()


def _magellano_campaign_present(lead: Lead) -> bool:
    mid = lead.magellano_campaign_id
    return bool(mid and str(mid).strip())


LAVORAZIONI_SANKEY_DOPPIONI_NODE = "Doppioni Magellano · Stima"


def _lavorazioni_sankey_meta_node_label(cmap: dict[str, str], campaign_id: str) -> str:
    """Etichetta nodo Meta per un campaign_id (anche senza lead in lista)."""
    cid = (campaign_id or "").strip()
    if not cid:
        return "Meta · Non associata a campagna"
    name = (cmap.get(cid) or "").strip()
    label = name if name else cid
    if len(label) > 72:
        label = label[:69] + "…"
    return f"Meta · {label}"


def _lavorazioni_sankey_meta_node(lead: Lead, cmap: dict[str, str]) -> str:
    """Primo stadio: provenienza campagna Meta."""
    cid = str(lead.meta_campaign_id).strip() if lead.meta_campaign_id else ""
    return _lavorazioni_sankey_meta_node_label(cmap, cid)


def _lavorazioni_sankey_ingresso_magellano_node(lead: Lead) -> str:
    """Secondo stadio: barra ingresso (entrate reali vs senza campagna Magellano)."""
    if _magellano_campaign_present(lead):
        return "Ingresso Magellano · Entrate"
    return "Ingresso Magellano · Senza campagna Magellano"


def _is_sankey_scartata_ws(lead: Lead) -> bool:
    """
    Chiusura «Scartate WS»: rifiuto da WS (stato Magellano refused-from-WS, oppure post-invio).
    Esclude rifiuti solo lato firewall / pre-invio Magellano (magellano_firewall, waiting, ecc.).
    """
    st = (lead.magellano_status or "").strip()
    if st == "magellano_refused":
        return True
    if lead.status_category != StatusCategory.RIFIUTATO:
        return False
    if st == "magellano_sent":
        return True
    if (lead.ulixe_status or "").strip():
        return True
    if lead.ulixe_status_category == StatusCategory.RIFIUTATO:
        return True
    return False


def _lavorazioni_sankey_uscita_magellano_node(lead: Lead) -> str:
    """
    Terzo stadio. Prefisso «Uscite Magellano ·» per il client (provenienza Meta sui nodi uscita).
    Invii a WS in un solo nodo (nessuna scomposizione Ulixe).
    """
    if not _magellano_campaign_present(lead):
        return "Uscite Magellano · Fuori flusso Magellano"
    if _is_sankey_scartata_ws(lead):
        return "Uscite Magellano · Rifiutate da WS"
    st = (lead.magellano_status or "").strip()
    if st == "magellano_sent":
        return "Uscite Magellano · Inviate WS"
    return "Uscite Magellano · Rifiutate a firewall"


# Chiavi API (heatmap / query lavorazione=…). ws_inviate = tutte le lead magellano_sent (senza scomposizione Ulixe).
LAVORAZIONI_OUTCOME_BUCKET_ORDER = (
    "fuori_flusso",
    "scartate_firewall",
    "scartate_ws",
    "ws_inviate",
)

LAVORAZIONI_OUTCOME_LABELS_IT: dict[str, str] = {
    "fuori_flusso": "Senza ingresso Magellano",
    "scartate_firewall": "Rifiutate a firewall (pre-invio WS)",
    "scartate_ws": "Rifiutate da WS",
    "ws_inviate": "Inviate WS",
}

# Vecchi filtri heatmap (prima della rimozione stati Ulixe) → bucket aggregato.
_LEGACY_HEATMAP_WS_FILTERS = frozenset({"ws_in_lavorazione", "ws_crm", "ws_unknown", "ws_approvate"})

LAVORAZIONI_HEATMAP_STATUS_PARAMS = frozenset(LAVORAZIONI_OUTCOME_BUCKET_ORDER)


def lavorazioni_heatmap_lavorazione_filter_ui_payload() -> dict[str, Any]:
    """
    Opzioni «Stato lavorazione» per heatmap e per ogni UI che deve usare gli stessi bucket API (lavorazione=…).
    """
    return {
        "optgroup_label": "Magellano",
        "options": [
            {"value": key, "label": LAVORAZIONI_OUTCOME_LABELS_IT[key]}
            for key in LAVORAZIONI_OUTCOME_BUCKET_ORDER
        ],
    }


def lavorazioni_lead_outcome_bucket(lead: Lead) -> str:
    """Bucket esito per heatmap / filtri: stessa logica dei nodi uscita Sankey."""
    if not _magellano_campaign_present(lead):
        return "fuori_flusso"
    if _is_sankey_scartata_ws(lead):
        return "scartate_ws"
    st = (lead.magellano_status or "").strip()
    if st == "magellano_sent":
        return "ws_inviate"
    return "scartate_firewall"


def _lavorazioni_chart_day_range(date_from_obj, date_to_obj) -> list[str]:
    d0 = date_from_obj.date() if hasattr(date_from_obj, "date") else date_from_obj
    d1 = date_to_obj.date() if hasattr(date_to_obj, "date") else date_to_obj
    if d1 < d0:
        d0, d1 = d1, d0
    out: list[str] = []
    cur: date = d0
    while cur <= d1:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


# Serie per-lead: Magellano come in /marketing; niente scomposizione Ulixe (status_category) nel grafico giornaliero.
_MARKETING_PAGE_DAILY_SERIES: tuple[tuple[str, str], ...] = (
    ("magellano_entrate", "Ingresso Magellano · Entrate"),
    ("magellano_inviate", "Uscita Magellano · Inviate"),
    ("magellano_rifiutate", "Uscita Magellano · Rifiutate"),
    ("magellano_altro", "Magellano · In attesa (non inviate né rifiutate)"),
)

_MARKETING_PAGE_DAILY_COLORS = (
    "#6366f1",
    "#22c55e",
    "#ef4444",
    "#94a3b8",
)

_META_DAILY_LORDO_KEY = "meta_conversioni_lordo"
_META_DAILY_LORDO_LABEL = "Dati Meta · Lead (conversioni lordo)"
_META_DAILY_LORDO_COLOR = "#0f172a"


def _marketing_page_daily_increment_for_lead(day_bucket: defaultdict[str, int], lead: Lead) -> None:
    """Aggiorna i contatori per un giorno: stessi criteri della gerarchia marketing (conteggi sovrapposti)."""
    mag_in = _magellano_campaign_present(lead)
    if mag_in:
        day_bucket["magellano_entrate"] += 1
    st = (lead.magellano_status or "").strip()
    if st == "magellano_sent":
        day_bucket["magellano_inviate"] += 1
    elif st in ("magellano_firewall", "magellano_refused"):
        day_bucket["magellano_rifiutate"] += 1
    elif mag_in:
        # Lead in ingresso Magellano senza uscita inviate/rifiutate (non è una colonna marketing; riconciliazione)
        day_bucket["magellano_altro"] += 1


def build_lead_lavorazioni_daily_chart_payload(
    leads: list,
    date_from_obj,
    date_to_obj,
    *,
    meta_conversions_by_day: dict[str, int] | None = None,
) -> dict[str, Any]:
    """
    Serie giornaliere allineate a /marketing.
    - Lordo Meta: somma conversioni MetaMarketingData per giorno (data metrica), stessi filtri entity.
    - Serie per-lead: giorno = magellano_subscr_date; più serie possono contare lo stesso lead.
    Lo scarto ingresso giornaliero si legge come lordo Meta − entrate (non è una singola serie per-lead).
    """
    labels = _lavorazioni_chart_day_range(date_from_obj, date_to_obj)
    day_set = set(labels)
    counts: dict[str, defaultdict[str, int]] = {d: defaultdict(int) for d in labels}
    total_leads_in_range = 0
    for lead in leads:
        sd = lead.magellano_subscr_date
        if sd is None:
            continue
        day_s = sd.isoformat() if hasattr(sd, "isoformat") else str(sd)
        if len(day_s) > 10:
            day_s = day_s[:10]
        if day_s not in day_set:
            continue
        total_leads_in_range += 1
        _marketing_page_daily_increment_for_lead(counts[day_s], lead)

    meta_map = meta_conversions_by_day or {}
    meta_series = [int(meta_map.get(d, 0)) for d in labels]
    total_meta_conversions = int(sum(meta_series))

    cm = _META_DAILY_LORDO_COLOR
    datasets: list[dict[str, Any]] = [
        {
            "key": _META_DAILY_LORDO_KEY,
            "label": _META_DAILY_LORDO_LABEL,
            "data": meta_series,
            "backgroundColor": cm + "33",
            "borderColor": cm,
            "borderDash": [6, 4],
        }
    ]
    for i, (key, lbl) in enumerate(_MARKETING_PAGE_DAILY_SERIES):
        c = _MARKETING_PAGE_DAILY_COLORS[i % len(_MARKETING_PAGE_DAILY_COLORS)]
        datasets.append(
            {
                "key": key,
                "label": lbl,
                "data": [int(counts[d].get(key, 0)) for d in labels],
                "backgroundColor": c,
                "borderColor": c,
            }
        )
    return {
        "labels": labels,
        "datasets": datasets,
        "total_leads": total_leads_in_range,
        "total_meta_conversions": total_meta_conversions,
        "group_by": "marketing_page",
    }


def build_lead_lavorazioni_heatmap_payload(
    db: Session,
    leads: list,
    date_from_obj,
    date_to_obj,
    lavorazione_filter: str,
    top_n: int = 14,
) -> dict[str, Any]:
    """
    Heatmap giorno × campagna Meta (top N + Altre). Filtro lavorazione su bucket esito.
    """
    filt = (lavorazione_filter or "all").strip().lower()
    if filt in _LEGACY_HEATMAP_WS_FILTERS:
        filt = "ws_inviate"
    if filt != "all" and filt not in LAVORAZIONI_HEATMAP_STATUS_PARAMS:
        filt = "all"
    if filt != "all":
        leads = [l for l in leads if lavorazioni_lead_outcome_bucket(l) == filt]

    labels = _lavorazioni_chart_day_range(date_from_obj, date_to_obj)
    day_set = set(labels)
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for lead in leads:
        sd = lead.magellano_subscr_date
        if sd is None:
            continue
        day_s = sd.isoformat() if hasattr(sd, "isoformat") else str(sd)
        if day_s not in day_set:
            continue
        cid = str(lead.meta_campaign_id).strip() if lead.meta_campaign_id else ""
        pair_counts[(day_s, cid)] += 1

    camp_totals: dict[str, int] = defaultdict(int)
    for (d, cid), v in pair_counts.items():
        camp_totals[cid] += v

    sorted_cids = sorted(camp_totals.keys(), key=lambda x: (-camp_totals[x], x))
    top = sorted_cids[:top_n]
    other_cids = sorted_cids[top_n:]

    cmap: dict[str, str] = {}
    ids_q = [c for c in camp_totals if c]
    if ids_q:
        for row in db.query(MetaCampaign).filter(MetaCampaign.campaign_id.in_(ids_q)).all():
            cmap[str(row.campaign_id)] = (row.name or "").strip() or str(row.campaign_id)

    def camp_label(cid: str) -> str:
        if not cid:
            return "Senza campagna Meta"
        name = (cmap.get(cid) or cid).strip()
        if len(name) > 48:
            name = name[:45] + "…"
        return name

    row_keys: list[str] = list(top)
    if other_cids:
        row_keys.append("__altre__")
    y_labels = [camp_label(c) for c in top]
    if other_cids:
        y_labels.append("Altre campagne")

    heat_data: list[list[int]] = []
    max_v = 0
    for j, day in enumerate(labels):
        for i, rkey in enumerate(row_keys):
            if rkey == "__altre__":
                v = sum(pair_counts.get((day, c), 0) for c in other_cids)
            else:
                v = pair_counts.get((day, rkey), 0)
            if v > 0:
                heat_data.append([j, i, v])
                max_v = max(max_v, v)

    return {
        "days": labels,
        "y_labels": y_labels,
        "data": heat_data,
        "lavorazione": filt,
        "max_value": max_v,
        "row_count": len(y_labels),
        "lavorazione_filter_ui": lavorazioni_heatmap_lavorazione_filter_ui_payload(),
    }


def _lavorazioni_sankey_node_depth(node_name: str) -> int:
    """Allinea colonne ECharts: 0 Meta, 1 ingresso/doppioni, 2 uscite."""
    if node_name.startswith("Meta ·"):
        return 0
    if node_name.startswith("Ingresso Magellano ·") or node_name == LAVORAZIONI_SANKEY_DOPPIONI_NODE:
        return 1
    if node_name.startswith("Uscite Magellano ·"):
        return 2
    return 1


def build_lead_lavorazioni_sankey_data(
    db: Session,
    leads: list,
    *,
    conversions_by_meta_campaign: dict[str, int] | None = None,
) -> dict[str, Any]:
    """
    Dati Sankey (ECharts): (1) Meta → (2) Ingresso Magellano | Doppioni (stima) → (3) Uscite Magellano
    (rifiuti firewall/WS, invii WS aggregati). Richiede conversioni Meta per il nodo doppioni.
    """
    conv = conversions_by_meta_campaign or {}
    lead_count_by_cid: dict[str, int] = defaultdict(int)
    for lead in leads:
        cid = str(lead.meta_campaign_id).strip() if lead.meta_campaign_id else ""
        if cid:
            lead_count_by_cid[cid] += 1

    ids = {str(l.meta_campaign_id) for l in leads if l.meta_campaign_id} | {str(k).strip() for k in conv.keys() if k}
    cmap: dict[str, str] = {}
    if ids:
        for row in db.query(MetaCampaign).filter(MetaCampaign.campaign_id.in_(ids)).all():
            cmap[str(row.campaign_id)] = (row.name or "").strip() or str(row.campaign_id)

    meta_ingresso: dict[tuple[str, str], int] = defaultdict(int)
    ingresso_uscita: dict[tuple[str, str], int] = defaultdict(int)
    exit_meta_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for lead in leads:
        n0 = _lavorazioni_sankey_meta_node(lead, cmap)
        n1 = _lavorazioni_sankey_ingresso_magellano_node(lead)
        n2 = _lavorazioni_sankey_uscita_magellano_node(lead)
        meta_ingresso[(n0, n1)] += 1
        ingresso_uscita[(n1, n2)] += 1
        exit_meta_counts[n2][n0] += 1

    doppioni_by_meta_node: dict[str, int] = defaultdict(int)
    dopp_link_vals: dict[tuple[str, str], int] = defaultdict(int)
    for cid_raw, conv_n in conv.items():
        cid = str(cid_raw).strip()
        if not cid:
            continue
        dopp = max(0, int(conv_n or 0) - lead_count_by_cid.get(cid, 0))
        if dopp <= 0:
            continue
        meta_n = _lavorazioni_sankey_meta_node_label(cmap, cid)
        dopp_link_vals[(meta_n, LAVORAZIONI_SANKEY_DOPPIONI_NODE)] += dopp
        doppioni_by_meta_node[meta_n] += dopp

    all_names: set[str] = set()
    for (a, b) in meta_ingresso:
        all_names.add(a)
        all_names.add(b)
    for (a, b) in ingresso_uscita:
        all_names.add(a)
        all_names.add(b)
    for (s, t) in dopp_link_vals:
        all_names.add(s)
        all_names.add(t)

    nodes = [{"name": n, "depth": _lavorazioni_sankey_node_depth(n)} for n in sorted(all_names)]
    links: list[dict[str, Any]] = []
    for (s, t), v in meta_ingresso.items():
        links.append({"source": s, "target": t, "value": int(v)})
    for (s, t), v in ingresso_uscita.items():
        links.append({"source": s, "target": t, "value": int(v)})
    for (s, t), v in dopp_link_vals.items():
        links.append({"source": s, "target": t, "value": int(v)})

    exit_meta_breakdown: dict[str, list[dict[str, Any]]] = {}
    for exit_name, meta_map in exit_meta_counts.items():
        rows = [{"meta_node": m, "count": int(c)} for m, c in meta_map.items()]
        rows.sort(key=lambda r: -r["count"])
        exit_meta_breakdown[exit_name] = rows
    if doppioni_by_meta_node:
        d_rows = [{"meta_node": m, "count": int(c)} for m, c in doppioni_by_meta_node.items()]
        d_rows.sort(key=lambda r: -r["count"])
        exit_meta_breakdown[LAVORAZIONI_SANKEY_DOPPIONI_NODE] = d_rows

    total_doppioni = int(sum(doppioni_by_meta_node.values()))
    return {
        "nodes": nodes,
        "links": links,
        "total_leads": len(leads),
        "total_doppioni_stima": total_doppioni,
        "exit_meta_breakdown": exit_meta_breakdown,
    }


def _get_valid_msg_ids_from_managed(db: Session) -> set:
    """Msg_id configurati in ManagedCampaign (solo attive)."""
    managed = db.query(ManagedCampaign).filter(ManagedCampaign.is_active == True).all()
    valid = set()
    for mc in managed:
        if not mc.msg_ids:
            continue
        for item in mc.msg_ids:
            if isinstance(item, dict):
                vid = item.get("id")
                if vid:
                    valid.add(str(vid))
            else:
                valid.add(str(item))
    return {x for x in valid if x}


def get_unmapped_ulixe_ids(db: Session) -> list[str]:
    """
    Msg_id presenti in ulixe_rcrm_temp ma NON configurati in ManagedCampaign.
    Usato per avvisare che alcuni ID da export RCRM non sono mappati.
    """
    valid = _get_valid_msg_ids_from_managed(db)
    rcrm_msg_ids = db.query(UlixeRcrmTemp.msg_id).distinct().all()
    rcrm_set = {str(m[0]) for m in rcrm_msg_ids if m[0]}
    unmapped = sorted(rcrm_set - valid)
    return unmapped


def _get_ulixe_approvate_from_rcrm_temp(db: Session, date_from, date_to) -> int | None:
    """
    Somma RCRM dalla tabella provvisoria ulixe_rcrm_temp per i periodi nel range.
    Considera SOLO msg_id configurati in ManagedCampaign (esclude ID Ulixe non mappati).
    Ritorna None se non ci sono dati (usa status_category come fallback).
    """
    date_from_d = date_from.date() if hasattr(date_from, "date") else date_from
    date_to_d = date_to.date() if hasattr(date_to, "date") else date_to
    periods = []
    y, m = date_from_d.year, date_from_d.month
    end_y, end_m = date_to_d.year, date_to_d.month
    while (y, m) <= (end_y, end_m):
        periods.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    if not periods:
        return None
    valid_msg_ids = _get_valid_msg_ids_from_managed(db)
    if not valid_msg_ids:
        return None
    from sqlalchemy import func
    row = db.query(func.sum(UlixeRcrmTemp.rcrm_count)).filter(
        UlixeRcrmTemp.period.in_(periods),
        UlixeRcrmTemp.msg_id.in_(valid_msg_ids),
    ).scalar()
    # None = nessun record per periodi+msg_id validi -> fallback status_category
    if row is None:
        return None
    return int(row)  # 0 è valido (somma filtrata = 0)

def _parse_amount(val) -> float:
    """
    Normalizza importi provenienti da MetaMarketingData:
    - supporta tipi numerici (int/float/Decimal)
    - supporta vecchie stringhe EU (\"1.360,71\") e nuove US (\"1360.71\").
    """
    if val is None:
        return 0.0
    # Numerici puri
    if isinstance(val, (int, float)):
        return float(val)
    try:
        from decimal import Decimal
        if isinstance(val, Decimal):
            return float(val)
    except ImportError:
        pass
    s = str(val).strip()
    if not s:
        return 0.0
    if '.' in s and ',' in s:
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    return float(s)

