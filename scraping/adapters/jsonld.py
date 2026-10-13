"""Универсальный адаптер: читает разметку schema.org Product (JSON-LD).

Такую разметку магазины публикуют для поисковиков, поэтому адаптер работает
на Ситилинке, Яндекс Маркете и большинстве интернет-магазинов без отдельного кода.
"""
import json
from typing import Iterator, Optional
from urllib.parse import urljoin

from scraping.base import Adapter, OutOfStockError, Page, ProductSnapshot, host_of, parse_price


def _iter_nodes(data) -> Iterator[dict]:
    """Обходит JSON-LD: списки, @graph и вложенные объекты."""
    if isinstance(data, list):
        for item in data:
            yield from _iter_nodes(item)
    elif isinstance(data, dict):
        yield data
        if "@graph" in data:
            yield from _iter_nodes(data["@graph"])


def _is_product(node: dict) -> bool:
    types = node.get("@type")
    types = types if isinstance(types, list) else [types]
    return any(t in ("Product", "ProductGroup", "IndividualProduct") for t in types)


def _first(value):
    return value[0] if isinstance(value, list) and value else value


def _image_url(image) -> str:
    image = _first(image)
    if isinstance(image, dict):
        image = image.get("contentUrl") or image.get("url")
    return image if isinstance(image, str) else ""


def _offer_prices(offers):
    """(цена, старая цена, валюта) из offers — Offer, AggregateOffer или списка."""
    offers = offers if isinstance(offers, list) else [offers]
    prices = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        price = parse_price(offer.get("price")) or parse_price(offer.get("lowPrice"))
        spec = _first(offer.get("priceSpecification"))
        if price is None and isinstance(spec, dict):
            price = parse_price(spec.get("price"))
        if price is not None:
            prices.append((price, offer.get("priceCurrency") or "RUB", offer))
    if not prices:
        return None, None, "RUB"

    price, currency, offer = min(prices, key=lambda p: p[0])
    return price, _old_price(offer, price), currency.upper()


_OUT_OF_STOCK = ("OutOfStock", "SoldOut", "Discontinued")


def _is_out_of_stock(offers) -> bool:
    """True, если все предложения помечены как отсутствующие (schema.org/ItemAvailability)."""
    offers = [o for o in (offers if isinstance(offers, list) else [offers]) if isinstance(o, dict)]
    return bool(offers) and all(
        any(s in str(o.get("availability")) for s in _OUT_OF_STOCK) for o in offers)


_OLD_PRICE_TYPES =("ListPrice", "StrikethroughPrice", "MSRP")


def _old_price(offer: dict, price):
    """Старая цена из priceSpecification с типом ListPrice / StrikethroughPrice."""
    specs = offer.get("priceSpecification") or []
    for spec in specs if isinstance(specs, list) else [specs]:
        if not isinstance(spec, dict):
            continue
        if any(t in str(spec.get("priceType")) for t in _OLD_PRICE_TYPES):
            old = parse_price(spec.get("price"))
            if old is not None and old > price:
                return old
    return None


def extract_product(page: Page) -> Optional[dict]:
    """Первый узел schema.org Product со страницы или None."""
    for tag in page.soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or tag.get_text())
        except (ValueError, TypeError):
            continue
        for node in _iter_nodes(data):
            if _is_product(node):
                return node
    return None


class JsonLdAdapter(Adapter):
    name = "Интернет-магазин"
    domains = ()  # универсальный

    # Название из <h1> точнее, если в JSON-LD лежит обобщённое ("Наручные часы")
    prefer_h1_title = False

    def parse(self, page: Page) -> Optional[ProductSnapshot]:
        node = extract_product(page)
        if node is None:
            return None

        ld_title = str(node.get("name") or "").strip()
        h1 = self.h1_text(page)
        title = (h1 or ld_title) if self.prefer_h1_title else (ld_title or h1)
        if not title:
            return None

        price, price_old, currency = _offer_prices(node.get("offers"))
        if price is None:
            # Ситилинк для закончившегося товара отдаёт price "0" и OutOfStock
            if _is_out_of_stock(node.get("offers")):
                raise OutOfStockError(page.url, title)
            return None

        image = _image_url(node.get("image"))
        return ProductSnapshot(
            title=title,
            price=price,
            price_old=price_old,
            currency=currency,
            image_url=urljoin(page.url, image) if image else "",
            source_url=page.url,
            platform=self.platform_name(page),
        )

    def platform_name(self, page: Page) -> str:
        # Универсальный адаптер называет площадку по домену
        return self.name if self.domains else host_of(page.url).removeprefix("www.")


class CitilinkAdapter(JsonLdAdapter):
    name = "Ситилинк"
    domains = ("citilink.ru",)


class YandexMarketAdapter(JsonLdAdapter):
    name = "Яндекс Маркет"
    domains = ("market.yandex.ru",)
    prefer_h1_title = True
