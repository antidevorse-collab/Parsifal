"""Парсинг карточек товаров.

    from scraping import parse_product
    snapshot = parse_product(url)   # ProductSnapshot или ParseError

Выбор адаптера:
  1. площадка из списка неподдерживаемых — отказ без сетевого запроса;
  2. адаптер конкретной площадки по домену (Свой Питомник, Ситилинк, Маркет);
  3. иначе — универсальный JSON-LD адаптер для любого магазина с разметкой schema.org.

Новая площадка = новый класс Adapter в scraping/adapters и строка в SITE_ADAPTERS.
"""
from urllib.parse import urlparse

from scraping.adapters import (CitilinkAdapter, JsonLdAdapter, SvoyPitomnikAdapter,
                               UnsupportedAdapter, YandexMarketAdapter)
from scraping.base import (NotAProductError, OutOfStockError, ParseError, ProductSnapshot,
                           SiteBlockedError, SiteUnavailableError, UnsupportedSiteError, fetch,
                           format_price, host_of, parse_price)

_UNSUPPORTED = UnsupportedAdapter()
SITE_ADAPTERS = (SvoyPitomnikAdapter(), CitilinkAdapter(), YandexMarketAdapter())
GENERIC_ADAPTER = JsonLdAdapter()

SUPPORTED_PLATFORMS = tuple(a.name for a in SITE_ADAPTERS)

__all__ = ["parse_product", "platform_of","ProductSnapshot", "ParseError", "SiteBlockedError",
           "SiteUnavailableError", "NotAProductError", "OutOfStockError", "UnsupportedSiteError",
           "SUPPORTED_PLATFORMS", "format_price", "parse_price"]


def platform_of(url: str) -> str:
    """Название площадки по ссылке: имя адаптера или домен без www."""
    adapter = next((a for a in SITE_ADAPTERS if a.can_handle(url)), None)
    return adapter.name if adapter else host_of(url).removeprefix("www.")


def _validate_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise NotAProductError(url, f"Некорректная ссылка: {url}")


def parse_product(url: str) -> ProductSnapshot:
    url = url.strip()
    _validate_url(url)

    if _UNSUPPORTED.can_handle(url):
        _UNSUPPORTED.reject(url)

    adapter = next((a for a in SITE_ADAPTERS if a.can_handle(url)), None)
    page = fetch(url)

    if adapter is not None:
        snapshot = adapter.parse(page)
        if snapshot is None:
            raise NotAProductError(url, f"На странице не найден товар ({adapter.name}): {url}")
        return snapshot

    snapshot = GENERIC_ADAPTER.parse(page)
    if snapshot is None:
        raise NotAProductError(url, f"Сайт {host_of(url)} не поддерживается: "
                                    f"на странице нет стандартной разметки товара.")
    return snapshot
