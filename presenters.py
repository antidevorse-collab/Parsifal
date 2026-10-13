"""Подготовка данных для шаблонов: карточки товаров, сводка панели, данные графика."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from forecast import MAX_GAP_DAYS, PriceAnalysis, analyze_prices
from scraping import platform_of

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")


def ru_date(value: datetime) -> str:
    """12 октября 2026"""
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def greeting(now: datetime) -> str:
    hour = now.hour
    if 5 <= hour < 12:
        return "Доброе утро"
    if 12 <= hour < 18:
        return "Добрый день"
    if 18 <= hour < 23:
        return "Добрый вечер"
    return "Доброй ночи"


def price_changes(history):
    """Точки истории, где цена изменилась (плюс самая первая): повторные
    проверки с той же ценой в списке не нужны, они лишь удлиняют его."""
    changes = []
    for point in history:
        if not changes or point.price != changes[-1].price:
            changes.append(point)
    return changes


def chart_points(history):
    """Точки для графика: смены цены, края пропусков в наблюдениях и последняя проверка.
    gap=True — перед точкой был пропуск дольше MAX_GAP_DAYS: цена там неизвестна,
    график рисует этот отрезок пунктиром."""
    max_gap = timedelta(days=MAX_GAP_DAYS)
    points, prev = [], None

    def add(h, gap=False):
        points.append({"t": h.recorded_at.isoformat(timespec="minutes"), "p": h.price, "gap": gap})

    for h in history:
        gap = prev is not None and h.recorded_at - prev.recorded_at > max_gap
        if gap and points and points[-1]["t"] != prev.recorded_at.isoformat(timespec="minutes"):
            add(prev)                          # последняя известная точка перед пропуском
        if not points or gap or h.price != points[-1]["p"]:
            add(h, gap)
        prev = h
    if prev is not None and points[-1]["t"] != prev.recorded_at.isoformat(timespec="minutes"):
        add(prev)                              # линия тянется до последней проверки
    return points


@dataclass
class ProductCard:
    product: object          # models.Product
    analysis: PriceAnalysis
    changes: list            # точки смены цены, новые сверху
    checks: int

    @property
    def platform(self) -> str:
        return platform_of(self.product.source_url or "")

    @property
    def initials(self) -> str:
        """Заглушка вместо фото: первые буквы двух первых слов названия."""
        words = [w for w in self.product.title.split() if w[:1].isalnum()]
        return "".join(w[0] for w in words[:2]).upper() or "?"

    def chart(self) -> dict:
        f, s = self.analysis.forecast, self.analysis.stats
        forecast = None
        if f is not None:
            at = s.current_at + timedelta(days=f.horizon_days)
            forecast = {"t": at.isoformat(timespec="minutes"), "p": f.price, "low": f.low, "high": f.high}
        return {"id": self.product.id, "title": self.product.title,
                "points": chart_points(self.product.price_history), "forecast": forecast}


def product_card(product) -> ProductCard:
    history = product.price_history   # упорядочена по recorded_at
    return ProductCard(product=product,
                       analysis=analyze_prices([(h.recorded_at, h.price) for h in history]),
                       changes=list(reversed(price_changes(history))),
                       checks=len(history))


def dashboard_stats(cards, now: datetime) -> dict:
    """Сводка панели: сколько товаров, сколько было снижений за 30 дней, сколько ждут снижения."""
    since = now - timedelta(days=30)
    drops = 0
    for card in cards:
        changes = list(reversed(card.changes))           # от старых к новым
        drops += sum(1 for a, b in zip(changes, changes[1:])
                     if b.recorded_at >= since and b.price < a.price)
    return {"tracked": len(cards), "drops_30d": drops,
            "expected_drops": sum(1 for c in cards if c.analysis.verdict == "wait")}
