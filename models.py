from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy import inspect, text

db = SQLAlchemy()

# Промежуточная таблица
user_product = db.Table('user_product',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('product_id', db.Integer, db.ForeignKey('products.id'), primary_key=True)
)

class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='user')

    # Связь с продуктами через промежуточную таблицу
    products = db.relationship('Product', secondary=user_product, back_populates='users')

class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    price_new = db.Column(db.String(50))
    price_old = db.Column(db.String(50))
    image_url = db.Column(db.Text)
    source_url = db.Column(db.Text)
    # Время последней попытки перепроверки (успешной или нет)
    last_checked = db.Column(db.DateTime)
    # Текст ошибки последней перепроверки; None — последняя проверка успешна
    last_error = db.Column(db.Text)

    # Пользователи, которые отслеживают этот товар
    users = db.relationship('User', secondary=user_product, back_populates='products')

    # История цен, от старых точек к новым
    price_history = db.relationship('PriceHistory', backref='product', lazy=True,
                                    order_by='PriceHistory.recorded_at',
                                    cascade='all, delete-orphan')

class PriceHistory(db.Model):
    __tablename__ = 'price_history'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    price = db.Column(db.Float, nullable=False)
    recorded_at = db.Column(db.DateTime, server_default=db.func.now())


# Колонки, добавленные после первой версии схемы: (таблица, колонка, SQL-тип).
# create_all() не меняет существующие таблицы, поэтому досоздаём их сами.
_ADDED_COLUMNS = (
    ('products', 'last_error', 'TEXT'),
)


def ensure_schema():
    """Создаёт таблицы и добавляет недостающие колонки в существующую БД."""
    db.create_all()
    inspector = inspect(db.engine)
    with db.engine.begin() as conn:
        for table, column, sql_type in _ADDED_COLUMNS:
            existing = {c['name'] for c in inspector.get_columns(table)}
            if column not in existing:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {sql_type}'))


# Утилиты
def get_user_by_username(username):
    return User.query.filter_by(username=username).first()

def create_user(username, password):
    if get_user_by_username(username):
        return False
    new_user = User(username=username, password=password, role='user')
    db.session.add(new_user)
    db.session.commit()
    return True
