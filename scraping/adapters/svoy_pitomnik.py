"""Свой Питомник (OpenCart): JSON-LD нет, читаем HTML-вёрстку карточки."""
from typing import Optional
from urllib.parse import urljoin

from scraping.base import Adapter, Page, ProductSnapshot, parse_price

# Колонки карточки товара. Селекторы ограничены ими: ниже на странице есть блок
# похожих товаров с собственными ценами (.price-old2), которые нельзя подхватить.
INFO_COLUMN = "div.col-sm-7"
IMAGE_COLUMN = "div.col-sm-5"
# "price-specail" — опечатка в вёрстке самого сайта, встречается на части страниц
PRICE_SELECTORS = ("h2.price-special", "h2.price-specail", "h2")
OLD_PRICE_SELECTORS = ("span.price-old", "del")

NOT_FOUND_TITLE = "запрашиваемая страница не найдена"


class SvoyPitomnikAdapter(Adapter):
    name = "Свой Питомник"
    domains = ("svoy-pitomnik.ru",)

    def parse(self, page: Page) -> Optional[ProductSnapshot]:
        title = self.h1_text(page)
        info = page.soup.select_one(INFO_COLUMN)
        if not title or title.lower().startswith(NOT_FOUND_TITLE) or info is None:
            return None

        price = self._price(info, PRICE_SELECTORS)
        if price is None:
            return None
        price_old = self._price(info, OLD_PRICE_SELECTORS)
        if price_old is not None and price_old <= price:
            price_old = None

        image_url = ""
        image = page.soup.select_one(f"{IMAGE_COLUMN} img[src]")
        if image:
            image_url = urljoin(page.url, image["src"])

        return ProductSnapshot(
            title=title,
            price=price,
            price_old=price_old,
            image_url=image_url,
            source_url=page.url,
            platform=self.name,
        )

    @staticmethod
    def _price(container, selectors):
        for selector in selectors:
            element = container.select_one(selector)
            if element:
                price = parse_price(element.get_text(" ", strip=True))
                if price is not None:
                    return price
        return None
