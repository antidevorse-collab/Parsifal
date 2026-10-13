"""Интеграционные тесты маршрутов парсинга и сохранения на временной БД."""
import atexit
import os
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)
os.environ["PARSIFAL_DATABASE_URL"] = f"sqlite:///{_db_path}"  # до импорта app

from werkzeug.security import generate_password_hash  # noqa: E402

import app as app_module  # noqa: E402
from app import app  # noqa: E402
from models import db, Product, PriceHistory, User  # noqa: E402
from scraping import ProductSnapshot, UnsupportedSiteError, SiteBlockedError  # noqa: E402


def snapshot(n, price="902"):
    return ProductSnapshot(title=f"Товар {n}", price=Decimal(price), platform="Свой Питомник",
                           source_url=f"https://voronezh.svoy-pitomnik.ru/item-{n}",
                           image_url=f"https://voronezh.svoy-pitomnik.ru/{n}.jpg")


def fake_parse(url):
    if "ozon" in url:
        raise UnsupportedSiteError(url, "Ozon")
    if "citilink" in url:
        raise SiteBlockedError(url, 429)
    return snapshot(url.rsplit("-", 1)[-1])


@atexit.register
def _remove_test_db():
    with app.app_context():
        db.engine.dispose()
    os.remove(_db_path)


class AppTestCase(unittest.TestCase):
    """База для тестов с приложением: чистая временная БД, пользователь u/p,
    parse_product в app подменён на fake_parse. Своих тестов не содержит."""

    def setUp(self):
        app.config.update(TESTING=True)
        with app.app_context():
            db.drop_all()
            db.create_all()
            db.session.add(User(username="u", password=generate_password_hash("p")))
            db.session.commit()
        self.client = app.test_client()
        patcher = mock.patch.object(app_module, "parse_product", side_effect=fake_parse)
        patcher.start()
        self.addCleanup(patcher.stop)

    def login(self):
        self.client.post("/auth/login", data={"username": "u", "password": "p"})

    def parse(self, *urls):
        return self.client.post("/", data={"url": "\n".join(urls)}, follow_redirects=True)

    def session_urls(self):
        with self.client.session_transaction() as s:
            return [p["source_url"] for p in s.get("parsed_products", [])]


class AppTest(AppTestCase):

    def test_parse_shows_cards_and_dedupes(self):
        a = "https://voronezh.svoy-pitomnik.ru/item-1"
        html = self.parse(a, a, "https://voronezh.svoy-pitomnik.ru/item-2").get_data(as_text=True)
        self.assertIn("Товар 1", html)
        self.assertIn("902 ₽", html)
        self.assertEqual(len(self.session_urls()), 2)

    def test_messages_for_unsupported_and_blocked(self):
        with mock.patch.object(app_module, "detect_egress_country", return_value="RU"):
            html = self.parse("https://www.ozon.ru/p/1", "https://www.citilink.ru/p/2").get_data(as_text=True)
        self.assertIn("Пока не поддерживаются: Ozon", html)
        self.assertIn("защищены от автоматических запросов", html)

        with mock.patch.object(app_module, "detect_egress_country", return_value="NL"):
            html = self.parse("https://www.citilink.ru/p/2").get_data(as_text=True)
        self.assertIn("вероятно, включён VPN", html)

    def test_remove_by_url_not_index(self):
        """Регрессия: после удаления первой карточки вторая кнопка удаляла третью."""
        urls = [f"https://voronezh.svoy-pitomnik.ru/item-{n}" for n in (1, 2, 3)]
        self.parse(*urls)
        self.client.post("/remove_product", data={"source_url": urls[0]})
        self.client.post("/remove_product", data={"source_url": urls[1]})
        self.assertEqual(self.session_urls(), [urls[2]])

    def test_save_one_uses_session_data_not_form(self):
        self.login()
        url = "https://voronezh.svoy-pitomnik.ru/item-1"
        self.parse(url)
        # Подменённая цена в форме игнорируется — данные берутся из сессии
        self.client.post("/save_parsed_product", data={"source_url": url, "price_new": "1 ₽"})
        self.client.post("/save_parsed_product", data={"source_url": url})  # повтор — без дубля
        with app.app_context():
            product = Product.query.filter_by(source_url=url).one()
            self.assertEqual(product.price_new, "902 ₽")
            self.assertEqual([h.price for h in product.price_history], [902.0])
            self.assertEqual(len(db.session.get(User, 1).products), 1)

    def test_save_all(self):
        self.login()
        self.parse(*[f"https://voronezh.svoy-pitomnik.ru/item-{n}" for n in (1, 2)])
        html = self.client.post("/save_all", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Добавлено новых товаров: 2", html)
        with app.app_context():
            self.assertEqual(PriceHistory.query.count(), 2)

    def test_stale_session_from_old_version_is_ignored(self):
        self.login()
        with self.client.session_transaction() as s:
            s["parsed_products"] = [{"title": "Старый", "price_new": "", "price_old": "",
                                     "image_url": "", "source_url": "https://x.example/1"}]
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.post("/save_all", follow_redirects=True).status_code, 200)
        with app.app_context():
            self.assertEqual(Product.query.count(), 0)


if __name__ == "__main__":
    unittest.main()
