"""Площадки, которые проверены и заведомо не парсятся по HTTP.

Для них не делаем запрос вовсе: ответ всё равно будет заглушкой антибота,
а лишние запросы только повышают риск бана IP. Результаты проверки —
check_platforms.py (без VPN, российский IP).
"""
from scraping.base import Adapter, UnsupportedSiteError, domain_matches, host_of

UNSUPPORTED_PLATFORMS = {
    "ozon.ru": "Ozon",
    "wildberries.ru": "Wildberries",
    "wb.ru": "Wildberries",
    "avito.ru": "Авито",
    "dns-shop.ru": "DNS",
    "lemanapro.ru": "Лемана ПРО",
    "megamarket.ru": "Мегамаркет",
    "lamoda.ru": "Lamoda",
    "mvideo.ru": "М.Видео",
    "aliexpress.ru": "AliExpress",
}


class UnsupportedAdapter(Adapter):
    """Отклоняет известные неподдерживаемые площадки без сетевого запроса."""
    name = "Не поддерживается"
    domains = tuple(UNSUPPORTED_PLATFORMS)

    def reject(self, url):
        host = host_of(url)
        platform = next(name for domain, name in UNSUPPORTED_PLATFORMS.items()
                        if domain_matches(host, domain))
        raise UnsupportedSiteError(url, platform)

    def parse(self, page):
        self.reject(page.url)
