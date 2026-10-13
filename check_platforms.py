"""Проверка площадок: какие магазины отдают название и цену товара с этой машины.

Запуск:  python check_platforms.py [доп. ссылки на товары ...]
Отчёт сохраняется в папку reports/.
"""
import json
import os
import sys
import time
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from network import detect_egress_country

try:  # необязательно: имитация TLS-отпечатка Chrome
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

# Площадка -> ссылка на реальную карточку товара (или главную, если карточки нет).
# Если ссылка устарела, замените её на любую карточку этой площадки.
PLATFORMS = {
    "Свой Питомник": "https://voronezh.svoy-pitomnik.ru/dekorativnye-kultury/akatsiya-belaya-3642",
    "Ситилинк": "https://www.citilink.ru/product/noutbuk-chuwi-minibook-x-u-series-u300-16gb-ssd512gb-10-51-ips-touch-f-2186288/",
    "Яндекс Маркет": "https://market.yandex.ru/card/casio-g-shock-gbm-2100a-4b/5043358260",
    "Ozon": "https://www.ozon.ru/product/fonar-nalobnyy-akkumulyatornyy-svetodiodnyy-led-s-zaryadkoy-5370441367/",
    "Wildberries": "https://www.wildberries.ru/catalog/169684889/detail.aspx",
    "Авито": "https://www.avito.ru/",
    "Мегамаркет": "https://megamarket.ru/",
    "М.Видео": "https://www.mvideo.ru/products/smartfon-apple-iphone-15-128gb-black-400213166",
    "DNS": "https://www.dns-shop.ru/",
    "Lamoda": "https://www.lamoda.ru/",
    "AliExpress": "https://aliexpress.ru/item/1005006136411346.html",
    "Лемана ПРО": "https://lemanapro.ru/",
}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept-Language": "ru-RU,ru;q=0.9",
}
TIMEOUT = 20
BLOCK_STATUSES = {401, 403, 429, 439, 498}
BLOCK_TITLE_MARKERS = ("доступ ограничен", "проверка безопасности", "похоже, нет соединения",
                       "captcha", "are you a robot", "загрузка...", "just a moment")
STUB_PAGE_MAX_LEN = 10_000

OK, PARTIAL, BLOCKED, JS, ERROR = "OK", "БЕЗ ЦЕНЫ", "БЛОКИРОВКА", "НУЖЕН JS", "ОШИБКА"


def extract_jsonld(soup):
    """Название и цена из schema.org Product (Ситилинк, Маркет и многие магазины)."""
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or tag.get_text())
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        for item in items:
            if isinstance(item, dict) and "Product" in str(item.get("@type")):
                offers = item.get("offers") or {}
                offers = offers[0] if isinstance(offers, list) and offers else offers
                price = offers.get("price") or offers.get("lowPrice") if isinstance(offers, dict) else None
                return item.get("name"), price
    return None, None


def extract_fallback(soup):
    """Название из <h1>, цена из микроразметки или селекторов OpenCart."""
    h1 = soup.select_one("h1")
    name = h1.get_text(strip=True) if h1 else None
    price_el = (soup.select_one('[itemprop="price"]') or soup.select_one("h2.price-special")
                or soup.select_one("div.col-sm-7 h2"))
    price = None
    if price_el:
        price = price_el.get("content") or price_el.get_text(strip=True)
    return name, price


def check(url, client):
    started = time.time()
    try:
        if client == "curl_cffi":
            r = curl_requests.get(url, impersonate="chrome", timeout=TIMEOUT, headers=HEADERS)
        else:
            r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
    except Exception as exc:
        return {"verdict": ERROR, "status": None, "detail": type(exc).__name__, "sec": time.time() - started}

    sec = time.time() - started
    # Байты, а не r.text: без charset в заголовке requests берёт latin-1,
    # а BeautifulSoup сам найдёт кодировку в <meta charset>
    soup = BeautifulSoup(r.content, "lxml")
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    result = {"status": r.status_code, "sec": sec, "size": len(r.text)}

    if r.status_code in BLOCK_STATUSES or any(m in page_title.lower() for m in BLOCK_TITLE_MARKERS):
        return {**result, "verdict": BLOCKED, "detail": page_title[:60] or f"HTTP {r.status_code}"}
    if r.status_code >= 400:
        return {**result, "verdict": ERROR, "detail": f"HTTP {r.status_code}"}

    name, price = extract_jsonld(soup)
    method = "JSON-LD"
    if not price:
        name2, price = extract_fallback(soup)
        name, method = name or name2, "HTML"

    if name and price:
        return {**result, "verdict": OK, "detail": f"{price} | {name[:45]}", "method": method}
    if not name and len(r.text) < STUB_PAGE_MAX_LEN:
        return {**result, "verdict": JS, "detail": "пустая JS-заглушка"}
    if name:
        return {**result, "verdict": PARTIAL, "detail": name[:50]}
    return {**result, "verdict": JS, "detail": "товар рендерится через JavaScript"}


def main():
    platforms = dict(PLATFORMS)
    for i, url in enumerate(sys.argv[1:], 1):
        platforms[f"{urlparse(url).netloc} #{i}"] = url

    clients = ["requests"] + (["curl_cffi"] if curl_requests else [])
    lines = []

    def out(text=""):
        print(text)
        lines.append(text)

    print("Чтобы проверить «чистую» сеть, перед запуском отключите VPN и туннели.\n")
    country = detect_egress_country()  # только код страны, IP не выводится
    out(f"Проверка площадок Parsifal — {datetime.now():%Y-%m-%d %H:%M}")
    out(f"Страна исходящего соединения: {country or '?'}"
        + ("   <-- похоже на VPN" if country and country != "RU" else ""))
    out(f"Методы: {', '.join(clients)}"
        + ("" if curl_requests else "   (curl_cffi не установлен: pip install curl_cffi)"))
    out()

    summary = {}
    for name, url in platforms.items():
        out(f"■ {name}  —  {urlparse(url).netloc}")
        for client in clients:
            res = check(url, client)
            summary.setdefault(name, []).append(res["verdict"])
            status = res.get("status") or "-"
            method = f" [{res['method']}]" if res.get("method") else ""
            out(f"    {client:<10} {res['verdict']:<11} HTTP {status:<4} {res['sec']:5.1f}с  {res['detail']}{method}")
        out()

    out("ИТОГ")
    for name, verdicts in summary.items():
        best = OK if OK in verdicts else verdicts[0]
        mark = "✅" if best == OK else ("⚠️" if best in (PARTIAL, JS) else "❌")
        out(f"  {mark} {name:<16} {best}")

    os.makedirs("reports", exist_ok=True)
    path = os.path.join("reports", f"platforms_{datetime.now():%Y%m%d_%H%M%S}.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"\nОтчёт сохранён: {os.path.abspath(path)}")


if __name__ == "__main__":
    main()
