# ==============================================================================
# 1. IMPORTAÇÕES DE BIBLIOTECAS
# ==============================================================================
import os
import io
import base64
import logging
import datetime
import pathlib
from flask import Flask, Response, jsonify, redirect, render_template, request, send_from_directory, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin, LoginManager, login_user, logout_user, login_required, current_user
from weasyprint import HTML
import pandas as pd
from validate_docbr import CPF, CNPJ
import requests
from dateutil.relativedelta import relativedelta
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, extract, or_, case, text, desc
from sqlalchemy.exc import IntegrityError, OperationalError

# --- Configuração Inicial ---
app = Flask(__name__)
app.secret_key = 'uma-chave-secreta-muito-segura'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
db = SQLAlchemy(app)

# --- CONFIGURAÇÃO DO FLASK-LOGIN ---
# ... (código existente sem alterações) ...
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, faça o login para acessar esta página."
login_manager.login_message_category = "info"

# --- Modelos do Banco de Dados ---
faturamento_os = db.Table('faturamento_os',
    db.Column('faturamento_id', db.Integer, db.ForeignKey('faturamento.id'), primary_key=True),
    db.Column('ordem_servico_id', db.Integer, db.ForeignKey('ordem_servico.id'), primary_key=True)
)

class Faturamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_emissao = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    # CORREÇÃO: Readicionando campos para alinhar com o banco de dados
    data_vencimento = db.Column(db.Date, nullable=False)
    tipo_pagamento = db.Column(db.String(20), nullable=False)
    chave_pix = db.Column(db.String(100), nullable=True) # Pode ser nulo
    
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    ordens = db.relationship('OrdemServico', secondary=faturamento_os, backref='faturamento', lazy='dynamic')
    cliente = db.relationship('Cliente')
    pagamentos = db.relationship('Pagamento', backref='faturamento', lazy=True, cascade="all, delete-orphan")

    @property
    def valor_total_faturado(self):
        return sum(os.valor_total for os in self.ordens.all())
    
class Pagamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    faturamento_id = db.Column(db.Integer, db.ForeignKey('faturamento.id'), nullable=False)
    tipo_pagamento = db.Column(db.String(20), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    data_vencimento = db.Column(db.Date, nullable=False)
    chave_pix = db.Column(db.String(100), nullable=True)
    numero_parcelas = db.Column(db.Integer, default=1)
    # ADICIONE ESTA LINHA
    status = db.Column(db.String(20), default='Pendente') # Pendente ou Recebido

#(Restante das classes Cliente, OrdemServico, Peca, User sem alterações)
class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo_pessoa = db.Column(db.String(10), nullable=False, default='FISICA')
    nome = db.Column(db.String(100), unique=True)
    cpf = db.Column(db.String(14), unique=True)
    razao_social = db.Column(db.String(150), unique=True)
    cnpj = db.Column(db.String(18), unique=True)
    inscricao_estadual = db.Column(db.String(20))
    email = db.Column(db.String(100))
    telefone = db.Column(db.String(11))
    cep = db.Column(db.String(9))
    rua = db.Column(db.String(150))
    numero = db.Column(db.String(20))
    bairro = db.Column(db.String(100))
    cidade = db.Column(db.String(100))
    uf = db.Column(db.String(2))
    ordens = db.relationship('OrdemServico', backref='cliente', lazy=True)

    @property
    def nome_exibicao(self): return self.nome if self.tipo_pessoa == 'FISICA' else self.razao_social
    @property
    def documento_exibicao(self):
        doc = self.cpf if self.tipo_pessoa == 'FISICA' else self.cnpj
        if not doc: return ""
        if self.tipo_pessoa == 'FISICA' and len(doc) == 11: return f"{doc[:3]}.{doc[3:6]}.{doc[6:9]}-{doc[9:]}"
        if self.tipo_pessoa == 'JURIDICA' and len(doc) == 14: return f"{doc[:2]}.{doc[2:5]}.{doc[5:8]}/{doc[8:12]}-{doc[12:]}"
        return doc
    @property
    def telefone_formatado(self):
        if not self.telefone: return ""
        n = len(self.telefone)
        if n == 11: return f"({self.telefone[:2]}) {self.telefone[2:7]}-{self.telefone[7:]}"
        if n == 10: return f"({self.telefone[:2]}) {self.telefone[2:6]}-{self.telefone[6:]}"
        return self.telefone
    def __repr__(self): return f'<Cliente {self.nome_exibicao}>'

class OrdemServico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    problema = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='Aberta')
    data_criacao = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    data_fechamento = db.Column(db.DateTime, nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    valor_servicos = db.Column(db.Float, default=0.0)
    pecas = db.relationship('Peca', backref='ordem_servico', lazy=True, cascade="all, delete-orphan")
    @property
    def valor_pecas(self): return sum(p.valor_total for p in self.pecas)
    @property
    def valor_total(self): return self.valor_servicos + self.valor_pecas
    def __repr__(self): return f'<O.S. {self.id} - Cliente {self.cliente.nome}>'

class Peca(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False, default=1)
    valor_unitario = db.Column(db.Float, nullable=False, default=0.0)
    ordem_servico_id = db.Column(db.Integer, db.ForeignKey('ordem_servico.id'), nullable=False)
    @property
    def valor_total(self): return self.quantidade * self.valor_unitario
    def __repr__(self): return f'<Peça {self.descricao}>'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)
    def __repr__(self): return f'<User {self.username}>'

class ContaPagar(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200), nullable=False)
    fornecedor_id = db.Column(db.Integer, db.ForeignKey('fornecedor.id'), nullable=True)
    valor = db.Column(db.Float, nullable=False)
    data_emissao = db.Column(db.Date, nullable=False, default=datetime.date.today)
    data_vencimento = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='Pendente') # Pendente ou Pago
    fornecedor = db.relationship('Fornecedor')

    def __repr__(self):
        return f'<Conta a Pagar {self.id} - {self.descricao}>'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

class Fornecedor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    razao_social = db.Column(db.String(150), nullable=False, unique=True)
    nome_fantasia = db.Column(db.String(150))
    cnpj = db.Column(db.String(18), unique=True)
    telefone = db.Column(db.String(15))
    email = db.Column(db.String(100))
    cep = db.Column(db.String(9))
    rua = db.Column(db.String(150))
    numero = db.Column(db.String(20))
    bairro = db.Column(db.String(100))
    cidade = db.Column(db.String(100))
    uf = db.Column(db.String(2))

    def __repr__(self):
        return f'<Fornecedor {self.razao_social}>'
    
class ContaReceber(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=True)
    valor = db.Column(db.Float, nullable=False)
    data_emissao = db.Column(db.Date, nullable=False, default=datetime.date.today)
    data_vencimento = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='Pendente') # Status pode ser 'Pendente' ou 'Recebido'
    cliente = db.relationship('Cliente')

    def __repr__(self):
        return f'<Conta a Receber {self.id} - {self.descricao}>'
    
class Produto(db.Model):
    __tablename__ = 'produto'
    __table_args__ = {'extend_existing': True}
    
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200), nullable=False, unique=True)
    # NOVOS CAMPOS ADICIONADOS
    sku = db.Column(db.String(50), unique=True)
    ncm = db.Column(db.String(20))
    cest = db.Column(db.String(20))
    origem = db.Column(db.String(50))
    unidade_medida = db.Column(db.String(10))
    
    valor_custo = db.Column(db.Float, default=0.0)
    margem_lucro = db.Column(db.Float, default=0.0)
    valor_venda = db.Column(db.Float, default=0.0)
    quantidade_estoque = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<Produto {self.descricao}>'
    
# Modelo para o cabeçalho da Entrada de Estoque (Nota Fiscal, etc.)
class EntradaEstoque(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_entrada = db.Column(db.Date, nullable=False, default=datetime.date.today)
    fornecedor_id = db.Column(db.Integer, db.ForeignKey('fornecedor.id'), nullable=True)
    observacao = db.Column(db.String(300))
    fornecedor = db.relationship('Fornecedor')
    itens = db.relationship('EntradaEstoqueItem', backref='entrada', cascade="all, delete-orphan")

# Modelo para cada item dentro de uma Entrada de Estoque
class EntradaEstoqueItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entrada_id = db.Column(db.Integer, db.ForeignKey('entrada_estoque.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    valor_custo_unitario = db.Column(db.Float, nullable=False)
    produto = db.relationship('Produto')
    
# ROTA DE FATURAMENTO ATUALIZADA (POST)
@app.route('/faturamento', methods=['GET', 'POST'])
@login_required
def faturamento():
    if request.method == 'POST':
        os_ids = request.form.getlist('os_ids')
        if not os_ids:
            flash('Nenhuma Ordem de Serviço foi selecionada para faturar.', 'warning')
            return redirect(url_for('faturamento'))

        pagamento_tipos = request.form.getlist('pagamento_tipo[]')
        pagamento_valores_str = request.form.getlist('pagamento_valor[]')
        pagamento_vencimentos_str = request.form.getlist('pagamento_vencimento[]')
        pagamento_chaves_pix = request.form.getlist('pagamento_chave_pix[]')
        pagamento_num_parcelas = request.form.getlist('pagamento_num_parcelas[]')

        if not pagamento_tipos:
            flash('É necessário adicionar pelo menos uma forma de pagamento.', 'danger')
            return redirect(url_for('faturamento'))

        ordens = OrdemServico.query.filter(OrdemServico.id.in_(os_ids)).all()
        cliente_id = ordens[0].cliente_id
        valor_total_fatura = sum(os.valor_total for os in ordens)

        try:
            valores_pagamentos = [float(v) for v in pagamento_valores_str]
            if abs(sum(valores_pagamentos) - valor_total_fatura) > 0.01:
                flash(f'Erro: A soma dos pagamentos (R$ {sum(valores_pagamentos):.2f}) não corresponde ao valor total das O.S. (R$ {valor_total_fatura:.2f}).', 'danger')
                return redirect(url_for('faturamento'))
            
            # CORREÇÃO: Define os valores principais com base no primeiro pagamento
            vencimento_principal = datetime.datetime.strptime(pagamento_vencimentos_str[0], '%Y-%m-%d').date()
            tipo_principal = pagamento_tipos[0]
            chave_pix_principal = pagamento_chaves_pix[0] if tipo_principal == 'PIX' and pagamento_chaves_pix[0] else None

            nova_fatura = Faturamento(
                cliente_id=cliente_id,
                data_vencimento=vencimento_principal,
                tipo_pagamento=tipo_principal,
                chave_pix=chave_pix_principal
            )
            
            for i in range(len(pagamento_tipos)):
                vencimento = datetime.datetime.strptime(pagamento_vencimentos_str[i], '%Y-%m-%d').date()
                novo_pagamento = Pagamento(
                    tipo_pagamento=pagamento_tipos[i],
                    valor=valores_pagamentos[i],
                    data_vencimento=vencimento,
                    chave_pix=pagamento_chaves_pix[i] if pagamento_chaves_pix[i] else None,
                    numero_parcelas=int(pagamento_num_parcelas[i])
                )
                nova_fatura.pagamentos.append(novo_pagamento)

            for os in ordens:
                os.status = 'Faturada'
                nova_fatura.ordens.append(os)
            
            db.session.add(nova_fatura)
            db.session.commit()
            flash(f'Fatura #{nova_fatura.id} gerada com sucesso!', 'success')
            return redirect(url_for('listar_faturas', open_pdf=nova_fatura.id))

        except Exception as e:
            db.session.rollback()
            logging.error(f"Erro ao gerar fatura: {e}")
            flash(f'Ocorreu um erro ao gerar a fatura: {e}', 'danger')
            return redirect(url_for('faturamento'))

    # Lógica GET (sem alterações)
    data_inicio_str, data_fim_str = request.args.get('data_inicio'), request.args.get('data_fim')
    cliente_id = request.args.get('cliente_id', 'todos')
    query = OrdemServico.query.filter(OrdemServico.status == 'Finalizada')
    if data_inicio_str: query = query.filter(OrdemServico.data_criacao >= datetime.datetime.strptime(data_inicio_str, '%Y-%m-%d').date())
    if data_fim_str: query = query.filter(OrdemServico.data_criacao < datetime.datetime.strptime(data_fim_str, '%Y-%m-%d').date() + datetime.timedelta(days=1))
    if cliente_id != 'todos': query = query.filter(OrdemServico.cliente_id == int(cliente_id))
    ordens_para_faturar = query.order_by(OrdemServico.data_criacao.desc()).all()
    todos_clientes = Cliente.query.order_by(Cliente.nome).all()
    return render_template('faturamento.html', ordens=ordens_para_faturar, todos_clientes=todos_clientes, data_inicio=data_inicio_str, data_fim=data_fim_str, cliente_id_filtro=cliente_id)

# NOVA ROTA PARA LISTAR FATURAS
@app.route('/faturas')
@login_required
def listar_faturas():
    # Adicionar filtros no futuro se necessário (cliente, data, etc.)
    faturas = Faturamento.query.order_by(Faturamento.data_emissao.desc()).all()
    return render_template('listar_faturas.html', faturas=faturas)
    
# Rota para CANCELAR uma fatura e liberar as O.S.
@app.route('/faturamento/cancelar/<int:fatura_id>', methods=['POST'])
@login_required
def cancelar_fatura(fatura_id):
    fatura_para_cancelar = Faturamento.query.get_or_404(fatura_id)

    # AMARRAÇÃO: Verifica se existe algum pagamento já recebido nesta fatura
    pagamentos_recebidos = Pagamento.query.filter_by(faturamento_id=fatura_id, status='Recebido').first()
    if pagamentos_recebidos:
        flash(f'A Fatura #{fatura_id} não pode ser cancelada pois possui pagamentos recebidos. Estorne os recebimentos primeiro.', 'danger')
        return redirect(url_for('relatorio_faturamento'))

    try:
        ordens_associadas = fatura_para_cancelar.ordens.all()
        for os in ordens_associadas:
            os.status = 'Finalizada'
        
        db.session.delete(fatura_para_cancelar)
        db.session.commit()
        flash(f'Fatura #{fatura_id} cancelada com sucesso! As O.S. foram liberadas.', 'success')
    except Exception as e:
        db.session.rollback()
        logging.error(f"Erro ao cancelar fatura: {e}")
        flash('Ocorreu um erro ao tentar cancelar a fatura.', 'danger')

    return redirect(url_for('relatorio_faturamento'))

# --- ROTAS DE AUTENTICAÇÃO (sem alterações) ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user_existente = User.query.filter_by(username=username).first()
        if user_existente:
            flash('Este nome de usuário já está em uso. Por favor, escolha outro.', 'danger')
            return redirect(url_for('register'))
        novo_usuario = User(username=username)
        novo_usuario.set_password(password)
        db.session.add(novo_usuario)
        db.session.commit()
        flash('Conta criada com sucesso! Por favor, faça o login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash('Login efetuado com sucesso!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Nome de usuário ou senha inválidos.', 'danger')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu do sistema.', 'success')
    return redirect(url_for('login'))

# Rota para o DASHBOARD (Página Inicial) - Sem alterações
@app.route('/')
@login_required
def dashboard():
    hoje = datetime.date.today()

    # --- Lógica do Dashboard (Cards) ---
    ordens_finalizadas_no_mes_lista = OrdemServico.query.filter(
        OrdemServico.status.in_(['Finalizada', 'Faturada']),
        extract('month', OrdemServico.data_criacao) == hoje.month,
        extract('year', OrdemServico.data_criacao) == hoje.year
    ).all()
    total_faturado_mes = sum(ordem.valor_total for ordem in ordens_finalizadas_no_mes_lista)
    os_finalizadas_mes = len(ordens_finalizadas_no_mes_lista)
    os_abertas = OrdemServico.query.filter(OrdemServico.status == 'Aberta').count()
    ticket_medio = (total_faturado_mes / os_finalizadas_mes) if os_finalizadas_mes > 0 else 0
    
    # --- LÓGICA DO GRÁFICO CORRIGIDA E SIMPLIFICADA ---
    chart_labels = []
    chart_data = []
    
    # Loop pelos últimos 6 meses
    for i in range(6):
        # Calcula o primeiro dia do mês que estamos analisando
        data_referencia = hoje - relativedelta(months=i)
        primeiro_dia_mes = data_referencia.replace(day=1)
        
        # Calcula o primeiro dia do mês seguinte para usar como limite
        primeiro_dia_proximo_mes = primeiro_dia_mes + relativedelta(months=1)

        # Busca todas as ordens finalizadas/faturadas DENTRO daquele mês
        ordens_do_mes = OrdemServico.query.filter(
            OrdemServico.status.in_(['Finalizada', 'Faturada']),
            OrdemServico.data_criacao >= primeiro_dia_mes,
            OrdemServico.data_criacao < primeiro_dia_proximo_mes
        ).all()

        # Soma o faturamento daquele mês
        faturamento_mes_total = sum(ordem.valor_total for ordem in ordens_do_mes)
        
        # Adiciona os dados nas listas para o gráfico
        nome_mes = primeiro_dia_mes.strftime('%b/%y') # Ex: Set/25
        chart_labels.append(nome_mes)
        chart_data.append(faturamento_mes_total)

    # Inverte as listas para que o gráfico seja exibido em ordem cronológica
    chart_labels.reverse()
    chart_data.reverse()
    
    return render_template('dashboard.html', 
                           total_faturado=total_faturado_mes,
                           os_abertas=os_abertas,
                           os_finalizadas_mes=os_finalizadas_mes,
                           ticket_medio=ticket_medio,
                           chart_labels=chart_labels,
                           chart_data=chart_data)

# Rota para ATUALIZAR status de uma O.S. (reabrir)
@app.route('/atualizar/<int:id>')
@login_required
def atualizar(id):
    os_para_atualizar = OrdemServico.query.get_or_404(id)

    # AMARRAÇÃO: Bloqueia reabertura se a O.S. já foi faturada
    if os_para_atualizar.status == 'Faturada':
        flash(f'A O.S. #{id} não pode ser reaberta pois já foi faturada. Cancele o faturamento primeiro.', 'danger')
        return redirect(url_for('listar_ordens'))

    if os_para_atualizar.status == 'Finalizada':
        os_para_atualizar.status = 'Aberta'
        os_para_atualizar.data_fechamento = None
        try:
            db.session.commit()
            flash('O.S. reaberta com sucesso!', 'success')
        except:
            db.session.rollback()
            flash('Erro ao reabrir a O.S.', 'danger')
    return redirect(url_for('listar_ordens'))

# Rota para a LISTA de Ordens de Serviço (sem alterações)
@app.route('/ordens')
@login_required
def listar_ordens():
    search_term = request.args.get('q', '')
    query = OrdemServico.query
    if search_term:
        query = query.join(Cliente)
        search_filter = or_(Cliente.nome.ilike(f'%{search_term}%'), OrdemServico.problema.ilike(f'%{search_term}%'))
        if search_term.isdigit(): search_filter = or_(search_filter, OrdemServico.id == int(search_term))
        query = query.filter(search_filter)
    ordens = query.order_by(OrdemServico.data_criacao.desc()).all()
    clientes = Cliente.query.order_by(Cliente.nome).all()
    return render_template('index.html', ordens=ordens, clientes=clientes, search_term=search_term)

# Rota para DELETAR uma O.S. (com verificação)
@app.route('/deletar/<int:id>')
@login_required
def deletar(id):
    os_para_deletar = OrdemServico.query.get_or_404(id)
    if os_para_deletar.status == 'Faturada':
        flash('Não é possível deletar uma O.S. que já foi faturada.', 'danger')
        return redirect(url_for('listar_ordens'))
    try:
        db.session.delete(os_para_deletar)
        db.session.commit()
        flash('Ordem de Serviço deletada com sucesso.', 'info')
    except:
        flash('Erro ao deletar a Ordem de Serviço.', 'danger')
    return redirect(url_for('listar_ordens'))

# Rota para ver DETALHES de uma O.S.
@app.route('/os/<int:id>', methods=['GET', 'POST'])
@login_required
def detalhe_os(id):
    os = OrdemServico.query.get_or_404(id)

    if request.method == 'POST':
        # AMARRAÇÃO: Só permite alterar se o status for 'Aberta'
        if os.status != 'Aberta':
            flash(f'A O.S. #{os.id} não pode ser modificada pois o status é "{os.status}". É necessário reabri-la primeiro.', 'warning')
            return redirect(url_for('detalhe_os', id=os.id))

        os.problema = request.form['problema'].upper()
        os.valor_servicos = float(request.form.get('valor_servicos', 0) or 0)
        try:
            db.session.commit()
            flash('Ordem de Serviço atualizada com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar a Ordem de Serviço: {e}', 'danger')
        return redirect(url_for('detalhe_os', id=os.id))

    produtos = Produto.query.order_by(Produto.descricao).all()
    return render_template('detalhe_os.html', os=os, produtos=produtos)

    # Lógica GET atualizada para buscar os produtos
    produtos = Produto.query.order_by(Produto.descricao).all()
    return render_template('detalhe_os.html', os=os, produtos=produtos)

# Rota para ADICIONAR uma peça (agora com baixa de estoque)
@app.route('/os/<int:os_id>/adicionar_peca', methods=['POST'])
@login_required
def adicionar_peca(os_id):
    os = OrdemServico.query.get_or_404(os_id)
    # AMARRAÇÃO: Só permite adicionar se o status for 'Aberta'
    if os.status != 'Aberta':
        flash(f'Não é possível adicionar peças na O.S. #{os.id} pois o status é "{os.status}".', 'warning')
        return redirect(url_for('detalhe_os', id=os_id))

    try:
        produto_id = request.form['produto_id']
        quantidade = int(request.form['quantidade'])
        produto = Produto.query.get(produto_id)
        if not produto:
            flash('Produto não encontrado.', 'danger')
            return redirect(url_for('detalhe_os', id=os_id))
        if produto.quantidade_estoque < quantidade:
            flash(f'Estoque insuficiente para "{produto.descricao}". Disponível: {produto.quantidade_estoque}', 'danger')
            return redirect(url_for('detalhe_os', id=os_id))

        nova_peca = Peca(
            descricao=produto.descricao, 
            quantidade=quantidade, 
            valor_unitario=produto.valor_venda,
            ordem_servico_id=os_id
        )
        produto.quantidade_estoque -= quantidade
        db.session.add(nova_peca)
        db.session.commit()
        flash('Peça adicionada e estoque atualizado com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao adicionar a peça: {e}', 'danger')
    
    return redirect(url_for('detalhe_os', id=os_id))

# Rota para DELETAR uma peça (agora com estorno de estoque)
@app.route('/peca/deletar/<int:peca_id>')
@login_required
def deletar_peca(peca_id):
    peca_para_deletar = Peca.query.get_or_404(peca_id)
    os_id = peca_para_deletar.ordem_servico.id

    # AMARRAÇÃO: Só permite remover se o status for 'Aberta'
    if peca_para_deletar.ordem_servico.status != 'Aberta':
        flash(f'Não é possível remover peças da O.S. #{os_id} pois o status é "{peca_para_deletar.ordem_servico.status}".', 'warning')
        return redirect(url_for('detalhe_os', id=os_id))
        
    try:
        produto = Produto.query.filter_by(descricao=peca_para_deletar.descricao).first()
        if produto:
            produto.quantidade_estoque += peca_para_deletar.quantidade
        
        db.session.delete(peca_para_deletar)
        db.session.commit()
        flash('Peça removida e estoque estornado com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao remover a peça: {e}', 'danger')
    
    return redirect(url_for('detalhe_os', id=os_id))
    
@app.route('/faturamento/pdf/<int:fatura_id>')
@login_required
def gerar_fatura_pdf(fatura_id):
    fatura = Faturamento.query.get_or_404(fatura_id)
    print("="*30)
    print(f"DEPURANDO FATURA #{fatura.id}")
    print("Pagamentos encontrados:", fatura.pagamentos)
    print("="*30)
    logo_data_uri = None
    try:
        project_path = pathlib.Path(__file__).parent
        logo_path = project_path / 'static' / 'images' / 'logo.png'
        with open(logo_path, 'rb') as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        logo_data_uri = f"data:image/png;base64,{encoded_string}"
    except FileNotFoundError:
        logging.warning("Arquivo logo.png não encontrado.")

    html_renderizado = render_template('fatura_pdf_template.html', fatura=fatura, logo_path=logo_data_uri)
    pdf = HTML(string=html_renderizado, base_url=str(project_path)).write_pdf()
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': f'inline; filename=fatura_{fatura.id}.pdf'})

# Rota para gerenciar CONTAS A RECEBER (agora automática)
@app.route('/contas-a-receber')
@login_required
def gerenciar_contas_a_receber():
    # AGORA BUSCA TODAS AS CONTAS, ordenando por status e depois por vencimento
    contas = Pagamento.query.order_by(Pagamento.status.asc(), Pagamento.data_vencimento.asc()).all()
    return render_template('contas_a_receber.html', contas=contas, today_date=datetime.date.today())

# --- Rotas existentes (Resto do arquivo) ---
# ... (copiar todo o resto do seu app.py, como as rotas de relatórios, clientes, etc.) ...
# ... o código abaixo é o restante do seu app.py sem alterações ...

# Rota para o Relatório de Ordens de Serviço
@app.route('/relatorio/os')
@login_required
def relatorio_os():
    data_inicio_str = request.args.get('data_inicio')
    data_fim_str = request.args.get('data_fim')
    status = request.args.get('status', 'todas')
    cliente_id = request.args.get('cliente_id', 'todos')
    sort_by = request.args.get('sort_by', 'data_criacao')
    direction = request.args.get('direction', 'desc')

    query = OrdemServico.query.join(Cliente)
    if data_inicio_str:
        data_inicio = datetime.datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
        query = query.filter(OrdemServico.data_criacao >= data_inicio)
    if data_fim_str:
        data_fim = datetime.datetime.strptime(data_fim_str, '%Y-%m-%d').date()
        query = query.filter(OrdemServico.data_criacao < data_fim + datetime.timedelta(days=1))
    if status != 'todas':
        query = query.filter(OrdemServico.status == status)
    if cliente_id != 'todos':
        query = query.filter(OrdemServico.cliente_id == int(cliente_id))

    if sort_by == 'id':
        order_column = OrdemServico.id
    elif sort_by == 'cliente':
        order_column = case((Cliente.tipo_pessoa == 'FISICA', Cliente.nome), else_=Cliente.razao_social)
    else:
        order_column = OrdemServico.data_criacao

    if direction == 'asc':
        query = query.order_by(order_column.asc())
    else:
        query = query.order_by(order_column.desc())

    ordens = query.all()

    ordem_inteligente_select = case((Cliente.nome != None, Cliente.nome), else_=Cliente.razao_social)
    todos_clientes = Cliente.query.order_by(ordem_inteligente_select).all()

    return render_template('relatorio_os.html',
                           ordens=ordens,
                           todos_clientes=todos_clientes,
                           data_inicio=data_inicio_str,
                           data_fim=data_fim_str,
                           status_filtro=status,
                           cliente_id_filtro=cliente_id,
                           sort_by=sort_by,
                           direction=direction)

# Rota para o Relatório de Faturamento
@app.route('/relatorio/faturamento')
@login_required
def relatorio_faturamento():
    data_inicio_str = request.args.get('data_inicio')
    data_fim_str = request.args.get('data_fim')
    cliente_id = request.args.get('cliente_id', 'todos')

    # 1. Monta a consulta base para Faturas
    query_faturas = Faturamento.query

    # 2. Aplica os filtros na consulta de Faturas
    if data_inicio_str:
        data_inicio = datetime.datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
        query_faturas = query_faturas.filter(Faturamento.data_emissao >= data_inicio)
    if data_fim_str:
        data_fim = datetime.datetime.strptime(data_fim_str, '%Y-%m-%d').date()
        query_faturas = query_faturas.filter(Faturamento.data_emissao < data_fim + datetime.timedelta(days=1))
    if cliente_id != 'todos':
        query_faturas = query_faturas.filter(Faturamento.cliente_id == int(cliente_id))
    
    # 3. Executa a consulta e obtém a lista de faturas para a tabela
    faturas_filtradas = query_faturas.order_by(Faturamento.id.desc()).all()

    # 4. Calcula os totais dos cards com base nas faturas que foram filtradas
    total_servicos = 0
    total_pecas = 0
    set_os_finalizadas = set()

    for fatura in faturas_filtradas:
        for os in fatura.ordens:
            total_servicos += os.valor_servicos
            total_pecas += os.valor_pecas
            set_os_finalizadas.add(os.id)
    
    faturamento_total = total_servicos + total_pecas
    num_os_finalizadas = len(set_os_finalizadas)
    ticket_medio = (faturamento_total / num_os_finalizadas) if num_os_finalizadas > 0 else 0
    
    # Busca todos os clientes para popular o menu de seleção
    ordem_inteligente = case((Cliente.nome != None, Cliente.nome), else_=Cliente.razao_social)
    todos_clientes = Cliente.query.order_by(ordem_inteligente).all()

    return render_template('relatorio_faturamento.html',
                           faturas=faturas_filtradas, # Passa a lista de faturas para o template
                           faturamento_total=faturamento_total,
                           total_servicos=total_servicos,
                           total_pecas=total_pecas,
                           num_os_finalizadas=num_os_finalizadas,
                           ticket_medio=ticket_medio,
                           todos_clientes=todos_clientes,
                           data_inicio=data_inicio_str,
                           data_fim=data_fim_str,
                           cliente_id_filtro=cliente_id)

# Rota para gerenciar CLIENTES
@app.route('/clientes', methods=['GET', 'POST'])
@login_required
def gerenciar_clientes():
    if request.method == 'POST':
        tipo_pessoa = request.form['tipo_pessoa']
        validador_cpf = CPF()
        validador_cnpj = CNPJ()
        if tipo_pessoa == 'FISICA':
            cpf_raw = request.form.get('cpf', '')
            cpf_limpo = "".join(filter(str.isdigit, cpf_raw))
            if not validador_cpf.validate(cpf_limpo):
                flash('CPF inválido. Por favor, verifique o número digitado.', 'danger')
                return redirect(url_for('gerenciar_clientes'))
            novo_cliente = Cliente(tipo_pessoa='FISICA', nome=request.form.get('nome', '').upper(), cpf=cpf_limpo)
        else:
            cnpj_raw = request.form.get('cnpj', '')
            cnpj_limpo = "".join(filter(str.isdigit, cnpj_raw))
            if not validador_cnpj.validate(cnpj_limpo):
                flash('CNPJ inválido. Por favor, verifique o número digitado.', 'danger')
                return redirect(url_for('gerenciar_clientes'))
            novo_cliente = Cliente(tipo_pessoa='JURIDICA', razao_social=request.form.get('razao_social', '').upper(), cnpj=cnpj_limpo, inscricao_estadual="".join(filter(str.isdigit, request.form.get('inscricao_estadual', ''))))
        novo_cliente.telefone = "".join(filter(str.isdigit, request.form.get('telefone', '')))
        novo_cliente.email = request.form.get('email')
        novo_cliente.cep = "".join(filter(str.isdigit, request.form.get('cep', '')))
        novo_cliente.rua = request.form.get('rua', '').upper()
        novo_cliente.numero = request.form.get('numero')
        novo_cliente.bairro = request.form.get('bairro', '').upper()
        novo_cliente.cidade = request.form.get('cidade', '').upper()
        novo_cliente.uf = request.form.get('uf', '').upper()
        try:
            db.session.add(novo_cliente)
            db.session.commit()
            flash(f'Cliente "{novo_cliente.nome_exibicao}" cadastrado com sucesso!', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Erro: Já existe um cliente com este Nome/Razão Social ou Documento.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro inesperado: {e}', 'danger')
        return redirect(url_for('gerenciar_clientes'))
    todos_clientes = Cliente.query.order_by(Cliente.id.desc()).all()
    return render_template('clientes.html', clientes=todos_clientes)

# Rota para gerenciar FORNECEDORES
@app.route('/fornecedores', methods=['GET', 'POST'])
@login_required
def gerenciar_fornecedores():
    if request.method == 'POST':
        validador_cnpj = CNPJ()
        cnpj_raw = request.form.get('cnpj', '')
        cnpj_limpo = "".join(filter(str.isdigit, cnpj_raw))

        if cnpj_limpo and not validador_cnpj.validate(cnpj_limpo):
            flash('CNPJ inválido. Por favor, verifique o número digitado.', 'danger')
            return redirect(url_for('gerenciar_fornecedores'))

        novo_fornecedor = Fornecedor(
            razao_social=request.form.get('razao_social', '').upper(),
            nome_fantasia=request.form.get('nome_fantasia', '').upper(),
            cnpj=cnpj_limpo,
            telefone="".join(filter(str.isdigit, request.form.get('telefone', ''))),
            email=request.form.get('email'),
            cep="".join(filter(str.isdigit, request.form.get('cep', ''))),
            rua=request.form.get('rua', '').upper(),
            numero=request.form.get('numero'),
            bairro=request.form.get('bairro', '').upper(),
            cidade=request.form.get('cidade', '').upper(),
            uf=request.form.get('uf', '').upper()
        )

        try:
            db.session.add(novo_fornecedor)
            db.session.commit()
            flash(f'Fornecedor "{novo_fornecedor.razao_social}" cadastrado com sucesso!', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Erro: Já existe um fornecedor com esta Razão Social ou CNPJ.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro inesperado: {e}', 'danger')
        
        return redirect(url_for('gerenciar_fornecedores'))

    todos_fornecedores = Fornecedor.query.order_by(Fornecedor.razao_social).all()
    return render_template('fornecedores.html', fornecedores=todos_fornecedores)

# Rota para DELETAR um cliente
@app.route('/cliente/deletar/<int:id>')
@login_required
def deletar_cliente(id):
    cliente_para_deletar = Cliente.query.get_or_404(id)
    if cliente_para_deletar.ordens:
        flash(f'Não é possível deletar "{cliente_para_deletar.nome_exibicao}", pois ele possui Ordens de Serviço registradas.', 'warning')
        return redirect(url_for('gerenciar_clientes'))
    try:
        db.session.delete(cliente_para_deletar)
        db.session.commit()
        flash('Cliente deletado com sucesso!', 'success')
    except:
        flash('Erro ao deletar o cliente.', 'danger')
    return redirect(url_for('gerenciar_clientes'))

# Rota para EDITAR um cliente
@app.route('/cliente/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    if request.method == 'POST':
        cliente.tipo_pessoa = request.form['tipo_pessoa']
        validador_cpf = CPF()
        validador_cnpj = CNPJ()
        if cliente.tipo_pessoa == 'FISICA':
            cliente.nome = request.form.get('nome', '').upper()
            cpf_raw = request.form.get('cpf', '')
            cliente.cpf = "".join(filter(str.isdigit, cpf_raw))
            cliente.razao_social, cliente.cnpj, cliente.inscricao_estadual = None, None, None
            if not validador_cpf.validate(cliente.cpf):
                flash('CPF inválido. Por favor, verifique o número digitado.', 'danger')
                return redirect(url_for('editar_cliente', id=id))
        else:
            cliente.razao_social = request.form.get('razao_social', '').upper()
            cnpj_raw = request.form.get('cnpj', '')
            cliente.cnpj = "".join(filter(str.isdigit, cnpj_raw))
            cliente.inscricao_estadual = "".join(filter(str.isdigit, request.form.get('inscricao_estadual', '')))
            cliente.nome, cliente.cpf = None, None
            if not validador_cnpj.validate(cliente.cnpj):
                flash('CNPJ inválido. Por favor, verifique o número digitado.', 'danger')
                return redirect(url_for('editar_cliente', id=id))
        cliente.telefone = "".join(filter(str.isdigit, request.form.get('telefone', '')))
        cliente.email = request.form.get('email')
        cliente.cep = "".join(filter(str.isdigit, request.form.get('cep', '')))
        cliente.rua = request.form.get('rua', '').upper()
        cliente.numero = request.form.get('numero')
        cliente.bairro = request.form.get('bairro', '').upper()
        cliente.cidade = request.form.get('cidade', '').upper()
        cliente.uf = request.form.get('uf', '').upper()
        try:
            db.session.commit()
            flash('Cliente atualizado com sucesso!', 'success')
            return redirect(url_for('gerenciar_clientes'))
        except IntegrityError:
            db.session.rollback()
            flash('Erro: Já existe outro cliente com este Nome/Razão Social ou Documento.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro inesperado: {e}', 'danger')
        return redirect(url_for('editar_cliente', id=id))
    return render_template('editar_cliente.html', cliente=cliente)

# Rota que atua como uma API interna para consultar CNPJs
@app.route('/consulta-cnpj/<cnpj>')
@login_required
def consulta_cnpj(cnpj):
    cnpj_limpo = "".join(filter(str.isdigit, cnpj))
    if len(cnpj_limpo) != 14:
        return jsonify({'erro': 'CNPJ inválido'}), 400
    try:
        response = requests.get(f'https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}')
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({'erro': 'CNPJ não encontrado ou serviço indisponível'}), 404
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao consultar BrasilAPI: {e}")
        return jsonify({'erro': 'Falha na comunicação com o serviço de consulta'}), 500

# Rota que atua como API interna para consultar CEPs
@app.route('/consulta-cep/<cep>')
@login_required
def consulta_cep(cep):
    cep_limpo = "".join(filter(str.isdigit, cep))
    if len(cep_limpo) != 8:
        return jsonify({'erro': 'CEP inválido'}), 400
    try:
        response = requests.get(f'https://brasilapi.com.br/api/cep/v1/{cep_limpo}')
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({'erro': 'CEP não encontrado ou serviço indisponível'}), 404
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao consultar BrasilAPI (CEP): {e}")
        return jsonify({'erro': 'Falha na comunicação com o serviço de consulta'}), 500

# Rota para ADICIONAR uma nova O.S.
@app.route('/adicionar', methods=['POST'])
@login_required
def adicionar():
    cliente_id = request.form['cliente_id']
    problema = request.form['problema'].upper()
    data_criacao_str = request.form.get('data_criacao')
    nova_os = OrdemServico(cliente_id=cliente_id, problema=problema)
    if data_criacao_str:
        nova_os.data_criacao = datetime.datetime.fromisoformat(data_criacao_str)
    try:
        db.session.add(nova_os)
        db.session.commit()
        flash('Ordem de Serviço criada com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao criar a Ordem de Serviço: {e}', 'danger')
    return redirect(url_for('listar_ordens'))

# Rota para gerar o PDF da O.S.
@app.route('/os/pdf/<int:id>')
@login_required
def gerar_os_pdf(id):
    os_obj = OrdemServico.query.get_or_404(id)
    logo_data_uri = None
    try:
        project_path = pathlib.Path(__file__).parent
        logo_path = project_path / 'static' / 'images' / 'logo.png'
        with open(logo_path, 'rb') as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        logo_data_uri = f"data:image/png;base64,{encoded_string}"
    except FileNotFoundError:
        print("AVISO: Arquivo logo.png não encontrado.")
    html_renderizado = render_template('os_pdf_template.html', os=os_obj, logo_path=logo_data_uri)
    pdf = HTML(string=html_renderizado, base_url=str(project_path)).write_pdf()
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': f'inline; filename=os_{os_obj.id}.pdf'})

# Rota para a página de confirmação de finalização de O.S.
@app.route('/os/<int:id>/finalizar', methods=['GET', 'POST'])
@login_required
def finalizar_os(id):
    os = OrdemServico.query.get_or_404(id)
    if os.status == 'Faturada':
        flash('Não é possível alterar o status de uma O.S. faturada.', 'danger')
        return redirect(url_for('listar_ordens'))
    if request.method == 'POST':
        data_fechamento_str = request.form.get('data_fechamento')
        os.data_fechamento = datetime.datetime.fromisoformat(data_fechamento_str) if data_fechamento_str else datetime.datetime.utcnow()
        os.status = 'Finalizada'
        try:
            db.session.commit()
            flash('Ordem de Serviço finalizada com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao finalizar a O.S.: {e}', 'danger')
        return redirect(url_for('listar_ordens'))
    return render_template('finalizar_os.html', os=os)

# Rota para EXPORTAR o Relatório de O.S. para PDF
@app.route('/relatorio/os/pdf')
@login_required
def relatorio_os_pdf():
    ids_str = request.args.get('ids')
    query = OrdemServico.query
    if ids_str:
        ids_lista = [int(id) for id in ids_str.split(',')]
        query = query.filter(OrdemServico.id.in_(ids_lista))
    else:
        data_inicio_str, data_fim_str = request.args.get('data_inicio'), request.args.get('data_fim')
        status, cliente_id = request.args.get('status', 'todas'), request.args.get('cliente_id', 'todos')
        if data_inicio_str: query = query.filter(OrdemServico.data_criacao >= datetime.datetime.strptime(data_inicio_str, '%Y-%m-%d').date())
        if data_fim_str: query = query.filter(OrdemServico.data_criacao < datetime.datetime.strptime(data_fim_str, '%Y-%m-%d').date() + datetime.timedelta(days=1))
        if status != 'todas': query = query.filter(OrdemServico.status == status)
        if cliente_id != 'todos': query = query.filter(OrdemServico.cliente_id == int(cliente_id))

    ordens = query.order_by(OrdemServico.data_criacao.desc()).all()
    total_relatorio = sum(ordem.valor_total for ordem in ordens)
    logo_data_uri = None
    try:
        project_path = pathlib.Path(__file__).parent
        logo_path = project_path / 'static' / 'images' / 'logo.png'
        with open(logo_path, 'rb') as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        logo_data_uri = f"data:image/png;base64,{encoded_string}"
    except FileNotFoundError:
        logging.warning("Arquivo logo.png não encontrado para o PDF do relatório.")
    html_renderizado = render_template('relatorio_os_pdf.html', ordens=ordens, total_relatorio=total_relatorio, data_geracao=datetime.datetime.now(), logo_path=logo_data_uri)
    pdf = HTML(string=html_renderizado).write_pdf()
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': 'inline; filename=relatorio_os.pdf'})

# Rota para EXPORTAR o Relatório de O.S. para Excel
@app.route('/relatorio/os/excel')
@login_required
def relatorio_os_excel():
    ids_str = request.args.get('ids')
    query = OrdemServico.query
    if ids_str:
        ids_lista = [int(id) for id in ids_str.split(',')]
        query = query.filter(OrdemServico.id.in_(ids_lista))
    else:
        data_inicio_str, data_fim_str = request.args.get('data_inicio'), request.args.get('data_fim')
        status, cliente_id = request.args.get('status', 'todas'), request.args.get('cliente_id', 'todos')
        if data_inicio_str: query = query.filter(OrdemServico.data_criacao >= datetime.datetime.strptime(data_inicio_str, '%Y-%m-%d').date())
        if data_fim_str: query = query.filter(OrdemServico.data_criacao < datetime.datetime.strptime(data_fim_str, '%Y-%m-%d').date() + datetime.timedelta(days=1))
        if status != 'todas': query = query.filter(OrdemServico.status == status)
        if cliente_id != 'todos': query = query.filter(OrdemServico.cliente_id == int(cliente_id))

    ordens = query.order_by(OrdemServico.data_criacao.desc()).all()
    dados_para_excel = [{'ID': o.id, 'Cliente': o.cliente.nome_exibicao if o.cliente else 'CLIENTE REMOVIDO', 'Data': o.data_criacao.strftime('%d/%m/%Y'), 'Status': o.status, 'Valor Total': o.valor_total} for o in ordens]
    df = pd.DataFrame(dados_para_excel)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='RelatorioOS')
    output.seek(0)
    return Response(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename=relatorio_os.xlsx'})

# Rota para marcar um pagamento como RECEBIDO
@app.route('/pagamento/receber/<int:pagamento_id>', methods=['POST'])
@login_required
def marcar_como_recebido(pagamento_id):
    pagamento = Pagamento.query.get_or_404(pagamento_id)
    try:
        pagamento.status = 'Recebido'
        db.session.commit()
        flash(f'Pagamento #{pagamento.id} marcado como recebido!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao dar baixa no pagamento: {e}', 'danger')
    return redirect(url_for('gerenciar_contas_a_receber'))

# --- COMANDOS DE TERMINAL ---
@app.cli.command("create-admin")
def create_admin_command():
    import getpass
    username = input("Digite o nome de usuário do admin: ")
    password = getpass.getpass("Digite a senha do admin (não aparecerá na tela): ")
    user_existente = User.query.filter_by(username=username).first()
    if user_existente:
        print(f"Erro: O usuário '{username}' já existe.")
        return
    novo_admin = User(username=username.upper())
    novo_admin.set_password(password)
    db.session.add(novo_admin)
    db.session.commit()
    print(f"Administrador '{username.upper()}' criado com sucesso!")

# NOVO COMANDO DE TERMINAL PARA ATUALIZAR A TABELA DE FORNECEDORES
@app.cli.command("migrate-suppliers")
def migrate_suppliers_command():
    """Adiciona as colunas de endereço à tabela de fornecedores existente."""
    print("Iniciando migração da tabela de fornecedores...")
    
    colunas_para_adicionar = {
        'cep': 'TEXT',
        'rua': 'TEXT',
        'numero': 'TEXT',
        'bairro': 'TEXT',
        'cidade': 'TEXT',
        'uf': 'TEXT'
    }

    # Remove a coluna 'endereco' antiga, se ela existir
    try:
        # SQLite tem limitações, então a forma de remover colunas é complexa.
        # Por agora, vamos focar em adicionar as novas. A antiga ficará inativa.
        # Em uma próxima etapa, se quiser, podemos limpar a coluna antiga.
        print("Verificando colunas de endereço...")
    except:
        pass

    for nome_coluna, tipo_coluna in colunas_para_adicionar.items():
        try:
            with app.app_context():
                # Monta o comando SQL para adicionar a coluna
                comando_sql = text(f'ALTER TABLE fornecedor ADD COLUMN {nome_coluna} {tipo_coluna}')
                db.session.execute(comando_sql)
                db.session.commit()
                print(f"  - Coluna '{nome_coluna}' adicionada com sucesso.")
        except OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"  - Coluna '{nome_coluna}' já existe, pulando.")
            else:
                print(f"  - Erro ao adicionar coluna '{nome_coluna}': {e}")
                db.session.rollback()
        except Exception as e:
            print(f"  - Um erro inesperado ocorreu: {e}")
            db.session.rollback()
    
    print("Migração da tabela de fornecedores concluída.")

# Rota para gerenciar CONTAS A PAGAR
@app.route('/contas-a-pagar', methods=['GET', 'POST'])
@login_required
def gerenciar_contas_a_pagar():
    if request.method == 'POST':
        # ... (a lógica do POST continua a mesma, sem alterações)
        descricao = request.form['descricao'].upper()
        fornecedor_id = request.form.get('fornecedor_id')
        valor_total = float(request.form['valor'])
        # CORREÇÃO: Pegar a data de emissão do campo correto
        data_emissao_str = request.form.get('data_emissao')
        # Se o campo não existir no form, usa a data de hoje como padrão
        data_emissao = datetime.datetime.strptime(data_emissao_str, '%Y-%m-%d').date() if data_emissao_str else datetime.date.today()

        primeiro_vencimento = datetime.datetime.strptime(request.form['data_vencimento'], '%Y-%m-%d').date()
        num_parcelas = int(request.form.get('num_parcelas', 1))

        try:
            valor_parcela = round(valor_total / num_parcelas, 2)
            resto = round(valor_total - (valor_parcela * num_parcelas), 2)

            for i in range(num_parcelas):
                descricao_parcela = f"{descricao} {i+1}/{num_parcelas}" if num_parcelas > 1 else descricao
                vencimento_parcela = primeiro_vencimento + relativedelta(months=i)
                
                valor_final_parcela = valor_parcela
                if i == 0:
                    valor_final_parcela += resto
                
                nova_conta = ContaPagar(
                    descricao=descricao_parcela,
                    fornecedor_id=fornecedor_id,
                    valor=valor_final_parcela,
                    data_emissao=data_emissao,
                    data_vencimento=vencimento_parcela,
                    status='Pendente'
                )
                db.session.add(nova_conta)
            
            db.session.commit()
            flash(f'{num_parcelas} conta(s) a pagar cadastrada(s) com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro ao cadastrar a conta: {e}', 'danger')
        
        return redirect(url_for('gerenciar_contas_a_pagar'))

    # Lógica GET para exibir a página
    contas = ContaPagar.query.order_by(ContaPagar.status.asc(), ContaPagar.data_vencimento.asc()).all()
    fornecedores = Fornecedor.query.order_by(Fornecedor.razao_social).all()
    # CORREÇÃO: Envia a data de hoje para o template
    today_date_str = datetime.date.today().strftime('%Y-%m-%d')
    return render_template('contas_a_pagar.html', contas=contas, fornecedores=fornecedores, today_date=datetime.date.today())

# Rota para marcar uma conta como PAGA
@app.route('/conta/pagar/<int:conta_id>', methods=['POST'])
@login_required
def marcar_como_pago(conta_id):
    conta = ContaPagar.query.get_or_404(conta_id)
    try:
        conta.status = 'Pago'
        db.session.commit()
        flash(f'Conta #{conta.id} marcada como paga!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao dar baixa na conta: {e}', 'danger')
    return redirect(url_for('gerenciar_contas_a_pagar'))

# NOVO COMANDO DE TERMINAL PARA ATUALIZAR TABELAS FINANCEIRAS
@app.cli.command("migrate-financeiro")
def migrate_financeiro_command():
    """Cria tabelas financeiras e adiciona colunas faltantes."""
    print("Iniciando migração financeira...")
    try:
        # Tenta adicionar a coluna 'status' na tabela 'pagamento'
        comando_sql = text('ALTER TABLE pagamento ADD COLUMN status TEXT DEFAULT "Pendente"')
        db.session.execute(comando_sql)
        db.session.commit()
        print("  - Coluna 'status' adicionada à tabela 'pagamento'.")
    except Exception as e:
        if "duplicate column name" in str(e):
            print("  - Coluna 'status' já existe em 'pagamento', pulando.")
        else:
            print(f"  - Aviso ao adicionar coluna em 'pagamento': {e}")
        db.session.rollback()
    
    # Cria todas as tabelas que ainda não existem (como conta_pagar)
    with app.app_context():
        db.create_all()
    print("Tabelas financeiras verificadas/criadas.")
    print("Migração financeira concluída.")

# Rota para ESTORNAR um pagamento recebido
@app.route('/pagamento/estornar/<int:pagamento_id>', methods=['POST'])
@login_required
def estornar_recebimento(pagamento_id):
    pagamento = Pagamento.query.get_or_404(pagamento_id)
    try:
        pagamento.status = 'Pendente'
        db.session.commit()
        flash(f'Recebimento do pagamento #{pagamento.id} estornado com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao estornar o pagamento: {e}', 'danger')
    return redirect(url_for('gerenciar_contas_a_receber'))

# Rota para ESTORNAR uma conta paga
@app.route('/conta/estornar/<int:conta_id>', methods=['POST'])
@login_required
def estornar_pagamento(conta_id):
    conta = ContaPagar.query.get_or_404(conta_id)
    try:
        conta.status = 'Pendente'
        db.session.commit()
        flash(f'Pagamento da conta #{conta.id} estornado!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao estornar a conta: {e}', 'danger')
    return redirect(url_for('gerenciar_contas_a_pagar'))

# Rota para DELETAR uma conta a pagar (com verificação de status)
@app.route('/conta/deletar/<int:conta_id>', methods=['POST'])
@login_required
def deletar_conta_a_pagar(conta_id):
    conta = ContaPagar.query.get_or_404(conta_id)
    
    # AMARRAÇÃO: Verifica se a conta já foi paga
    if conta.status == 'Pago':
        flash(f'A conta "{conta.descricao}" não pode ser excluída pois já foi paga. É necessário estornar o pagamento primeiro.', 'danger')
        return redirect(url_for('gerenciar_contas_a_pagar'))

    # Se estiver pendente, prossegue com a exclusão
    try:
        db.session.delete(conta)
        db.session.commit()
        flash(f'Conta #{conta.id} deletada com sucesso!', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao deletar a conta: {e}', 'danger')
    
    return redirect(url_for('gerenciar_contas_a_pagar'))

# Rota para EDITAR uma conta a pagar
@app.route('/conta-a-pagar/editar/<int:conta_id>', methods=['GET', 'POST'])
@login_required
def editar_conta_a_pagar(conta_id):
    conta = ContaPagar.query.get_or_404(conta_id)
    
    if request.method == 'POST':
        try:
            conta.descricao = request.form['descricao'].upper()
            conta.fornecedor_id = request.form.get('fornecedor_id') if request.form.get('fornecedor_id') else None
            conta.valor = float(request.form['valor'])
            conta.data_emissao = datetime.datetime.strptime(request.form['data_emissao'], '%Y-%m-%d').date()
            conta.data_vencimento = datetime.datetime.strptime(request.form['data_vencimento'], '%Y-%m-%d').date()
            
            db.session.commit()
            flash('Conta a pagar atualizada com sucesso!', 'success')
            return redirect(url_for('gerenciar_contas_a_pagar'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro ao atualizar a conta: {e}', 'danger')
            return redirect(url_for('editar_conta_a_pagar', conta_id=conta.id))

    # Lógica GET para exibir a página de edição
    fornecedores = Fornecedor.query.order_by(Fornecedor.razao_social).all()
    return render_template('editar_conta_a_pagar.html', conta=conta, fornecedores=fornecedores)

# Rota para ADICIONAR um novo produto (GET para mostrar o form, POST para salvar)
@app.route('/produtos/adicionar', methods=['GET', 'POST'])
@login_required
def adicionar_produto():
    if request.method == 'POST':
        try:
            novo_produto = Produto(
                descricao=request.form['descricao'].upper(),
                ncm=request.form.get('ncm'),
                cest=request.form.get('cest'),
                origem=request.form.get('origem'),
                unidade_medida=request.form.get('unidade_medida', 'UN').upper(),
                valor_custo=float(request.form.get('valor_custo', 0)),
                margem_lucro=float(request.form.get('margem_lucro', 0))
            )
            novo_produto.valor_venda = novo_produto.valor_custo * (1 + (novo_produto.margem_lucro / 100))
            
            db.session.add(novo_produto)
            db.session.flush()

            novo_produto.sku = f'PROD{novo_produto.id:04d}'
            db.session.commit()
            flash(f'Produto "{novo_produto.descricao}" cadastrado com SKU {novo_produto.sku}!', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Erro: Já existe um produto com esta descrição ou SKU.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro inesperado: {e}', 'danger')
        return redirect(url_for('estoque'))
    
    # GET: CORREÇÃO APLICADA AQUI - Passa um objeto Produto vazio para o template
    return render_template('adicionar_produto.html', produto=Produto())

# Rota para a tela de gerenciamento de ESTOQUE
@app.route('/estoque')
@login_required
def gerenciar_estoque():
    produtos = Produto.query.order_by(Produto.descricao).all()
    return render_template('estoque.html', produtos=produtos)

# Rota para AJUSTAR o estoque de um produto
@app.route('/estoque/ajustar', methods=['POST'])
@login_required
def ajustar_estoque():
    try:
        produto_id = request.form['produto_id']
        nova_quantidade = int(request.form['quantidade'])
        produto = Produto.query.get(produto_id)

        if produto:
            produto.quantidade_estoque = nova_quantidade
            db.session.commit()
            flash(f'Estoque do produto "{produto.descricao}" atualizado para {nova_quantidade} unidade(s).', 'success')
        else:
            flash('Produto não encontrado.', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Ocorreu um erro ao ajustar o estoque: {e}', 'danger')
    
    return redirect(url_for('gerenciar_estoque'))

#Funções de migração 
# NOVO COMANDO DE TERMINAL PARA ATUALIZAR A TABELA DE PRODUTOS
@app.cli.command("migrate-produtos")
def migrate_produtos_command():
    """Adiciona a coluna de quantidade de estoque à tabela de produtos."""
    print("Iniciando migração da tabela de produtos...")
    try:
        comando_sql = text('ALTER TABLE produto ADD COLUMN quantidade_estoque INTEGER DEFAULT 0')
        db.session.execute(comando_sql)
        db.session.commit()
        print("  - Coluna 'quantidade_estoque' adicionada com sucesso.")
    except Exception as e:
        if "duplicate column name" in str(e):
            print("  - Coluna 'quantidade_estoque' já existe, pulando.")
        else:
            print(f"  - Aviso ao adicionar coluna em 'produto': {e}")
        db.session.rollback()
    print("Migração de produtos concluída.")

# NOVO COMANDO DE TERMINAL PARA ATUALIZAR A TABELA DE PRODUTOS COM CAMPOS FISCAIS
@app.cli.command("migrate-produtos-fiscais")
def migrate_produtos_fiscais_command():
    """Adiciona colunas fiscais à tabela de produtos."""
    print("Iniciando migração fiscal da tabela de produtos...")
    colunas = {
        'sku': 'TEXT', 'ncm': 'TEXT', 'cest': 'TEXT', 
        'origem': 'TEXT', 'unidade_medida': 'TEXT'
    }
    for nome, tipo in colunas.items():
        try:
            comando_sql = text(f'ALTER TABLE produto ADD COLUMN {nome} {tipo}')
            db.session.execute(comando_sql)
            db.session.commit()
            print(f"  - Coluna '{nome}' adicionada com sucesso.")
        except Exception as e:
            if "duplicate column name" in str(e):
                print(f"  - Coluna '{nome}' já existe, pulando.")
            else:
                print(f"  - Aviso ao adicionar coluna '{nome}': {e}")
            db.session.rollback()
    print("Migração fiscal de produtos concluída.")

# Rota para a LISTA de produtos e estoque (antiga gerenciar_estoque)
@app.route('/estoque')
@login_required
def estoque():
    produtos = Produto.query.order_by(Produto.descricao).all()
    return render_template('estoque.html', produtos=produtos)

# Rota para EDITAR um produto existente
@app.route('/produtos/editar/<int:produto_id>', methods=['GET', 'POST'])
@login_required
def editar_produto(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    if request.method == 'POST':
        try:
            produto.descricao = request.form['descricao'].upper()
            produto.ncm = request.form.get('ncm')
            produto.cest = request.form.get('cest')
            produto.origem = request.form.get('origem')
            produto.unidade_medida = request.form.get('unidade_medida', 'UN').upper()
            produto.valor_custo = float(request.form.get('valor_custo', 0))
            produto.margem_lucro = float(request.form.get('margem_lucro', 0))
            produto.valor_venda = produto.valor_custo * (1 + (produto.margem_lucro / 100))
            
            db.session.commit()
            flash('Produto atualizado com sucesso!', 'success')
            return redirect(url_for('estoque'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro ao atualizar o produto: {e}', 'danger')
    
    # GET: Mostra a página de edição com os dados do produto
    return render_template('editar_produto.html', produto=produto)

# Rota para DELETAR um produto (com verificação de movimentação)
@app.route('/produtos/deletar/<int:produto_id>', methods=['POST'])
@login_required
def deletar_produto(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    
    # VERIFICA SE HOUVE ENTRADA DO PRODUTO NO ESTOQUE
    movimento_entrada = EntradaEstoqueItem.query.filter_by(produto_id=produto.id).first()
    
    # VERIFICA SE O PRODUTO FOI USADO EM ALGUMA O.S.
    # (Baseado na descrição, como está atualmente no modelo Peca)
    movimento_saida = Peca.query.filter_by(descricao=produto.descricao).first()

    # Se encontrou qualquer movimentação, bloqueia a exclusão
    if movimento_entrada or movimento_saida:
        flash(f'Não é possível excluir o produto "{produto.descricao}", pois ele já possui movimentações de estoque ou foi usado em Ordens de Serviço.', 'danger')
        return redirect(url_for('estoque'))

    # Se não houver movimentações, prossegue com a exclusão
    try:
        db.session.delete(produto)
        db.session.commit()
        flash(f'Produto "{produto.descricao}" deletado com sucesso.', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao deletar o produto: {e}', 'danger')
    
    return redirect(url_for('estoque'))

# Rota para a tela de ENTRADA DE ESTOQUE
@app.route('/estoque/entrada', methods=['GET', 'POST'])
@login_required
def entrada_estoque():
    if request.method == 'POST':
        try:
            # Pega os dados do cabeçalho da entrada
            fornecedor_id = request.form.get('fornecedor_id') if request.form.get('fornecedor_id') else None
            nova_entrada = EntradaEstoque(
                data_entrada=datetime.datetime.strptime(request.form['data_entrada'], '%Y-%m-%d').date(),
                fornecedor_id=fornecedor_id,
                observacao=request.form.get('observacao', '').upper()
            )
            db.session.add(nova_entrada)
            
            # Pega os dados de cada item da nota
            produtos_ids = request.form.getlist('produto_id[]')
            quantidades = request.form.getlist('quantidade[]')
            custos = request.form.getlist('custo[]')

            for i in range(len(produtos_ids)):
                produto_id = int(produtos_ids[i])
                quantidade = int(quantidades[i])
                custo = float(custos[i])
                
                # Adiciona o item à entrada de estoque
                item = EntradaEstoqueItem(
                    entrada=nova_entrada,
                    produto_id=produto_id,
                    quantidade=quantidade,
                    valor_custo_unitario=custo
                )
                db.session.add(item)
                
                # ATUALIZA O ESTOQUE DO PRODUTO
                produto = Produto.query.get(produto_id)
                produto.quantidade_estoque += quantidade
                # Opcional: Atualiza o valor de custo do produto com o da última compra
                produto.valor_custo = custo

            db.session.commit()
            flash('Entrada de estoque registrada com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro ao registrar a entrada: {e}', 'danger')
        
        return redirect(url_for('estoque'))

    # Lógica GET para exibir o formulário
    fornecedores = Fornecedor.query.order_by(Fornecedor.razao_social).all()
    produtos = Produto.query.order_by(Produto.descricao).all()
    # CORREÇÃO APLICADA AQUI
    return render_template('entrada_estoque.html', 
                           fornecedores=fornecedores, 
                           produtos=produtos, 
                           today_date=datetime.date.today())

# Rota para o RELATÓRIO DE FLUXO DE CAIXA
@app.route('/relatorio/fluxo-caixa')
@login_required
def relatorio_fluxo_caixa():
    # Pega os filtros de data da URL
    data_inicio_str = request.args.get('data_inicio')
    data_fim_str = request.args.get('data_fim')

    # Converte as strings de data para objetos date, se existirem
    data_inicio = datetime.datetime.strptime(data_inicio_str, '%Y-%m-%d').date() if data_inicio_str else None
    data_fim = datetime.datetime.strptime(data_fim_str, '%Y-%m-%d').date() if data_fim_str else None

    # Busca todas as contas a receber pendentes
    query_receber = Pagamento.query.filter(Pagamento.status == 'Pendente')
    if data_inicio:
        query_receber = query_receber.filter(Pagamento.data_vencimento >= data_inicio)
    if data_fim:
        query_receber = query_receber.filter(Pagamento.data_vencimento <= data_fim)
    contas_a_receber = query_receber.all()

    # Busca todas as contas a pagar pendentes
    query_pagar = ContaPagar.query.filter(ContaPagar.status == 'Pendente')
    if data_inicio:
        query_pagar = query_pagar.filter(ContaPagar.data_vencimento >= data_inicio)
    if data_fim:
        query_pagar = query_pagar.filter(ContaPagar.data_vencimento <= data_fim)
    contas_a_pagar = query_pagar.all()

    # Junta as duas listas em uma só
    lancamentos = []
    for conta in contas_a_receber:
        lancamentos.append({
            'data': conta.data_vencimento,
            'descricao': f"Recebimento Fatura #{conta.faturamento.id}",
            'entrada': conta.valor,
            'saida': 0
        })
    for conta in contas_a_pagar:
        lancamentos.append({
            'data': conta.data_vencimento,
            'descricao': conta.descricao,
            'entrada': 0,
            'saida': conta.valor
        })

    # Ordena a lista unificada por data
    lancamentos.sort(key=lambda x: x['data'])

    # Calcula o saldo corrente
    saldo = 0
    for lancamento in lancamentos:
        saldo += lancamento['entrada'] - lancamento['saida']
        lancamento['saldo'] = saldo

    return render_template('fluxo_caixa.html', 
                           lancamentos=lancamentos,
                           data_inicio=data_inicio_str,
                           data_fim=data_fim_str)

# Rota para o RELATÓRIO DE FATURAMENTO POR CLIENTE
@app.route('/relatorio/faturamento-por-cliente')
@login_required
def relatorio_faturamento_cliente():
    data_inicio_str = request.args.get('data_inicio')
    data_fim_str = request.args.get('data_fim')

    data_inicio = datetime.datetime.strptime(data_inicio_str, '%Y-%m-%d').date() if data_inicio_str else None
    data_fim = datetime.datetime.strptime(data_fim_str, '%Y-%m-%d').date() if data_fim_str else None

    # Inicia a consulta base
    query = db.session.query(
        Cliente,
        func.count(Faturamento.id).label('num_faturas'),
        func.sum(Pagamento.valor).label('total_faturado')
    ).join(Faturamento, Faturamento.cliente_id == Cliente.id)\
     .join(Pagamento, Pagamento.faturamento_id == Faturamento.id)

    # Aplica os filtros de data
    if data_inicio:
        query = query.filter(Faturamento.data_emissao >= data_inicio)
    if data_fim:
        query = query.filter(Faturamento.data_emissao <= data_fim)

    # Agrupa por cliente e ordena pelo maior faturamento
    faturamento_por_cliente = query.group_by(Cliente.id).order_by(desc('total_faturado')).all()

    return render_template('relatorio_faturamento_cliente.html',
                           faturamento_por_cliente=faturamento_por_cliente,
                           data_inicio=data_inicio_str,
                           data_fim=data_fim_str)

# --- Inicialização ---
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0')