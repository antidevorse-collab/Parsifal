"""Анализ истории цены: статистика, тренд, прогноз и совет «покупать или ждать».

История — ряд проверок (время, цена) с неравномерным шагом: старые точки могли
появляться раз в неделю, новые — каждые несколько часов. Поэтому:

  1. Ряд переводится на суточную сетку (цена на конец дня = последняя известная).
     Иначе периоды частых проверок весили бы больше редких.
  2. Через пропуск дольше MAX_GAP_DAYS цена не протягивается: о ней ничего не известно.
  3. Модель — случайное блуждание со сносом: прогноз = текущая цена + снос × горизонт.
     Цены ведут себя близко к случайному блужданию, и привязка к текущей цене
     не даёт прогнозу «вернуться» к давно ушедшему уровню после разовой смены цены.
  4. Снос — оценка Тейла–Сена (медиана наклонов всех пар точек): одна акция
     не разворачивает прогноз, в отличие от обычной линейной регрессии.
  5. Диапазон — из разброса суточных изменений, растёт как √горизонта.
  6. Горизонт не дальше длины наблюдений: по неделе истории месяц вперёд не прогнозируем.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import sqrt
from statistics import median, pstdev
from typing import Optional, Sequence, Tuple

# Прогноз строится по последним WINDOW_DAYS дням наблюдений
WINDOW_DAYS = 90
# Дольше этого без проверок — пропуск, цену через него не протягиваем
MAX_GAP_DAYS = 14
# Минимум суток с наблюдениями для прогноза
MIN_DAYS = 7
HORIZON_DAYS = 14
# Ожидаемое изменение меньше этой доли — цена стабильна
STABLE_SHARE = 0.01
# Изменение от этой доли — повод советовать подождать или покупать сейчас
NOTABLE_SHARE = 0.03
# Квантиль нормального распределения для 90% диапазона
Z_90 = 1.645

Point = Tuple[datetime, float]


@dataclass(frozen=True)
class PriceStats:
    current: float
    min: float
    min_at: datetime
    max: float
    max_at: datetime
    since: datetime          # первая проверка
    current_at: datetime     # последняя проверка
    first: float             # цена при первой проверке
    distinct: int            # сколько разных цен было

    @property
    def change_share(self) -> float:
        """Изменение цены с первой проверки, доля: −0.08 — подешевел на 8%."""
        return (self.current - self.first) / self.first


@dataclass(frozen=True)
class Forecast:
    current: float
    price: float             # ожидаемая цена через horizon_days
    low: float               # 90% диапазон
    high: float
    horizon_days: int
    based_on_days: int       # сколько суток истории использовано

    @property
    def change_share(self) -> float:
        return (self.price - self.current) / self.current

    @property
    def direction(self) -> str:
        if abs(self.change_share) < STABLE_SHARE:
            return "flat"
        return "up" if self.change_share > 0 else "down"


@dataclass(frozen=True)
class PriceAnalysis:
    stats: Optional[PriceStats]
    forecast: Optional[Forecast]
    days_observed: int       # суток с наблюдениями в окне прогноза

    @property
    def days_needed(self) -> int:
        """Сколько ещё суток наблюдений нужно до первого прогноза."""
        return max(0, MIN_DAYS - self.days_observed)

    @property
    def trend(self) -> str:
        if self.forecast is None:
            return "Недостаточно данных"
        f = self.forecast
        percent = f"{abs(f.change_share):.0%}"
        period = f"за {f.horizon_days} дн."
        return {"flat": "🔸 Цена стабильна",
                "up": f"📈 Цена растёт: ≈ +{percent} {period}",
                "down": f"📉 Цена снижается: ≈ −{percent} {period}"}[f.direction]

    @property
    def verdict(self) -> Optional[str]:
        """Вид совета: wait, buy, lowest, highest или None, если сказать нечего."""
        f, s = self.forecast, self.stats
        if f is not None and f.change_share <= -NOTABLE_SHARE:
            return "wait"
        if f is not None and f.change_share >= NOTABLE_SHARE:
            return "buy"
        if s is not None and s.distinct > 1:
            if s.current <= s.min:
                return "lowest"
            if s.current >= s.max:
                return "highest"
        return None

    @property
    def verdict_label(self) -> str:
        """Короткая подпись совета для бейджа карточки."""
        return VERDICT_LABELS.get(self.verdict, "Наблюдаем")

    @property
    def advice(self) -> Optional[str]:
        """Совет покупателю развёрнуто или None, если сказать нечего."""
        if self.verdict == "highest":
            cheaper = f"{self.stats.max - self.stats.min:,.0f}".replace(",", " ")
            return f"Сейчас цена на максимуме — раньше было дешевле на {cheaper} ₽."
        return ADVICE_TEXTS.get(self.verdict)


VERDICT_LABELS = {"wait": "Лучше подождать", "buy": "Купить сейчас",
                  "lowest": "Лучшая цена", "highest": "Цена на максимуме"}
ADVICE_TEXTS = {"wait": "Цена снижается — если покупка не срочная, можно подождать.",
                "buy": "Цена растёт — выгоднее купить сейчас.",
                "lowest": "Сейчас самая низкая цена за всё время наблюдений."}


def price_stats(points: Sequence[Point]) -> Optional[PriceStats]:
    if not points:
        return None
    points = sorted(points)
    # При равных ценах — самая ранняя дата минимума/максимума
    low = min(points, key=lambda p: p[1])
    high = max(points, key=lambda p: p[1])
    return PriceStats(current=points[-1][1], min=low[1], min_at=low[0], max=high[1],
                      max_at=high[0], since=points[0][0], current_at=points[-1][0],
                      first=points[0][1], distinct=len({p for _, p in points}))


def daily_series(points: Sequence[Point], window_days=WINDOW_DAYS,
                 max_gap_days=MAX_GAP_DAYS) -> list:
    """[(день, цена)] — цена на конец каждого дня последних window_days дней.
    Дни, когда последняя проверка была больше max_gap_days назад, пропускаются."""
    if not points:
        return []
    points = sorted(points)
    last_day = points[-1][0].date()
    day = max(points[0][0].date(), last_day - timedelta(days=window_days - 1))

    series, i, known = [], 0, None   # known — (день проверки, цена)
    while day <= last_day:
        while i < len(points) and points[i][0].date() <= day:
            known = (points[i][0].date(), points[i][1])
            i += 1
        if known is not None and (day - known[0]).days <= max_gap_days:
            series.append((day, known[1]))
        day += timedelta(days=1)
    return series


def theil_sen_slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Медиана наклонов всех пар точек — устойчивая к выбросам оценка тренда."""
    slopes = [(ys[j] - ys[i]) / (xs[j] - xs[i])
              for i in range(len(xs)) for j in range(i + 1, len(xs)) if xs[j] != xs[i]]
    return median(slopes) if slopes else 0.0


def forecast_price(points: Sequence[Point], horizon_days=HORIZON_DAYS) -> Optional[Forecast]:
    """Прогноз цены через horizon_days (не дальше длины истории) или None."""
    series = daily_series(points)
    if len(series) < MIN_DAYS:
        return None

    first_day: date = series[0][0]
    xs = [(d - first_day).days for d, _ in series]
    ys = [p for _, p in series]
    span = xs[-1]
    horizon = min(horizon_days, span)

    drift = theil_sen_slope(xs, ys)
    # Суточные изменения только между соседними днями — не через пропуски
    changes = [ys[k] - ys[k - 1] for k in range(1, len(xs)) if xs[k] - xs[k - 1] == 1]
    spread = Z_90 * (pstdev(changes) if len(changes) > 1 else 0.0) * sqrt(horizon)

    current = ys[-1]
    expected = max(current + drift * horizon, 0.0)
    return Forecast(current=current, price=round(expected),
                    low=round(max(expected - spread, 0.0)), high=round(expected + spread),
                    horizon_days=horizon, based_on_days=len(series))


def analyze_prices(points: Sequence[Point]) -> PriceAnalysis:
    """points — [(время проверки, цена)] в любом порядке."""
    return PriceAnalysis(stats=price_stats(points), forecast=forecast_price(points),
                         days_observed=len(daily_series(points)))
