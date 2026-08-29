-- Dedup guard for usage_events (#97): a retried/re-polled vendor call carrying the same
-- (vendor, request_id) must not be counted twice. Partial unique index (request_id may be null for
-- calls we can't key, e.g. Anthropic chat without an id — those stay un-deduped by design).
-- meter.record_usage uses ON CONFLICT (vendor, request_id) WHERE request_id IS NOT NULL DO NOTHING.

create unique index if not exists usage_events_vendor_request_id_uidx
  on usage_events (vendor, request_id)
  where request_id is not null;
