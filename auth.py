from urllib.parse import urlparse

from flask import Blueprint, render_template, redirect, request, flash, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, logout_user, login_required
from models import get_user_by_username, create_user

auth = Blueprint('auth', __name__)


def safe_next_url(target):
    """Только относительный путь этого сайта: '/account' — да,
    'https://evil.example' и '//evil.example' — нет (защита от open redirect)."""
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith('/') or target.startswith('//'):
        return None
    return target


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = get_user_by_username(request.form['username'])
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect(safe_next_url(request.args.get('next')) or url_for('index'))
        flash('Неверный логин или пароль', 'danger')
    return render_template('login.html')

@auth.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        success = create_user(username, password)
        if not success:
            flash('Пользователь уже существует', 'danger')
        else:
            flash('Успешная регистрация. Войдите.', 'success')
            return redirect(url_for('auth.login'))
    return render_template('register.html')

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))
