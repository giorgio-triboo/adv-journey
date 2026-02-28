# Server-side integration with Meta Conversions API (CAPI)

## Overview

This document describes a backend system that integrates with **Meta Conversions API (CAPI)** to send server-side conversion events. The platform manages leads and their lifecycle; when a lead’s status changes, the system sends corresponding custom events to Meta for attribution and optimization.

The integration is **abstract and product-agnostic**: it can be used with any Meta Business account, Pixel, or Dataset, and does not depend on specific client or product names.

---

## Architecture (high level)

- **Backend**: Python (FastAPI), relational DB, scheduled sync jobs.
- **Data sources**: External CRM/ERP and other internal systems are synced into a central data store (leads, campaigns, history).
- **Meta integration**:
  - **Conversions API (CAPI)**: server-side event sending (this document).
  - **Marketing API**: read-only ingestion of ad account data (campaigns, adsets, ads, insights) for reporting and attribution.

No reference is made to specific third-party products or brands beyond “Meta” and “Conversions API”.

---

## Conversions API (CAPI) – role in the system

### Purpose

- Send **server-side events** to Meta when lead status changes (e.g. new lead, in progress, converted, rejected).
- Improve attribution and measurement by pairing server-side events with client-side signals (e.g. Pixel).
- Support optimization and reporting using first-party lead outcomes.

### Event flow

1. **Lead status updates**  
   Leads are updated from internal systems (CRM/ERP sync, manual updates, etc.). Each lead can be linked to Meta campaign/adset/ad IDs when the lead originated from Meta ads.

2. **Selection of leads to sync**  
   A dedicated job (“conversion marker”) selects leads whose status has changed since the last event sent to Meta. Only leads that need an update are processed.

3. **Sending events**  
   For each selected lead, the system:
   - Resolves the correct Meta access token (per ad account or shared).
   - Resolves the target for events: **Dataset ID** (preferred) or **Pixel ID**.
   - Builds a CAPI event with:
     - **event_name**: custom event name reflecting the lead status (e.g. status-based custom events).
     - **event_time**: Unix timestamp.
     - **user_data**: matching signals (e.g. hashed email, hashed phone, state/region when available). Email and phone are sent as SHA-256 hashes in line with Meta’s recommendations.
     - **custom_data**: optional fields; when available, **campaign_id**, **adset_id**, **ad_id** are included for attribution.
     - **action_source**: `"system_generated"` (server-side, no browser).
   - Sends the event to Meta via **Graph API** (`POST .../v18.0/{pixel_id|dataset_id}/events`).

4. **Idempotency and state**  
   After a successful send, the system stores the last event status for the lead so the same status is not sent again. Only new status changes trigger new events.

### Technical details (CAPI)

- **Endpoint**: Graph API, `https://graph.facebook.com/v23.0/{pixel_id|dataset_id}/events`.
- **Payload**: JSON with `data` array of events and `access_token`.
- **User data**: Email and phone are hashed (SHA-256) before sending; no raw PII is sent to Meta.
- **Target**: Events can be sent to a **Dataset** or to a **Pixel**; the implementation supports both and uses Dataset when configured.
- **Attribution**: When the lead is linked to a Meta campaign/adset/ad, those IDs are passed in `custom_data` so Meta can attribute the conversion to the right ad.

### Security and compliance

- Access tokens are stored encrypted and are not logged.
- Only hashed user_data (and optional region) are sent; no plaintext PII in event payloads.
- Rate limiting and error handling are applied to avoid abuse and to respect API limits.

---

## Sync pipeline (where CAPI fits)

The CAPI send is part of a larger sync pipeline that runs on a schedule (e.g. nightly):

1. **Data sync** – Import/update leads and related data from external systems.
2. **Marketing data sync** – Pull Meta Marketing API data (campaigns, ads, insights) for reporting.
3. **Conversion marker** – Mark leads whose status has changed and should be sent to CAPI.
4. **Conversion sync (CAPI)** – Send the corresponding server-side events to Meta.

The pipeline is sequential and logged; failed steps can be retried or inspected without re-sending duplicate events for already-synced statuses.

---

## What we send to Meta (summary)

| Aspect | Description |
|--------|-------------|
| **When** | When a lead’s status changes and the lead is selected by the conversion-marker job. |
| **Where** | Graph API: `/{pixel_id or dataset_id}/events`. |
| **What** | One event per status change: custom `event_name`, `event_time`, `user_data` (hashed), `custom_data` (optional campaign/adset/ad IDs), `action_source: system_generated`. |
| **Why** | To improve attribution, measurement, and optimization of Meta ad campaigns using first-party lead outcomes. |

---

## Contact and use

This integration is designed to work with any Meta Business account and CAPI setup. For questions about the technical implementation or CAPI compliance, the development team can provide code-level details (excluding any client- or product-specific naming).
