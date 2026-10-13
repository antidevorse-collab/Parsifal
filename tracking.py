"""Перепроверка цен отслеживаемых товаров — источник истории цен.

Каждая успешная проверка добавляет точку в PriceHistory и обновляет карточку
товара; неуспешная — сохраняет причину в Product.last_error. Запуск:
  * фоновый поток PriceRefresher (стартует из app.py);
  * кнопка «Обновить цены» в аккаунте (refresh_products);
  * консоль: flask --app app refresh-prices
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from models import db, Product, PriceHistory, user_product
from scraping import ParseError, format_price, parse_product

log = logging.getLogger(__name__)

# Пауза между запросами к сайтам, чтобы не нагружать магазины и не получить бан
REQUEST_PAUSE_SEC = 2.0


@dataclass
class RefreshReport:
    updated: int = 0
    changed: list = field(default_factory=list)   # (title, старая цена, новая цена)
    failed: list = field(default_factory=list)    # (title, текст ошибки)


def refresh_product(product, now=None, parse=None):
    """Перепроверяет один товар. Возвращает (успех, изменилась_ли_цена, старая_цена).
    Коммит — на вызывающем. parse — для тестов; по умолчанию parse_product."""
    now = now or datetime.now()
    product.last_checked = now
    try:
        snapshot = (parse or parse_product)(product.source_url)
    except ParseError as err:
        product.last_error = str(err)
        return False, False, None

    previous = product.price_history[-1].price if product.price_history else None
    price = float(snapshot.price)

    product.title = snapshot.title
    product.price_new = format_price(snapshot.price, snapshot.currency)
    product.price_old = format_price(snapshot.price_old, snapshot.currency) if snapshot.price_old else ''
    product.image_url = snapshot.image_url or product.image_url
    product.last_error = None
    product.price_history.append(PriceHistory(price=price, recorded_at=now))
    return True, previous is not None and previous != price, previous


def refresh_products(products, pause=REQUEST_PAUSE_SEC, parse=None):
    """Перепроверяет товары по очереди, коммитя после каждого, и возвращает отчёт."""
    report = RefreshReport()
    for i, product in enumerate(products):
        if i and pause:
            time.sleep(pause)
        ok, changed, previous = refresh_product(product, parse=parse)
        db.session.commit()
        if ok:
            report.updated += 1
            if changed:
                report.changed.append((product.title, previous, product.price_history[-1].price))
        else:
            report.failed.append((product.title, product.last_error))
    return report


def due_products(max_age, now=None):
    """Отслеживаемые хотя бы одним пользователем товары, которые пора перепроверить."""
    threshold = (now or datetime.now()) - max_age
    return (Product.query
            .filter(Product.id.in_(db.select(user_product.c.product_id)))
            .filter(db.or_(Product.last_checked.is_(None), Product.last_checked < threshold))
            .order_by(Product.last_checked.is_not(None), Product.last_checked)
            .all())


class PriceRefresher(threading.Thread):
    """Фоновый поток: раз в poll_interval перепроверяет товары старше max_age."""

    def __init__(self, app, max_age=timedelta(hours=6), poll_interval=timedelta(minutes=10)):
        super().__init__(name='price-refresher', daemon=True)
        self.app = app
        self.max_age = max_age
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()

    def run(self):
        log.info('Перепроверка цен: каждые %s, товары старше %s', self.poll_interval, self.max_age)
        while not self._stop_event.is_set():
            try:
                with self.app.app_context():
                    products = due_products(self.max_age)
                    if products:
                        report = refresh_products(products)
                        log.info('Перепроверено %d, изменилась цена у %d, ошибок %d',
                                 report.updated, len(report.changed), len(report.failed))
            except Exception:  # поток не должен умирать из-за одной ошибки
                log.exception('Ошибка фоновой перепроверки цен')
            self._stop_event.wait(self.poll_interval.total_seconds())

    def stop(self):
        self._stop_event.set()
