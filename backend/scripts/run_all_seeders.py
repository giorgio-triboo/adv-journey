#!/usr/bin/env python3
"""
Esegue tutti i seeder. Utile per produzione dopo deploy o per ripopolare dati.

Uso:
  python -m scripts.run_all_seeders
  docker exec adj-journey-backend-blue-1 python -m scripts.run_all_seeders
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from seeders.campaigns_seeder import seed_campaigns
from seeders.traffic_platforms_seeder import seed_traffic_platforms
from seeders.msg_traffic_mapping_seeder import seed_msg_traffic_mapping
from seeders.users_seeder import seed_users
from seeders.marketing_threshold_config_seeder import seed_marketing_threshold_config
from seeders.alert_config_seeder import seed_alert_configs


def main():
    print("Esecuzione seeder...")
    seed_campaigns()
    seed_traffic_platforms()
    seed_msg_traffic_mapping()
    seed_users()
    seed_marketing_threshold_config()
    seed_alert_configs()
    print("✓ Tutti i seeder completati")


if __name__ == "__main__":
    main()
