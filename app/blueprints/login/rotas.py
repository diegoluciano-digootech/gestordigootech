# app/blueprints/login/rotas.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, login_required, logout_user
from app import db, bcrypt
from app.modelos import Usuario

login = Blueprint('login', __name__)

@login.route('/', methods=['GET', 'POST'])
def exibir_pagina_login():
    if request.method == 'POST':
        nome_usuario_form = request.form.get('username')
        senha_form = request.form.get('password')
        usuario_db = Usuario.query.filter_by(nome_usuario=nome_usuario_form).first()

        if usuario_db and bcrypt.check_password_hash(usuario_db.senha_hash, senha_form):
            login_user(usuario_db)
            return redirect(url_for('login.dashboard')) # Redireciona para o dashboard
        else:
            flash('Login falhou. Verifique seu usuário e senha.', 'danger')
            return redirect(url_for('login.exibir_pagina_login'))

    return render_template('login/login.html')


# Por enquanto, vamos colocar a rota do dashboard aqui para manter simples
@login.route('/dashboard')
@login_required # Esta linha protege a rota!
def dashboard():
    return render_template('dashboard.html')


@login.route('/logout')
@login_required # Protege a rota de logout também
def logout():
    logout_user()
    flash('Você saiu do sistema.', 'info')
    return redirect(url_for('login.exibir_pagina_login'))