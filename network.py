"""Диагностика сети: определяем страну, через которую сервер выходит в интернет.

Используется, только когда магазин отклонил запрос: если выход не из ожидаемой
страны, вероятная причина — VPN; иначе сайт просто защищён от автоматических
запросов. IP-адрес не сохраняется и не показывается — нужен лишь код страны.
"""
from typing import Optional

import requests

# Сервисы геолокации IP: (url, поле с кодом страны). Опрашиваются по очереди.
_GEO_PROVIDERS = (
    ("https://ipinfo.io/json", "country"),
    ("http://ip-api.com/json/?fields=countryCode", "countryCode"),
    ("https://api.country.is/", "country"),
)
_TIMEOUT = 3


def detect_egress_country() -> Optional[str]:
    """Код страны исходящего соединения (например, 'RU') или None, если не удалось определить."""
    for url, country_field in _GEO_PROVIDERS:
        try:
            country = requests.get(url, timeout=_TIMEOUT).json().get(country_field)
        except (requests.RequestException, ValueError):
            continue
        if country:
            return country.upper()
    return None
