# app/modelos.py

from datetime import datetime, timezone
from . import db, gerenciador_login
from flask_login import UserMixin

@gerenciador_login.user_loader
def carregar_usuario(id_usuario):
    return Usuario.query.get(int(id_usuario))

class Usuario(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    nome_usuario = db.Column(db.String(150), unique=True, nullable=False)
    senha_hash = db.Column(db.String(60), nullable=False)

    def __repr__(self):
        return f"Usuario('{self.nome_usuario}')"

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Identificação
    nome = db.Column(db.String(120), nullable=False)
    documento = db.Column(db.String(20), unique=True, nullable=True)
    # --- CAMPO ADICIONADO ---
    inscricao_estadual = db.Column(db.String(20), nullable=True)
    # ------------------------
    # Endereço
    endereco = db.Column(db.String(200), nullable=True)
    numero = db.Column(db.String(20), nullable=True)
    cidade = db.Column(db.String(100), nullable=True)
    uf = db.Column(db.String(2), nullable=True)
    cep = db.Column(db.String(10), nullable=True)
    # Controle
    data_cadastro = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    
    contatos = db.relationship('Contato', backref='cliente', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"Cliente('{self.nome}', '{self.documento}')"

# --- NOVA CLASSE/TABELA CRIADA ---
class Contato(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    telefone = db.Column(db.String(20), nullable=True)
    
    # --- CHAVE ESTRANGEIRA ---
    # Esta coluna conecta cada contato a um cliente específico.
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)

    def __repr__(self):
        return f"Contato('{self.nome}', '{self.cliente.nome}')"