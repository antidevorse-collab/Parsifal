from scraping.adapters.jsonld import CitilinkAdapter, JsonLdAdapter, YandexMarketAdapter
from scraping.adapters.svoy_pitomnik import SvoyPitomnikAdapter
from scraping.adapters.unsupported import UnsupportedAdapter

__all__ = ["CitilinkAdapter", "JsonLdAdapter", "SvoyPitomnikAdapter",
           "UnsupportedAdapter", "YandexMarketAdapter"]
