# app/modelos.py

from datetime import datetime, timezone
from . import db, gerenciador_login
from flask_login import UserMixin
from datetime import datetime, timezone

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
    nome = db.Column(db.String(120), nullable=False)  # OBRIGATÓRIO
    documento = db.Column(db.String(20), unique=True, nullable=False) # OBRIGATÓRIO
    
    # NOVO: Atributo real para armazenar o valor da IE (privado)
    _inscricao_estadual = db.Column('inscricao_estadual', db.String(20), nullable=False, default='ISENTO') 
    
    endereco = db.Column(db.String(200), nullable=False) # OBRIGATÓRIO
    numero = db.Column(db.String(20), nullable=False)    # OBRIGATÓRIO
    cidade = db.Column(db.String(100), nullable=False)   # OBRIGATÓRIO
    uf = db.Column(db.String(2), nullable=False)         # OBRIGATÓRIO
    cep = db.Column(db.String(10), nullable=False)       # OBRIGATÓRIO
    
    # data_cadastro já estava correto como obrigatório
    data_cadastro = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    
    contatos = db.relationship('Contato', backref='cliente', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"Cliente('{self.nome}', '{self.documento}')"

    # --- CORREÇÃO DA INSCRIÇÃO ESTADUAL (IE) ---

    @property
    def ie(self):
        """Getter: Retorna o valor real armazenado no atributo privado."""
        return self._inscricao_estadual

    @ie.setter
    def ie(self, ie_valor):
        """Setter: Padroniza e atribui ao atributo privado."""
        if ie_valor is not None:
            # 1. Converte para string, remove espaços, e converte para maiúsculas
            valor_limpo = str(ie_valor).strip().upper()
            
            # 2. Aplica a regra 'ISENTO' se o valor for vazio
            if not valor_limpo:
                self._inscricao_estadual = 'ISENTO'
            else:
                self._inscricao_estadual = valor_limpo # Atribui ao atributo privado
        else:
            self._inscricao_estadual = 'ISENTO'

class Contato(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    telefone = db.Column(db.String(20), nullable=True)

    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)

    def __repr__(self):
        return f"Contato('{self.nome}', '{self.cliente.nome}')"
    
# -----------------------------------------------------
# NOVOS MODELOS: FORNECEDOR E CONTATOFORNECEDOR
# -----------------------------------------------------

class Fornecedor(db.Model):
    __tablename__ = 'fornecedores'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    documento = db.Column(db.String(20), unique=True, nullable=False) # CNPJ/CPF
    ie = db.Column(db.String(20), default='ISENTO') # Inscrição Estadual
    endereco = db.Column(db.String(150))
    numero = db.Column(db.String(10))
    cidade = db.Column(db.String(50))
    uf = db.Column(db.String(2))
    cep = db.Column(db.String(10))

    # Relação com os contatos do fornecedor
    contatos_fornecedor = db.relationship('ContatoFornecedor', backref='fornecedor', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"Fornecedor('{self.nome}')"
    
    # Propriedades de tratamento de IE (opcional, mas bom manter)
    @property
    def ie(self):
        return self._ie

    @ie.setter
    def ie(self, value):
        if value and value.strip().upper() == 'ISENTO':
            self._ie = 'ISENTO'
        else:
            self._ie = value.strip().upper() if value else None


class ContatoFornecedor(db.Model):
    __tablename__ = 'contatos_fornecedor'
    id = db.Column(db.Integer, primary_key=True)
    fornecedor_id = db.Column(db.Integer, db.ForeignKey('fornecedores.id'), nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120))
    telefone = db.Column(db.String(20))

    def __repr__(self):
        return f"ContatoFornecedor('{self.nome}', '{self.telefone}')"