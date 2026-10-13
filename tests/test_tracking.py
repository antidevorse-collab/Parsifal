"""Тесты перепроверки цен, авторизации и страницы аккаунта."""
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest import mock

from tests.test_app import AppTestCase, snapshot  # общая временная БД и фикстуры
from app import app
from auth import safe_next_url
from models import db, Product, PriceHistory, User
from scraping import SiteBlockedError
from tracking import due_products, refresh_product, refresh_products

T0 = datetime(2026, 10, 1, 12, 0)


def hours(n):
    return T0 + timedelta(hours=n)


class SafeNextTest(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(safe_next_url("/account"), "/account")
        for bad in ("https://evil.example/", "//evil.example", "javascript:alert(1)", "", None):
            with self.subTest(bad=bad):
                self.assertIsNone(safe_next_url(bad))


class TrackingTest(AppTestCase):
    def add_product(self, n=1, tracked=True, last_checked=None, prices=(902,), step_hours=1):
        product = Product(title=f"Товар {n}", price_new=f"{prices[-1]} ₽", price_old="",
                          image_url="", source_url=f"https://voronezh.svoy-pitomnik.ru/item-{n}",
                          last_checked=last_checked)
        for i, price in enumerate(prices):
            product.price_history.append(PriceHistory(price=price, recorded_at=hours(i * step_hours)))
        db.session.add(product)
        if tracked:
            user = db.session.get(User, 1)  # держим ссылку: иначе объект соберёт GC посреди append
            user.products.append(product)
        db.session.commit()
        return product

    def test_refresh_appends_point_and_detects_change(self):
        with app.app_context():
            product = self.add_product(prices=(902,))
            ok, changed, previous = refresh_product(
                product, now=hours(5), parse=lambda url: snapshot(1, price="850"))
            db.session.commit()
            self.assertEqual((ok, changed, previous), (True, True, 902))
            self.assertEqual([h.price for h in product.price_history], [902, 850])
            self.assertEqual(product.price_new, "850 ₽")
            self.assertEqual(product.last_checked, hours(5))
            self.assertIsNone(product.last_error)

    def test_refresh_failure_keeps_history_and_stores_error(self):
        def blocked(url):
            raise SiteBlockedError(url, 429)
        with app.app_context():
            product = self.add_product()
            report = refresh_products([product], pause=0, parse=blocked)
            self.assertEqual(report.updated, 0)
            self.assertEqual(len(report.failed), 1)
            self.assertIn("HTTP 429", product.last_error)
            self.assertEqual(len(product.price_history), 1)

    def test_due_products(self):
        now = datetime.now()
        with app.app_context():
            stale = self.add_product(1, last_checked=now - timedelta(hours=7))
            self.add_product(2, last_checked=now - timedelta(hours=1))      # свежий
            never = self.add_product(3, last_checked=None)
            self.add_product(4, tracked=False, last_checked=None)          # никто не отслеживает
            due = due_products(timedelta(hours=6), now=now)
            self.assertEqual([p.id for p in due], [never.id, stale.id])

    def test_guest_redirected_to_login_with_next(self):
        """Регрессия: login_view='login' давал 500 (BuildError) вместо редиректа."""
        response = self.client.get("/account")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login?next=%2Faccount", response.headers["Location"])
        response = self.client.post("/auth/login?next=/account",
                                    data={"username": "u", "password": "p"})
        self.assertTrue(response.headers["Location"].endswith("/account"))

    def page(self, url):
        """HTML страницы с нормализованными пробелами — удобно искать фразы."""
        return " ".join(self.client.get(url).get_data(as_text=True).split())

    def test_account_card_product_page_and_refresh(self):
        self.login()
        with app.app_context():
            pid = self.add_product(prices=(1000, 1000, 950, 900), step_hours=24).id
        html = self.page("/account")
        self.assertIn("4 проверки", html)
        self.assertIn("Добавлен по цене 1 000 ₽", html)
        self.assertIn("−10%", html)                       # с первой проверки
        self.assertIn("Лучшая цена", html)
        self.assertIn(f"/product/{pid}", html)

        html = self.page(f"/product/{pid}")
        self.assertIn("Изменения цены", html)
        self.assertEqual(html.count("<time "), 3)         # 1000 → 950 → 900, повтор схлопнут
        self.assertIn("3 дня наблюдений", html)           # 4 дня из 7 до прогноза
        self.assertIn("Минимум</span> <strong class=\"stat-value\">900 ₽", html)
        self.assertIn("самая низкая цена", html)
        self.assertIn('"points": [', html)                # данные графика

        with mock.patch("tracking.parse_product", return_value=snapshot(1, price="880")), \
                mock.patch("tracking.REQUEST_PAUSE_SEC", 0):
            response = self.client.post("/refresh", data={"next": f"/product/{pid}"})
            self.assertTrue(response.headers["Location"].endswith(f"/product/{pid}"))
            html = self.client.get(response.headers["Location"]).get_data(as_text=True)
        self.assertIn("Цены обновлены: 1 из 1", html)
        self.assertIn("900 ₽ → 880 ₽", html)

    def test_product_page_shows_forecast(self):
        self.login()
        with app.app_context():
            pid = self.add_product(prices=range(1200, 1000, -10), step_hours=24).id   # −10 ₽/день, 20 дней
        html = self.page(f"/product/{pid}")
        self.assertIn("Прогноз через 14 дней</span> <strong class=\"stat-value\">≈ 870 ₽", html)
        self.assertIn("за 20 дней", html)
        self.assertIn("Цена снижается", html)
        self.assertIn("можно подождать", html)
        self.assertIn("Лучше подождать", self.page("/account"))

    def test_product_page_only_for_own_products(self):
        self.login()
        with app.app_context():
            pid = self.add_product(tracked=False).id
        self.assertEqual(self.client.get(f"/product/{pid}").status_code, 404)
        self.assertEqual(self.client.get("/product/999").status_code, 404)

    def test_dashboard_stats_and_chart(self):
        self.login()
        with app.app_context():
            self.add_product(prices=(1000, 950, 900), step_hours=24)
        html = self.page("/")
        self.assertIn("Снижений цены</span> <strong class=\"stat-value\">2", html)
        self.assertIn("data-price-chart", html)
        self.assertIn("Товар 1", html)

    def test_guest_dashboard(self):
        html = self.page("/")
        self.assertIn("Войти", html)
        self.assertNotIn("data-price-chart", html)

    def test_admin_account_shows_own_products(self):
        """Регрессия: админ на /account получал админ-панель без списка товаров."""
        with app.app_context():
            db.session.get(User, 1).role = "admin"
            db.session.commit()
            self.add_product()
        self.login()
        html = self.client.get("/account").get_data(as_text=True)
        self.assertIn("Товар 1", html)


if __name__ == "__main__":
    unittest.main()
