# Parsifal — карта проекта

Веб-приложение на Flask для отслеживания цен товаров в интернет-магазинах и прогноза цены
по истории. Пользователь вставляет ссылки → приложение парсит карточки → товары сохраняются
в аккаунт → фоновая перепроверка копит историю → статистика, тренд, прогноз, совет «покупать/ждать».

Язык интерфейса, комментариев и общения — русский. Пользователь просит качество «как сеньор».

## Запуск и тесты
- Запуск: `python app.py` (так же запускает PyCharm) → http://localhost:5000
  - Хост по умолчанию `::1`, а не 127.0.0.1: AmneziaVPN у пользователя блокирует IPv4-loopback
    (см. `default_host()` в app.py). Переопределение: `PARSIFAL_HOST`, `PARSIFAL_PORT`.
- Тесты: `python -X utf8 -m unittest discover -s tests -t .` (stdlib unittest, без pytest)
  - Тесты на HTML-фикстурах, сеть не нужна; БД временная через `PARSIFAL_DATABASE_URL`.
- Перепроверка цен вручную: `python -X utf8 -m flask --app app refresh-prices [--all]`.
  Фоново — поток `PriceRefresher` в `python app.py` (раз в 10 мин ищет товары старше
  `PARSIFAL_REFRESH_HOURS`=6; выключить: `PARSIFAL_REFRESH_ENABLED=0`).
  ⚠️ Пользователь обычно держит сервер запущенным в debug: правка .py → автоперезапуск →
  фоновая перепроверка реально ходит в сеть и пишет в `products.db`.
- Проверка площадок вживую: `check_platforms.bat` (двойной клик) → `check_platforms.py`.
  Отчёты пишутся в `reports/` — содержат страну выхода; IP не выводится намеренно.
- Git: https://github.com/antidevorse-collab/Parsifal, ветка `main`. Не коммитим: БД, `.idea/`, `reports/` (`.gitignore`).
- Shell: PowerShell 5.1 (Bash сломан). Python 3.13, пакеты в глобальном site-packages.
  Для вывода кириллицы из python: `python -X utf8`.

## Карта файлов
| Файл | Что там |
|---|---|
| `app.py` | Flask-приложение, конфиг, маршруты (кроме auth), `track_product`, фильтр `plural`, CLI `refresh-prices`, запуск фонового потока |
| `auth.py` | Blueprint `auth` (`/auth/login`, `/auth/register`, `/auth/logout`), `safe_next_url` (защита от open redirect) |
| `models.py` | `User`, `Product` (+`last_error`), `PriceHistory`, M2M `user_product`; `ensure_schema()` — create_all + ALTER для новых колонок (`_ADDED_COLUMNS`) |
| `tracking.py` | Перепроверка цен: `refresh_product`, `refresh_products` → `RefreshReport`, `due_products`, поток `PriceRefresher` |
| `presenters.py` | Данные для шаблонов: `ProductCard` (analysis, changes, platform, initials, `chart()`), `product_card`, `chart_points` (смены цены + края пропусков), `dashboard_stats`, `greeting`, `ru_date` |
| `forecast.py` | `analyze_prices(points) -> PriceAnalysis` (stats/forecast/trend/advice/days_needed). Суточная сетка, снос Тейла–Сена, прогноз от текущей цены, 90% диапазон, горизонт ≤ длины истории, минимум `MIN_DAYS`=7 суток |
| `network.py` | `detect_egress_country()` — код страны исходящего IP (для текста «вероятно, VPN») |
| `scraping/__init__.py` | `parse_product(url) -> ProductSnapshot`, реестр адаптеров, `SUPPORTED_PLATFORMS` |
| `scraping/base.py` | `ProductSnapshot`, ошибки, `fetch()` (детект блокировок), `parse_price`, `format_price`, базовый `Adapter` |
| `scraping/adapters/jsonld.py` | `JsonLdAdapter` (универсальный schema.org), `CitilinkAdapter`, `YandexMarketAdapter` |
| `scraping/adapters/svoy_pitomnik.py` | `SvoyPitomnikAdapter` — вёрстка OpenCart, селекторы только внутри `div.col-sm-7` |
| `scraping/adapters/unsupported.py` | `UNSUPPORTED_PLATFORMS` — Ozon, WB, Авито, DNS и др.; отказ без запроса |
| `check_platforms.py/.bat` | Диагностика доступности площадок (отдельно от приложения) |
| `templates/layout.html` | Базовый шаблон: шапка (навигация, кнопка аккаунта), выдвижная панель аккаунта, flash. Без Bootstrap |
| `templates/_macros.html` | `icon(name)` (SVG из макета), `product_card`, `product_visual`, `change_badge`, `verdict_icon`, `price_chart(charts)` |
| `templates/index.html` | «Обзор»: приветствие, форма ссылок (textarea, Enter — отправить), результаты парсинга, показатели, график, 3 карточки |
| `templates/account.html` | «Мои товары»: сетка карточек + «Обновить цены» |
| `templates/product.html` | Страница товара: показатели, график с прогнозом, совет, история изменений, удаление |
| `templates/admin_panel.html` | Таблицы пользователей и всех товаров (для admin) |
| `templates/login.html`, `register.html` | Формы входа/регистрации |
| `static/css/app.css` | Все стили (палитра макета Figma Make; исходник макета удалён), адаптив 1050/760px |
| `static/js/app.js` | Панель аккаунта, закрытие flash, autosize поля ссылок, «Убрать» карточку (`data-remove-parsed`), `data-confirm`, `data-busy` |
| `static/js/chart.js` | SVG-график без библиотек: ступенчатая линия, пропуски пунктиром, прогноз + 90% диапазон, период 7/30/90/всё, подсказка |
| `tests/test_scraping.py` | Адаптеры, `parse_price`, реестр, детект блокировок |
| `tests/test_app.py` | `AppTestCase` (база: временная БД, юзер u/p, фейковый парсер) + тесты маршрутов парсинга/сохранения |
| `tests/test_tracking.py` | Перепроверка, `due_products`, login/next, карточки аккаунта, страница товара (прогноз, 404 чужого), обзор, `/refresh` с `next` |
| `tests/test_forecast.py` | Суточная сетка, прогноз, выбросы, советы, статистика |
| `products.db` | Рабочая SQLite БД (в git не попадает, см. `.gitignore`; создаётся сама при запуске) |
| `requirements` | Зависимости (файл без расширения .txt) |

## Маршруты (app.py)
| URL | Функция | Доступ |
|---|---|---|
| `GET/POST /` | `index` — «Обзор»: парсинг ссылок (результаты в `session['parsed_products']`), для вошедших — показатели, график, карточки | все |
| `POST /remove_product` | убрать карточку из сессии по `source_url` | все |
| `POST /save_parsed_product` | сохранить один товар (данные из сессии, не из формы) | login |
| `POST /save_all` | сохранить все из сессии | login |
| `GET /account` | сетка карточек товаров (одинаково для user и admin) | login |
| `GET /product/<id>` | страница товара (404, если товар не отслеживается пользователем) | login |
| `POST /refresh` | перепроверить цены товаров пользователя сейчас | login |
| `POST /delete/<id>` | отвязать товар от пользователя | login |
| `POST /delete_user` | удалить пользователя | admin |
| `GET /admin_panel` | админка | admin |

## Ключевые решения
- **Парсинг — через адаптеры.** Порядок выбора: неподдерживаемая площадка → отказ без запроса;
  адаптер по домену; иначе универсальный JSON-LD. Новая площадка = класс в `scraping/adapters/`
  + строка в `SITE_ADAPTERS` (`scraping/__init__.py`) + тест на фикстуре.
- **Ошибки парсинга** — иерархия `ParseError`: `SiteBlockedError` (антибот/VPN),
  `UnsupportedSiteError`, `NotAProductError`, `SiteUnavailableError`, `OutOfStockError` (JSON-LD без цены + availability OutOfStock — Ситилинк так отдаёт снятые товары). `str(err)` — текст для пользователя.
- **VPN-сообщение** показывается только после реального отказа сайта (`blocked_sites_message`):
  страна ≠ RU → «вероятно, VPN», RU → «площадка защищена». Постоянного баннера нет (ложные
  срабатывания при раздельном туннеле).
- **Идентичность товара — `source_url`** (не title, не индекс в списке).
- **История цен**: каждая успешная перепроверка добавляет точку (даже без изменения цены —
  это ряд наблюдений для тренда/прогноза). В UI показываются только точки изменения
  (`price_changes`). Неудача → `Product.last_error`, `last_checked` всё равно обновляется
  (не долбим сайт до следующего интервала). Перепроверяются только товары, которые кто-то отслеживает.
- **Схема БД**: миграций (Alembic) нет. Новая колонка = поле в модели + строка в `_ADDED_COLUMNS`.
- **Цена**: в снимке `Decimal`; `Product.price_new/price_old` пока строки («902 ₽»),
  `PriceHistory.price` — float. HTML разбирать из `response.content` (байты), не `.text` —
  иначе кракозябры у сайтов без charset в заголовке.

## Площадки (проверено 2026-10-12, российский IP без VPN)
- ✅ HTTP: Свой Питомник (`*.svoy-pitomnik.ru`), Ситилинк, Яндекс Маркет (JSON-LD).
- ❌ Антибот независимо от страны: Ozon 403, WB 498, Авито 439, DNS/Лемана ПРО 401.
- ⚠️ Нужен JS (Playwright): Мегамаркет, Lamoda, AliExpress, М.Видео.
- Под VPN Ситилинк (429) и Маркет (403) тоже блокируют.
- Живая проверка адаптеров без VPN (2026-10-12): Питомник ✅, Ситилинк ✅ (снятый товар → «Нет в наличии»),
  Маркет — нестабильно: часть запросов получает заглушку антибота (пустой ответ), часть проходит.

## Известные проблемы / план (по порядку)
1. ~~VPN-предупреждение~~, ~~адаптеры~~, ~~login_view~~, ~~накопление истории~~, ~~живая проверка~~, ~~прогноз~~ — сделано.
   Возможное развитие прогноза: учёт сезонности (нужна история > года).
2. ~~Визуальная часть~~ — редизайн по макету Figma сделан 2026-10-13 (шаблоны, CSS, график).
   Осталось: проверить вживую в браузере на десктопе и телефоне.
3. Прочее из досье: захардкоженный `secret_key` + `debug=True`, нет CSRF,
   нет способа назначить admin.
   (~~«₽ ₽» в admin_panel~~, ~~flash без категорий~~, ~~мёртвый product_id.py~~ — сделано.)
