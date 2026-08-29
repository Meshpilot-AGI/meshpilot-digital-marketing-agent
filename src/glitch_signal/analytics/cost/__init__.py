"""Per-brand cost metering across vendors (COST-METER). Self-meter every model/media call at our
own choke points, attribute it to the active brand, and cost it from a maintained price book."""
from glitch_signal.analytics.cost.context import brand_scope, get_brand, set_brand
from glitch_signal.analytics.cost.meter import record_usage, spend_summary

__all__ = ["brand_scope", "get_brand", "set_brand", "record_usage", "spend_summary"]
