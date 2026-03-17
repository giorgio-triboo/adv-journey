import argparse
from datetime import datetime

from playwright.sync_api import sync_playwright

from services.integrations.magellano_automation import MagellanoAutomation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Debug visuale STEP 2 Magellano (export_fetch)")
    parser.add_argument("--campaign", type=int, required=True, help="ID campagna Magellano")
    parser.add_argument("--start-date", required=True, help="Data inizio (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="Data fine (YYYY-MM-DD)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()

    # headless=False per avere la GUI del browser
    automation = MagellanoAutomation(headless=False)

    with sync_playwright() as p:
        # Usa come password_date il giorno in cui è stato richiesto l'export.
        # Per debug locale assumiamo che coincida con oggi.
        from datetime import date as _date

        password_date = _date.today()

        leads = automation.fetch_export_and_process(
            p,
            campaign_number=args.campaign,
            start_date=start_date,
            end_date=end_date,
            password_date=password_date,
            download_dir=".",
        )

    if not leads:
        print("Nessuna lead trovata: export non pronto / non trovato.")
    else:
        print(f"Leads trovate: {len(leads)}")


if __name__ == "__main__":
    main()

