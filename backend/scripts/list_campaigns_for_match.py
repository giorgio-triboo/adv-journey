"""
Lista campagne: (1) associate alle lead (da Magellano), (2) estratte da Meta.
Utile per capire come fare match quando i nomi sono cambiati.
"""
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from sqlalchemy import func
from database import SessionLocal
from models import Lead, MetaCampaign, MetaAccount


def main():
    db = SessionLocal()
    try:
        # --- 1. Campagne dalle lead (nome che arriva da Magellano: facebook_campaign_name) ---
        q_lead = (
            db.query(Lead.facebook_campaign_name, func.count(Lead.id).label("count"))
            .filter(Lead.facebook_campaign_name.isnot(None))
            .filter(Lead.facebook_campaign_name != "")
            .group_by(Lead.facebook_campaign_name)
            .order_by(Lead.facebook_campaign_name)
        )
        lead_campaigns = q_lead.all()

        # --- 2. Campagne da Meta (tabella meta_campaigns) ---
        meta_campaigns = (
            db.query(MetaCampaign.name, MetaCampaign.campaign_id, MetaAccount.name.label("account_name"))
            .join(MetaAccount, MetaCampaign.account_id == MetaAccount.id)
            .order_by(MetaCampaign.name)
            .all()
        )

        # --- Output ---
        print("=" * 80)
        print("CAMPAGNE ASSOCIATE ALLE LEAD (da Magellano – facebook_campaign_name)")
        print("=" * 80)
        print(f"{'Nome campagna (lead)':<60} {'N. lead':>10}")
        print("-" * 72)
        for name, count in lead_campaigns:
            display_name = (name or "").strip()
            if len(display_name) > 58:
                display_name = display_name[:55] + "..."
            print(f"{display_name:<60} {count:>10}")
        print("-" * 72)
        print(f"Totale distinte: {len(lead_campaigns)}  |  Lead con campagna: {sum(c for _, c in lead_campaigns)}")
        print()

        print("=" * 80)
        print("CAMPAGNE ESTRATTE DA META (meta_campaigns)")
        print("=" * 80)
        print(f"{'Nome campagna (Meta)':<55} {'Account':<20} {'Meta campaign_id':<20}")
        print("-" * 95)
        for name, campaign_id, account_name in meta_campaigns:
            display_name = (name or "").strip()
            if len(display_name) > 53:
                display_name = display_name[:50] + "..."
            acc = (account_name or "")[:18]
            cid = (campaign_id or "")[:18]
            print(f"{display_name:<55} {acc:<20} {cid:<20}")
        print("-" * 95)
        print(f"Totale campagne Meta: {len(meta_campaigns)}")
        print()

        # --- Scrivi docs/campaigns-lists.md ---
        docs_dir = os.path.join(PROJECT_ROOT, "..", "docs")
        os.makedirs(docs_dir, exist_ok=True)
        md_path = os.path.join(docs_dir, "campaigns-lists.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# Liste campagne: Lead (Magellano) e Meta\n\n")
            f.write("Generate dallo script `backend/scripts/list_campaigns_for_match.py`.\n\n")
            f.write("---\n\n")
            f.write("## 1. Campagne associate alle lead (da Magellano)\n\n")
            f.write("Fonte: `leads.facebook_campaign_name`.\n\n")
            f.write("| Nome campagna (lead) | N. lead |\n")
            f.write("| --- | ---:|\n")
            for name, count in lead_campaigns:
                safe_name = (name or "").replace("|", "\\|")
                f.write(f"| {safe_name} | {count} |\n")
            f.write("\n**Totale distinte:** " + str(len(lead_campaigns)) + "  \n")
            f.write("**Lead con campagna:** " + str(sum(c for _, c in lead_campaigns)) + "\n\n")
            f.write("---\n\n")
            f.write("## 2. Campagne estratte da Meta\n\n")
            f.write("Fonte: tabella `meta_campaigns`.\n\n")
            f.write("| Nome campagna (Meta) | Account | Meta campaign_id |\n")
            f.write("| --- | --- | --- |\n")
            for name, campaign_id, account_name in meta_campaigns:
                safe_name = (name or "").replace("|", "\\|")
                f.write(f"| {safe_name} | {account_name or ''} | {campaign_id or ''} |\n")
            f.write("\n**Totale campagne Meta:** " + str(len(meta_campaigns)) + "\n")
        print(f"Scritto: {md_path}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
