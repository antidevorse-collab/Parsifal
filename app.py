import logging
import os
import socket
from datetime import datetime, timedelta
from decimal import Decimal

import click
from flask import Flask, abort, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, login_required, current_user

from auth import auth as auth_bp, safe_next_url
from models import db, ensure_schema, User, Product, PriceHistory
from network import detect_egress_country
from presenters import dashboard_stats, greeting, product_card, ru_date
from scraping import (parse_product, parse_price, format_price, ParseError, SiteBlockedError,
                      UnsupportedSiteError, SUPPORTED_PLATFORMS)
from tracking import PriceRefresher, due_products, refresh_products

app = Flask(__name__)
app.secret_key = 'super-secret-key'

# Настройки БД
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'PARSIFAL_DATABASE_URL', f"sqlite:///{os.path.join(basedir, 'products.db')}")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Страна, из которой ожидаем выход в интернет; иная страна — признак VPN
app.config['EXPECTED_COUNTRY'] = os.environ.get('PARSIFAL_EXPECTED_COUNTRY', 'RU')
# Как часто перепроверять цены отслеживаемых товаров (фоновый поток)
app.config['REFRESH_INTERVAL'] = timedelta(hours=float(os.environ.get('PARSIFAL_REFRESH_HOURS', 6)))
app.config['REFRESH_ENABLED'] = os.environ.get('PARSIFAL_REFRESH_ENABLED', '1') == '1'
db.init_app(app)

with app.app_context():
    ensure_schema()

# Flask-Login
login_manager = LoginManager()
login_manager.login_view = 'auth.login'  # маршрут в blueprint auth
login_manager.login_message = 'Войдите, чтобы открыть эту страницу.'
login_manager.login_message_category = 'info'
login_manager.init_app(app)

# Blueprints
app.register_blueprint(auth_bp, url_prefix='/auth')

@app.template_filter('plural')
def plural(n, one, few, many):
    """Русское склонение: 1 проверка, 2 проверки, 5 проверок, 21 проверка."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


@app.template_filter('money')
def money(value):
    """Цена из истории (float) для показа: 1234.0 → «1 234 ₽». История хранится в рублях."""
    return format_price(Decimal(str(round(value, 2))))


app.add_template_filter(ru_date, 'ru_date')


@app.template_filter('percent')
def percent(share):
    """−0.083 → «−8,3%», 0.05 → «+5%»: знак всегда, запятая как в русской записи."""
    text = f"{abs(share) * 100:.1f}".rstrip('0').rstrip('.').replace('.', ',')
    return f"{'+' if share > 0 else '−' if share < 0 else ''}{text}%"


@app.context_processor
def layout_context():
    """Данные шапки: число отслеживаемых товаров для меню аккаунта."""
    tracked = len(current_user.products) if current_user.is_authenticated else 0
    return {'tracked_count': tracked,
            'supported_platforms': SUPPORTED_PLATFORMS,
            'refresh_hours': app.config['REFRESH_INTERVAL'].total_seconds() / 3600}


# Загрузка пользователя
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# Главная страница (парсинг)
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # dict.fromkeys — убираем дубли ссылок, сохраняя порядок
        urls = list(dict.fromkeys(u.strip() for u in request.form['url'].splitlines() if u.strip()))
        results = []
        blocked_hosts = []
        unsupported = []
        for url in urls:
            try:
                results.append(session_product(parse_product(url)))
            except UnsupportedSiteError as err:
                unsupported.append(err.platform)
            except SiteBlockedError as err:
                blocked_hosts.append(err.host)
            except ParseError as err:
                flash(str(err), 'danger')
        session['parsed_products'] = results

        if unsupported:
            flash(f"Пока не поддерживаются: {', '.join(sorted(set(unsupported)))} — эти площадки "
                  f"защищены от автоматических запросов. Поддерживаются: "
                  f"{', '.join(SUPPORTED_PLATFORMS)} и магазины со стандартной разметкой товара.",
                  'warning')
        if blocked_hosts:
            flash(blocked_sites_message(sorted(set(blocked_hosts))), 'warning')
        return redirect(url_for('index'))

    now = datetime.now()
    cards = [product_card(p) for p in current_user.products] if current_user.is_authenticated else []
    tracked_urls = {c.product.source_url for c in cards}
    return render_template('index.html', parsed_products=session_products(),
                           tracked_urls=tracked_urls, cards=cards,
                           stats=dashboard_stats(cards, now), charts=[c.chart() for c in cards],
                           greeting=greeting(now), today=ru_date(now))


def session_product(snapshot):
    """Снимок товара в виде, который хранится в сессии и выводится в шаблоне."""
    data = snapshot.to_dict()
    # Поля, которые сейчас хранятся в Product строками
    data['price_new'] = data['price_display']
    data['price_old'] = data['price_old_display']
    return data


def blocked_sites_message(hosts):
    """Объясняет отказ сайтов: VPN или защита от автоматических запросов."""
    sites = ', '.join(hosts)
    expected = app.config['EXPECTED_COUNTRY']
    country = detect_egress_country()

    if country is None:
        return (f"Сайты отклонили запрос: {sites}. Если включён VPN — отключите его или добавьте "
                f"эти сайты в исключения; иначе площадка защищена от автоматических запросов "
                f"и пока не поддерживается.")
    if country != expected:
        return (f"Сайты отклонили запрос: {sites}. Сервер выходит в интернет не из {expected} "
                f"(страна: {country}) — вероятно, включён VPN. Отключите его или добавьте эти "
                f"сайты в исключения VPN и повторите парсинг.")
    return (f"Сайты защищены от автоматических запросов и пока не поддерживаются: {sites}. "
            f"Сейчас поддерживаются: {', '.join(SUPPORTED_PLATFORMS)}.")


def session_products():
    """Распарсенные товары из сессии. Записи старого формата (без числовой
    цены 'price') отбрасываются — они остались в cookie от прежней версии."""
    return [p for p in session.get('parsed_products', []) if 'price' in p]


def find_parsed(source_url):
    """Распарсенный товар из сессии по ссылке (ссылка стабильна, индекс — нет)."""
    return next((p for p in session_products() if p['source_url'] == source_url), None)


def track_product(data):
    """Привязывает товар к пользователю; новый товар создаётся с первой точкой истории.
    Возвращает True, если товар добавлен в аккаунт впервые. Коммит — на вызывающем."""
    product = Product.query.filter_by(source_url=data['source_url']).first()
    if product is None:
        price = parse_price(data['price'])
        product = Product(
            title=data['title'],
            price_new=data['price_new'],
            price_old=data['price_old'],
            image_url=data['image_url'],
            source_url=data['source_url'],
            last_checked=datetime.now(),
        )
        product.price_history.append(PriceHistory(price=float(price), recorded_at=datetime.now()))
        db.session.add(product)

    if product in current_user.products:
        return False
    current_user.products.append(product)
    return True


# Убрать карточку из результатов парсинга (без перезагрузки)
@app.route('/remove_product', methods=['POST'])
def remove_product():
    source_url = request.form.get('source_url', '')
    session['parsed_products'] = [p for p in session_products() if p['source_url'] != source_url]
    return '', 204


# Добавить один товар
@app.route('/save_parsed_product', methods=['POST'])
@login_required
def save_parsed_product():
    data = find_parsed(request.form.get('source_url', ''))
    if data is None:
        flash('Товар не найден в результатах парсинга — распарсьте ссылку заново.', 'danger')
    elif track_product(data):
        db.session.commit()
        flash(f"«{data['title']}» добавлен в аккаунт", 'success')
    else:
        flash(f"«{data['title']}» уже отслеживается", 'info')
    return redirect(url_for('index'))


# Добавить все товары
@app.route('/save_all', methods=['POST'])
@login_required
def save_all():
    count = sum(track_product(p) for p in session_products())
    db.session.commit()
    flash(f'Добавлено новых товаров: {count}', 'success')
    return redirect(url_for('index'))


# Мои товары: карточки с текущей ценой, прогнозом и советом
@app.route('/account')
@login_required
def account():
    return render_template('account.html', cards=[product_card(p) for p in current_user.products])


# Страница товара: график, прогноз, статистика, история изменений
@app.route('/product/<int:id>')
@login_required
def product_detail(id):
    product = db.session.get(Product, id)
    if product is None or product not in current_user.products:
        abort(404)
    card = product_card(product)
    return render_template('product.html', card=card, chart=card.chart())


# Перепроверить цены товаров пользователя сейчас
@app.route('/refresh', methods=['POST'])
@login_required
def refresh():
    report = refresh_products(current_user.products)
    flash(f'Цены обновлены: {report.updated} из {report.updated + len(report.failed)}', 'success')
    for title, old, new in report.changed:
        flash(f'«{title}»: {format_price(Decimal(str(old)))} → {format_price(Decimal(str(new)))}', 'info')
    for title, error in report.failed:
        flash(f'«{title}»: не удалось обновить — {error}', 'warning')
    return redirect(safe_next_url(request.form.get('next')) or url_for('account'))

# Удаление товара
@app.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    product = db.session.get(Product, id)
    if product and product in current_user.products:
        current_user.products.remove(product)
        db.session.commit()
        flash('Товар удален из аккаунта', 'success')
    return redirect(url_for('account'))

# Удаление пользователя (только админ)
@app.route('/delete_user', methods=['POST'])
@login_required
def delete_user():
    if current_user.role != 'admin':
        flash("Доступ запрещён", "danger")
        return redirect(url_for('account'))

    user_id = request.form.get('user_id', type=int)
    user = db.session.get(User, user_id) if user_id else None
    if user and user.id != current_user.id:
        db.session.delete(user)
        db.session.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin_panel')
@login_required
def admin_panel():
    if current_user.role != 'admin':
        flash("Доступ запрещён", "danger")
        return redirect(url_for('account'))

    users = User.query.all()
    products = Product.query.all()
    return render_template('admin_panel.html', users=users, products=products)

def default_host():
    """Адрес для локального запуска: IPv6-loopback, если он доступен, иначе 127.0.0.1.

    Некоторые VPN-клиенты (замечено на AmneziaVPN) блокируют IPv4-loopback:
    сервер на 127.0.0.1 стартует, но браузер не может подключиться. Браузер
    по адресу http://localhost сам пробует ::1, поэтому IPv6 надёжнее.
    """
    if socket.has_ipv6:
        try:
            with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
                probe.bind(('::1', 0))
            return '::1'
        except OSError:
            pass
    return '127.0.0.1'


@app.cli.command('refresh-prices')
@click.option('--all', 'refresh_all', is_flag=True, help='Перепроверить все товары, а не только устаревшие.')
def refresh_prices_command(refresh_all):
    """Перепроверить цены отслеживаемых товаров: flask --app app refresh-prices"""
    products = due_products(timedelta(0) if refresh_all else app.config['REFRESH_INTERVAL'])
    click.echo(f'Товаров к проверке: {len(products)}')
    report = refresh_products(products)
    for title, old, new in report.changed:
        click.echo(f'  изменилась цена: {title}: {old:g} -> {new:g}')
    for title, error in report.failed:
        click.echo(f'  ошибка: {title}: {error}')
    click.echo(f'Обновлено {report.updated}, ошибок {len(report.failed)}')


def start_price_refresher(debug):
    """Запускает фоновую перепроверку цен. В debug-режиме Flask запускает два
    процесса (наблюдатель и рабочий с WERKZEUG_RUN_MAIN) — поток нужен только в рабочем."""
    if not app.config['REFRESH_ENABLED']:
        return
    if debug and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        return
    PriceRefresher(app, max_age=app.config['REFRESH_INTERVAL']).start()


# Запуск
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s: %(message)s')
    debug = True
    start_price_refresher(debug)
    host = os.environ.get('PARSIFAL_HOST') or default_host()
    port = int(os.environ.get('PARSIFAL_PORT', 5000))
    print(f" * Откройте в браузере: http://localhost:{port}")
    app.run(host=host, port=port, debug=debug)
