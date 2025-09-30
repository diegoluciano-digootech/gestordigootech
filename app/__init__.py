# app/__init__.py

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager

db = SQLAlchemy()
bcrypt = Bcrypt()
gerenciador_login = LoginManager()

def criar_app():
    """Função que cria e configura a aplicação Flask."""
    app = Flask(__name__)
    
    app.config['SECRET_KEY'] = 'uma-chave-secreta-muito-dificil-de-adivinhar'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///../database.db'

    db.init_app(app)
    bcrypt.init_app(app)
    gerenciador_login.init_app(app)
    
    gerenciador_login.login_view = 'login.exibir_pagina_login'
    gerenciador_login.login_message = 'Por favor, faça o login para acessar esta página.'
    gerenciador_login.login_message_category = 'warning'

    from .modelos import Usuario

    # Importa e registra o blueprint de login
    from .blueprints.login.rotas import login as login_bp
    app.register_blueprint(login_bp, url_prefix='/')

    # --- LINHAS ADICIONADAS ---
    # Importa e registra o novo blueprint de clientes
    from .blueprints.clientes.rotas import clientes as clientes_bp
    app.register_blueprint(clientes_bp)
    # --------------------------

    from app.blueprints.fornecedores.rotas import fornecedores
    app.register_blueprint(fornecedores)

    return app