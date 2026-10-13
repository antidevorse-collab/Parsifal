"""Тесты адаптеров на HTML-фикстурах, повторяющих разметку реальных площадок.

Запуск из корня проекта:  python -m unittest discover tests
"""
import json
import unittest
from decimal import Decimal
from unittest import mock

from bs4 import BeautifulSoup

import scraping
from scraping.base import Page, parse_price, format_price
from scraping.adapters import (CitilinkAdapter, JsonLdAdapter, SvoyPitomnikAdapter,
                               YandexMarketAdapter)


def page(url, html):
    return Page(url=url, status=200, html=html, soup=BeautifulSoup(html, "lxml"))


def jsonld_html(data, h1=""):
    return (f'<html><head><script type="application/ld+json">{json.dumps(data, ensure_ascii=False)}'
            f'</script></head><body><h1>{h1}</h1></body></html>')


class FakeResponse:
    def __init__(self, html, status=200):
        self.status_code = status
        self.content = html.encode("utf-8")
        self.text = html


class ParsePriceTest(unittest.TestCase):
    def test_formats(self):
        cases = {
            "902 ₽": Decimal("902"),
            "1 083 ₽": Decimal("1083"),
            "1\xa0990,50 руб.": Decimal("1990.50"),
            "39990": Decimal("39990"),
            "39990.00": Decimal("39990.00"),
            "1,990": Decimal("1990"),
            "1.990.000": Decimal("1990000"),
            7348: Decimal("7348"),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_price(raw), expected)

    def test_no_price(self):
        for raw in (None, "", "Нет в наличии", 0, "0 ₽", True):
            with self.subTest(raw=raw):
                self.assertIsNone(parse_price(raw))

    def test_format(self):
        self.assertEqual(format_price(Decimal("39990")), "39 990 ₽")
        self.assertEqual(format_price(Decimal("1990.5")), "1 990.50 ₽")


class JsonLdAdapterTest(unittest.TestCase):
    # Структура как на citilink.ru (2026-10)
    CITILINK = {
        "@context": "https://schema.org", "@type": "Product",
        "name": "Ноутбук CHUWI MiniBook X", "image": ["https://items.citilink.ru/1.jpg"],
        "offers": {"@type": "Offer", "priceCurrency": "RUB", "availability": "InStock",
                   "price": "39990", "url": "https://www.citilink.ru/product/x-2186288/"},
    }
    # Структура как на market.yandex.ru: цена числом, обобщённое name
    MARKET = {
        "@context": "https://schema.org", "@type": "Product", "name": "Наручные часы",
        "image": {"@type": "ImageObject", "url": "//avatars.mds.yandex.net/i.jpg"},
        "offers": {"@type": "Offer", "price": 18073, "priceCurrency": "RUB"},
    }

    def test_citilink(self):
        snap = CitilinkAdapter().parse(page("https://www.citilink.ru/product/x/", jsonld_html(self.CITILINK)))
        self.assertEqual(snap.title, "Ноутбук CHUWI MiniBook X")
        self.assertEqual(snap.price, Decimal("39990"))
        self.assertEqual(snap.image_url, "https://items.citilink.ru/1.jpg")
        self.assertEqual(snap.platform, "Ситилинк")

    def test_market_prefers_h1_and_resolves_image(self):
        url = "https://market.yandex.ru/card/casio/5043358260"
        snap = YandexMarketAdapter().parse(page(url, jsonld_html(self.MARKET, h1="Casio G-SHOCK GBM-2100A-4B")))
        self.assertEqual(snap.title, "Casio G-SHOCK GBM-2100A-4B")
        self.assertEqual(snap.price, Decimal("18073"))
        self.assertEqual(snap.image_url, "https://avatars.mds.yandex.net/i.jpg")

    def test_graph_aggregate_offer_and_old_price(self):
        data = {"@graph": [
            {"@type": "BreadcrumbList"},
            {"@type": ["Product"], "name": "Чайник",
             "offers": [{"@type": "AggregateOffer", "lowPrice": "2 490", "priceCurrency": "rub",
                         "priceSpecification": [{"priceType": "https://schema.org/StrikethroughPrice",
                                                 "price": 2990}]}]},
        ]}
        snap = JsonLdAdapter().parse(page("https://www.shop.example/kettle", jsonld_html(data)))
        self.assertEqual(snap.price, Decimal("2490"))
        self.assertEqual(snap.price_old, Decimal("2990"))
        self.assertEqual(snap.currency, "RUB")
        self.assertEqual(snap.platform, "shop.example")

    def test_no_product_or_price(self):
        no_price = dict(self.CITILINK, offers={"@type": "Offer", "availability": "InStock"})
        for html in (jsonld_html({"@type": "Organization", "name": "X"}),
                     jsonld_html(no_price),
                     '<script type="application/ld+json">{broken</script>'):
            with self.subTest(html=html[:60]):
                self.assertIsNone(JsonLdAdapter().parse(page("https://a.example/", html)))

    def test_out_of_stock(self):
        """Ситилинк для закончившегося товара отдаёт price "0" и OutOfStock (живая проверка 2026-10-12)."""
        sold_out = dict(self.CITILINK, offers={"@type": "Offer", "availability": "OutOfStock",
                                               "price": "0", "priceCurrency": "RUB"})
        with self.assertRaises(scraping.OutOfStockError) as ctx:
            CitilinkAdapter().parse(page("https://www.citilink.ru/product/x/", jsonld_html(sold_out)))
        self.assertEqual(str(ctx.exception), "Нет в наличии: Ноутбук CHUWI MiniBook X")


class SvoyPitomnikAdapterTest(unittest.TestCase):
    # Вёрстка voronezh.svoy-pitomnik.ru: ниже карточки — похожие товары со своими ценами
    HTML = """
    <html><body><h1>Акация Белая</h1>
      <div class="row">
        <div class="col-sm-5"><img src="/image/cache/akaciya.jpg"></div>
        <div class="col-sm-7"><h2 class="price-special">902 ₽</h2>{old}</div>
      </div>
      <div class="related"><span class="price-old2">4 511 ₽</span><h2>4 000 ₽</h2></div>
    </body></html>"""
    URL = "https://voronezh.svoy-pitomnik.ru/dekorativnye-kultury/akatsiya-belaya-3642"

    def test_product(self):
        snap = SvoyPitomnikAdapter().parse(page(self.URL, self.HTML.format(old="")))
        self.assertEqual(snap.title, "Акация Белая")
        self.assertEqual(snap.price, Decimal("902"))
        self.assertIsNone(snap.price_old, "старая цена соседнего товара не должна подхватываться")
        self.assertEqual(snap.image_url, "https://voronezh.svoy-pitomnik.ru/image/cache/akaciya.jpg")

    def test_old_price(self):
        html = self.HTML.format(old='<span class="price-old">1 022 ₽</span>')
        self.assertEqual(SvoyPitomnikAdapter().parse(page(self.URL, html)).price_old, Decimal("1022"))

    def test_site_typo_class(self):
        html = self.HTML.format(old="").replace("price-special", "price-specail")
        self.assertEqual(SvoyPitomnikAdapter().parse(page(self.URL, html)).price, Decimal("902"))

    def test_not_found_page(self):
        html = "<html><body><h1>Запрашиваемая страница не найдена!</h1><div class='col-sm-7'></div></body></html>"
        self.assertIsNone(SvoyPitomnikAdapter().parse(page(self.URL, html)))

    def test_any_region_subdomain(self):
        self.assertTrue(SvoyPitomnikAdapter().can_handle("https://moskva.svoy-pitomnik.ru/x"))
        self.assertFalse(SvoyPitomnikAdapter().can_handle("https://svoy-pitomnik.ru.evil.example/x"))


class RegistryTest(unittest.TestCase):
    def test_unsupported_without_request(self):
        with mock.patch("scraping.base.requests.get") as get:
            for url in ("https://www.ozon.ru/product/x-1/", "https://www.wildberries.ru/catalog/1/detail.aspx"):
                with self.subTest(url=url):
                    with self.assertRaises(scraping.UnsupportedSiteError):
                        scraping.parse_product(url)
            get.assert_not_called()

    def test_invalid_url(self):
        for url in ("ftp://a.example/x", "file:///etc/passwd", "просто текст"):
            with self.subTest(url=url), self.assertRaises(scraping.NotAProductError):
                scraping.parse_product(url)

    def test_blocked_and_stub_pages(self):
        cases = [FakeResponse("<html><title>403</title></html>", 403),
                 FakeResponse("<html><title>Доступ ограничен: проверка безопасности</title><h1>x</h1></html>"),
                 FakeResponse("<html><script>challenge()</script></html>")]
        for response in cases:
            with self.subTest(status=response.status_code), \
                    mock.patch("scraping.base.requests.get", return_value=response), \
                    self.assertRaises(scraping.SiteBlockedError):
                scraping.parse_product("https://www.citilink.ru/product/x/")

    def test_recaptcha_script_is_not_a_block(self):
        html = SvoyPitomnikAdapterTest.HTML.format(old="").replace(
            "<body>", '<head><script src="https://www.google.com/recaptcha/api.js"></script></head><body>')
        with mock.patch("scraping.base.requests.get", return_value=FakeResponse(html)):
            snap = scraping.parse_product(SvoyPitomnikAdapterTest.URL)
        self.assertEqual(snap.platform, "Свой Питомник")

    def test_generic_site_without_markup(self):
        html = "<html><body><h1>О компании</h1>" + "x" * 20000 + "</body></html>"
        with mock.patch("scraping.base.requests.get", return_value=FakeResponse(html)), \
                self.assertRaises(scraping.NotAProductError):
            scraping.parse_product("https://unknown-shop.example/about")


if __name__ == "__main__":
    unittest.main()
