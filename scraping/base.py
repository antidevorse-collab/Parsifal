"""Общие типы парсинга: снимок товара, ошибки, загрузка страниц, базовый адаптер."""
import re
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept-Language": "ru-RU,ru;q=0.9",
}
TIMEOUT = 15

# Коды, которыми антибот-системы отклоняют запрос (439 — Авито, 498 — Wildberries)
BLOCK_STATUSES = {401, 403, 429, 439, 498}
# Признаки страниц-заглушек в <title>; ищем только там, потому что обычные
# страницы магазинов содержат в коде, например, скрипт google.com/recaptcha
BLOCK_TITLE_MARKERS = ("доступ ограничен", "проверка безопасности", "похоже, нет соединения",
                       "доступ к сервису временно запрещён", "captcha", "are you a robot",
                       "загрузка...", "just a moment")
# Страница меньше этого размера и без <h1> — JS-заглушка антибота, а не карточка товара
STUB_PAGE_MAX_LEN = 10_000

CURRENCY_SIGNS = {"RUB": "₽", "RUR": "₽", "USD": "$", "EUR": "€"}


# ---------- Ошибки ----------

class ParseError(Exception):
    """Базовая ошибка парсинга; str(err) — сообщение для пользователя."""

    def __init__(self, url, message):
        self.url = url
        self.host = host_of(url)
        super().__init__(message)


class SiteBlockedError(ParseError):
    """Сайт отклонил запрос: антибот-защита или блокировка по стране (VPN).
    Причину определяет вызывающий код — см. app.blocked_sites_message."""

    def __init__(self, url, status):
        self.status = status
        super().__init__(url, f"{host_of(url)} отклонил запрос (HTTP {status})")


class UnsupportedSiteError(ParseError):
    """Площадка известна и заведомо не парсится по HTTP (антибот или JS-рендеринг)."""

    def __init__(self, url, platform):
        self.platform = platform
        super().__init__(url, f"{platform} пока не поддерживается: площадка защищена от "
                              f"автоматических запросов.")


class SiteUnavailableError(ParseError):
    pass


class NotAProductError(ParseError):
    pass


class OutOfStockError(ParseError):
    """Карточка товара есть, но цены нет: товар закончился или снят с продажи."""

    def __init__(self, url, title):
        self.title = title
        super().__init__(url, f"Нет в наличии: {title}")


# ---------- Данные ----------

@dataclass(frozen=True)
class ProductSnapshot:
    """Состояние карточки товара в момент парсинга."""
    title: str
    price: Decimal
    source_url: str
    platform: str
    price_old: Optional[Decimal] = None
    currency: str = "RUB"
    image_url: str = ""

    def to_dict(self):
        """Сериализуемое представление (для сессии и шаблонов)."""
        data = asdict(self)
        data["price"] = str(self.price)
        data["price_old"] = str(self.price_old) if self.price_old is not None else None
        data["price_display"] = format_price(self.price, self.currency)
        data["price_old_display"] = format_price(self.price_old, self.currency) if self.price_old else ""
        return data


# ---------- Утилиты ----------

def host_of(url):
    return (urlparse(url).hostname or url).lower()


def domain_matches(host, domain):
    """True, если host — это domain или его поддомен (voronezh.svoy-pitomnik.ru)."""
    return host == domain or host.endswith("." + domain)


_PRICE_JUNK = re.compile(r"[^\d,.]")


def parse_price(value) -> Optional[Decimal]:
    """'1 990 ₽', '1\xa0990,50 руб.', 39990, '39990.00' -> Decimal. None, если цены нет."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)) if value > 0 else None
    text = _PRICE_JUNK.sub("", str(value)).strip(".,")
    if not text:
        return None
    if "," in text and "." in text:          # 1.990,50 или 1,990.50
        decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
        text = text.replace("." if decimal_sep == "," else ",", "").replace(",", ".")
    elif "," in text:
        whole, _, frac = text.rpartition(",")
        text = f"{whole.replace(',', '')}.{frac}" if len(frac) <= 2 else text.replace(",", "")
    elif text.count(".") > 1:                  # 1.990.000 — разделители тысяч
        text = text.replace(".", "")
    try:
        price = Decimal(text)
    except InvalidOperation:
        return None
    return price if price > 0 else None


def format_price(price, currency="RUB"):
    if price is None:
        return ""
    value = int(price) if price == price.to_integral_value() else price.quantize(Decimal("0.01"))
    number = f"{value:,}".replace(",", " ")
    return f"{number} {CURRENCY_SIGNS.get(currency, currency)}"


# ---------- Загрузка ----------

@dataclass
class Page:
    url: str
    status: int
    html: str
    soup: BeautifulSoup


def fetch(url) -> Page:
    """Загружает страницу; бросает ParseError, если товара на ней заведомо нет."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise SiteUnavailableError(url, f"Не удалось подключиться к {host_of(url)}: "
                                        f"{type(exc).__name__}") from exc

    if response.status_code in BLOCK_STATUSES:
        raise SiteBlockedError(url, response.status_code)
    if response.status_code == 404:
        raise NotAProductError(url, f"Страница не найдена: {url}")
    if response.status_code >= 400:
        raise SiteUnavailableError(url, f"{host_of(url)} вернул ошибку HTTP {response.status_code}")

    # Байты, а не response.text: без charset в заголовке requests берёт latin-1,
    # а BeautifulSoup сам найдёт кодировку в <meta charset>
    soup = BeautifulSoup(response.content, "lxml")
    page_title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    if any(marker in page_title for marker in BLOCK_TITLE_MARKERS):
        raise SiteBlockedError(url, response.status_code)
    if not soup.select_one("h1") and len(response.content) < STUB_PAGE_MAX_LEN:
        raise SiteBlockedError(url, response.status_code)

    return Page(url=url, status=response.status_code, html=response.text, soup=soup)


# ---------- Адаптер ----------

class Adapter:
    """Парсер одной площадки (или семейства сайтов).

    name    — название площадки для пользователя;
    domains — домены, которые адаптер обслуживает (поддомены включаются).
              Пустой кортеж — универсальный адаптер, пробуется для любых сайтов.
    """
    name: str = ""
    domains: tuple = ()

    def can_handle(self, url) -> bool:
        host = host_of(url)
        return any(domain_matches(host, d) for d in self.domains)

    def parse(self, page: Page) -> Optional[ProductSnapshot]:
        """Снимок товара или None, если адаптер не узнал товар на странице."""
        raise NotImplementedError

    def h1_text(self, page: Page) -> str:
        h1 = page.soup.select_one("h1")
        return h1.get_text(" ", strip=True) if h1 else ""
