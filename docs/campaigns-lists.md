# Liste campagne: Lead (Magellano) e Meta

Per rigenerare il file: dalla root progetto con backend nel path, eseguire  
`python backend/scripts/list_campaigns_for_match.py` (oppure da container:  
`docker compose exec backend python scripts/list_campaigns_for_match.py`);  
lo script può essere esteso per riscrivere questo file.

---

## 1. Campagne associate alle lead (da Magellano)

Fonte: `leads.facebook_campaign_name`.

| Nome campagna (lead) | N. lead |
| --- | ---:|


| [CP] GS - CBO/01/25/117383 - 123 - form25 | 498 |
| [CP] GS - V1/0126/117383/UT DPerf | 84 |


**Totale distinte:** 5  
**Lead con campagna:** 1489

---

## 2. Campagne estratte da Meta (solo con "117383" nel nome)

Fonte: tabella `meta_campaigns`. Filtrate per nome contenente `117383`.

| Nome campagna (Meta) | Account | Meta campaign_id |
| --- | --- | --- |

| [CP] GS - CBO/01/26/117383 - 123 - form25 | 02 TribooEducation | 120218677344150067 |
| [CP] GS - V1/0126/117383/123 DPerf | Direct_Performance | 120241164384030092 |

| [CP] [ADC-DIP] - DIPLOMA - GDI/05/25/117383 - DT - form25 | 12 | 120225705242960233 |


**Totale campagne Meta (filtrate):** 6


| [CP] WEND - GS - GDI/01/25/117383 - 123 | 90 |
| [CP] WEND - GS - GDI/01/25/117383 - 123 | 02 TribooEducation | 120239225483460067 |


| AAA [CP] GS - CBO/01/26/117383 - 123 - form25 | 304 |
| AAA [CP] GS - CBO/01/26/117383 - 123 - form25 | 02 TribooEducation | 120240933449470067 |

| [CP] Cepu - GS - GDI/05/25/117383 - SLD - form25IE | 513 |
| [CP] [ADC-DIP] - DIPLOMA - GDI/05/25/117383 - SLD - form25IE | 12 | 120226589270710233 |