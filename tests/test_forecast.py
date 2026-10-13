"""Тесты прогноза цены: суточная сетка, снос, диапазон, советы."""
import unittest
from datetime import datetime, timedelta

from forecast import (MIN_DAYS, analyze_prices, daily_series, forecast_price, price_stats,
                      theil_sen_slope)

T0 = datetime(2026, 9, 1, 12, 0)


def daily(prices, start=T0):
    """Одна проверка в день: [(время, цена)]."""
    return [(start + timedelta(days=i), float(p)) for i, p in enumerate(prices)]


class DailySeriesTest(unittest.TestCase):
    def test_frequent_checks_collapse_to_end_of_day(self):
        points = [(T0, 100.0), (T0 + timedelta(hours=6), 90.0), (T0 + timedelta(days=2), 80.0)]
        self.assertEqual([p for _, p in daily_series(points)], [90.0, 90.0, 80.0])

    def test_long_gap_is_not_filled(self):
        """Цена за полтора года без проверок неизвестна — не протягиваем её."""
        points = [(T0, 100.0), (T0 + timedelta(days=500), 120.0)]
        self.assertEqual(len(daily_series(points)), 1)


class ForecastTest(unittest.TestCase):
    def test_not_enough_days(self):
        self.assertIsNone(forecast_price(daily([100] * (MIN_DAYS - 1))))
        # Много проверок за один день — всё равно один день наблюдений
        many = [(T0 + timedelta(minutes=30 * k), 100.0) for k in range(20)]   # 12:00–21:30
        analysis = analyze_prices(many)
        self.assertIsNone(analysis.forecast)
        self.assertEqual(analysis.days_needed, MIN_DAYS - 1)
        self.assertEqual(analysis.trend, "Недостаточно данных")

    def test_flat_price(self):
        f = forecast_price(daily([500] * 10))
        self.assertEqual((f.price, f.low, f.high, f.direction), (500, 500, 500, "flat"))

    def test_linear_decline_continues(self):
        f = forecast_price(daily(range(1000, 900, -5)))   # −5 ₽/день, 20 дней
        self.assertEqual(f.horizon_days, 14)
        self.assertEqual(f.price, 905 - 5 * 14)
        self.assertEqual(f.direction, "down")

    def test_horizon_not_longer_than_history(self):
        f = forecast_price(daily(range(100, 110)))         # 10 дней → горизонт 9
        self.assertEqual(f.horizon_days, 9)

    def test_one_time_drop_is_not_a_trend(self):
        """Разовое снижение: прогноз от новой цены, без продолжения падения."""
        f = forecast_price(daily([1000] * 30 + [900] * 10))
        self.assertEqual(f.price, 900)
        self.assertEqual(f.direction, "flat")
        self.assertLess(f.low, 900)      # но диапазон учитывает, что цена умеет прыгать
        self.assertGreater(f.high, 900)

    def test_outlier_does_not_turn_trend(self):
        prices = list(range(100, 130))
        prices[15] = 10                                    # однодневная распродажа
        self.assertAlmostEqual(theil_sen_slope(range(30), prices), 1.0)


class AdviceTest(unittest.TestCase):
    def test_rising_buy_now(self):
        a = analyze_prices(daily(range(1000, 1200, 10)))
        self.assertIn("растёт", a.trend)
        self.assertIn("купить сейчас", a.advice)

    def test_falling_wait(self):
        a = analyze_prices(daily(range(1200, 1000, -10)))
        self.assertIn("снижается", a.trend)
        self.assertIn("подождать", a.advice)

    def test_lowest_and_highest(self):
        self.assertIn("самая низкая", analyze_prices(daily([1000, 950])).advice)
        self.assertIn("дешевле на 50 ₽", analyze_prices(daily([950, 1000])).advice)
        self.assertIsNone(analyze_prices(daily([1000, 1000])).advice)

    def test_stats(self):
        s = price_stats(daily([900, 800, 1000, 800, 950]))
        self.assertEqual((s.min, s.max, s.current, s.distinct), (800, 1000, 950, 4))
        self.assertEqual(s.min_at, T0 + timedelta(days=1))   # первый раз, когда была минимальной


if __name__ == "__main__":
    unittest.main()
