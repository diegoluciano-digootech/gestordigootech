# ==============================================================================
# 1. IMPORTAÇÕES E CONFIGURAÇÃO INICIAL
# ==============================================================================
import os
import io
import base64
import logging
import datetime
import pathlib
from flask import Flask, Response, jsonify, redirect, render_template, request, url_for, flash, abort, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, extract, or_, case, text, desc
from sqlalchemy.exc import IntegrityError, OperationalError
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin, LoginManager, login_user, logout_user, login_required, current_user
from weasyprint import HTML
import pandas as pd
from validate_docbr import CPF, CNPJ
import requests
from dateutil.relativedelta import relativedelta
from enum import Enum

# --- Configuração do App Flask ---
app = Flask(__name__)
app.secret_key = 'uma-chave-secreta-muito-segura'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
db = SQLAlchemy(app)

# --- Configuração do Flask-Login ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, faça o login para acessar esta página."
login_manager.login_message_category = "info"


# ==============================================================================
# 2. MODELOS DO BANCO DE DADOS (TABELAS)
# ==============================================================================

# Tabela de associação para Faturamento <-> Ordem de Serviço
faturamento_os = db.Table('faturamento_os',
    db.Column('faturamento_id', db.Integer, db.ForeignKey('faturamento.id'), primary_key=True),
    db.Column('ordem_servico_id', db.Integer, db.ForeignKey('ordem_servico.id'), primary_key=True)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

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

class Produto(db.Model):
    __tablename__ = 'produto'
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200), nullable=False, unique=True)
    sku = db.Column(db.String(50), unique=True)
    ncm = db.Column(db.String(20))
    cest = db.Column(db.String(20))
    origem = db.Column(db.String(50))
    unidade_medida = db.Column(db.String(10))
    valor_custo = db.Column(db.Float, default=0.0)
    margem_lucro = db.Column(db.Float, default=0.0)
    valor_venda = db.Column(db.Float, default=0.0)
    quantidade_estoque = db.Column(db.Integer, default=0)

class StatusOS(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), nullable=False, unique=True)
    cor = db.Column(db.String(20), default='secondary')

class OrdemServico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    problema = db.Column(db.Text, nullable=False)
    status_id = db.Column(db.Integer, db.ForeignKey('status_os.id'))
    status = db.relationship('StatusOS', backref='ordens_servico')
    data_criacao = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    data_fechamento = db.Column(db.DateTime, nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    valor_servicos = db.Column(db.Float, default=0.0)
    pecas = db.relationship('Peca', backref='ordem_servico', lazy=True, cascade="all, delete-orphan")
    @property
    def valor_pecas(self): return sum(p.valor_total for p in self.pecas)
    @property
    def valor_total(self): return self.valor_servicos + self.valor_pecas

class Peca(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False, default=1)
    valor_unitario = db.Column(db.Float, nullable=False, default=0.0)
    ordem_servico_id = db.Column(db.Integer, db.ForeignKey('ordem_servico.id'), nullable=False)
    @property
    def valor_total(self): return self.quantidade * self.valor_unitario

class Faturamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_emissao = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    data_vencimento = db.Column(db.Date, nullable=False)
    tipo_pagamento = db.Column(db.String(20), nullable=False)
    chave_pix = db.Column(db.String(100), nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    ordens = db.relationship('OrdemServico', secondary=faturamento_os, backref='faturamento', lazy='dynamic')
    cliente = db.relationship('Cliente')
    pagamentos = db.relationship('Pagamento', backref='faturamento', lazy=True, cascade="all, delete-orphan")
    @property
    def valor_total_faturado(self): return sum(os.valor_total for os in self.ordens.all())

class Pagamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    faturamento_id = db.Column(db.Integer, db.ForeignKey('faturamento.id'), nullable=False)
    tipo_pagamento = db.Column(db.String(20), nullable=False)
    valor = db.Column(db.Float, nullable=False)
    data_vencimento = db.Column(db.Date, nullable=False)
    chave_pix = db.Column(db.String(100), nullable=True)
    numero_parcelas = db.Column(db.Integer, default=1)
    status = db.Column(db.String(20), default='Pendente')

class ContaPagar(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    descricao = db.Column(db.String(200), nullable=False)
    fornecedor_id = db.Column(db.Integer, db.ForeignKey('fornecedor.id'), nullable=True)
    valor = db.Column(db.Float, nullable=False)
    data_emissao = db.Column(db.Date, nullable=False, default=datetime.date.today)
    data_vencimento = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default='Pendente')
    fornecedor = db.relationship('Fornecedor')

class EntradaEstoque(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    data_entrada = db.Column(db.Date, nullable=False, default=datetime.date.today)
    fornecedor_id = db.Column(db.Integer, db.ForeignKey('fornecedor.id'), nullable=True)
    observacao = db.Column(db.String(300))
    fornecedor = db.relationship('Fornecedor')
    itens = db.relationship('EntradaEstoqueItem', backref='entrada', cascade="all, delete-orphan")

class EntradaEstoqueItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entrada_id = db.Column(db.Integer, db.ForeignKey('entrada_estoque.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    valor_custo_unitario = db.Column(db.Float, nullable=False)
    produto = db.relationship('Produto')

class Orcamento(db.Model):
    __tablename__ = 'orcamento'
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    data_criacao = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    descricao = db.Column(db.Text)
    valor_servicos = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(20), default='Em Aberto')
    cliente = db.relationship('Cliente', backref='orcamentos')
    itens = db.relationship('OrcamentoItem', backref='orcamento', cascade="all, delete-orphan")
    @property
    def valor_produtos(self): return sum(item.valor_total for item in self.itens)
    @property
    def valor_total(self): return self.valor_servicos + self.valor_produtos

class OrcamentoItem(db.Model):
    __tablename__ = 'orcamento_item'
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    orcamento_id = db.Column(db.Integer, db.ForeignKey('orcamento.id'), nullable=False)
    produto_id = db.Column(db.Integer, db.ForeignKey('produto.id'), nullable=False)
    descricao = db.Column(db.String(200), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False)
    valor_unitario = db.Column(db.Float, nullable=False)
    produto = db.relationship('Produto')
    @property
    def valor_total(self): return self.quantidade * self.valor_unitario

# ==============================================================================
# 3. ROTAS PRINCIPAIS E DE AUTENTICAÇÃO
# ==============================================================================
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

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

@app.route('/')
@login_required
def dashboard():
    hoje = datetime.date.today()
    status_concluidos_nomes = ['FINALIZADA', 'FATURADA']
    status_concluidos = StatusOS.query.filter(StatusOS.nome.in_(status_concluidos_nomes)).all()
    status_concluidos_ids = [s.id for s in status_concluidos]
    
    ordens_finalizadas_no_mes_lista = OrdemServico.query.filter(
        OrdemServico.status_id.in_(status_concluidos_ids),
        extract('month', OrdemServico.data_criacao) == hoje.month,
        extract('year', OrdemServico.data_criacao) == hoje.year
    ).all()
    total_faturado_mes = sum(ordem.valor_total for ordem in ordens_finalizadas_no_mes_lista)
    os_finalizadas_mes = len(ordens_finalizadas_no_mes_lista)
    
    status_aberta = StatusOS.query.filter_by(nome='ABERTA').first()
    os_abertas = OrdemServico.query.filter_by(status_id=status_aberta.id).count() if status_aberta else 0
    
    ticket_medio = (total_faturado_mes / os_finalizadas_mes) if os_finalizadas_mes > 0 else 0
    
    chart_labels, chart_data = [], []
    for i in range(6):
        data_referencia = hoje - relativedelta(months=i)
        primeiro_dia_mes = data_referencia.replace(day=1)
        primeiro_dia_proximo_mes = primeiro_dia_mes + relativedelta(months=1)
        ordens_do_mes = OrdemServico.query.filter(
            OrdemServico.status_id.in_(status_concluidos_ids),
            OrdemServico.data_criacao >= primeiro_dia_mes,
            OrdemServico.data_criacao < primeiro_dia_proximo_mes
        ).all()
        faturamento_mes_total = sum(ordem.valor_total for ordem in ordens_do_mes)
        nome_mes = primeiro_dia_mes.strftime('%b/%y')
        chart_labels.append(nome_mes)
        chart_data.append(faturamento_mes_total)
    chart_labels.reverse()
    chart_data.reverse()

    return render_template('dashboard.html', 
                           total_faturado=total_faturado_mes,
                           os_abertas=os_abertas,
                           os_finalizadas_mes=os_finalizadas_mes,
                           ticket_medio=ticket_medio,
                           chart_labels=chart_labels,
                           chart_data=chart_data)


# ==============================================================================
# 4. ROTAS DE CADASTROS (CLIENTES, FORNECEDORES, ETC.)
# ==============================================================================

# --- CLIENTES ---
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

    # Lógica GET (para exibir a página)
    search_term = request.args.get('q', '')
    query = Cliente.query

    if search_term:
        doc_search_term = "".join(filter(str.isdigit, search_term))
        search_filter = or_(
            Cliente.nome.ilike(f'%{search_term}%'),
            Cliente.razao_social.ilike(f'%{search_term}%'),
            Cliente.cpf.ilike(f'%{doc_search_term}%'),
            Cliente.cnpj.ilike(f'%{doc_search_term}%'),
            Cliente.cidade.ilike(f'%{search_term}%')
        )
        query = query.filter(search_filter)
    
    # Ordena pelo nome/razão social para um resultado mais intuitivo
    ordem_inteligente = case((Cliente.nome != None, Cliente.nome), else_=Cliente.razao_social)
    todos_clientes = query.order_by(ordem_inteligente.asc()).all()
    
    return render_template('clientes.html', clientes=todos_clientes, search_term=search_term)

@app.route('/cliente/adicionar', methods=['GET', 'POST'])
@login_required
def adicionar_cliente():
    if request.method == 'POST':
        tipo_pessoa = request.form['tipo_pessoa']
        validador_cpf, validador_cnpj = CPF(), CNPJ()
        if tipo_pessoa == 'FISICA':
            cpf_raw = request.form.get('cpf', '')
            cpf_limpo = "".join(filter(str.isdigit, cpf_raw))
            if not validador_cpf.validate(cpf_limpo):
                flash('CPF inválido. Por favor, verifique o número digitado.', 'danger')
                return redirect(url_for('adicionar_cliente'))
            novo_cliente = Cliente(tipo_pessoa='FISICA', nome=request.form.get('nome', '').upper(), cpf=cpf_limpo)
        else:
            cnpj_raw = request.form.get('cnpj', '')
            cnpj_limpo = "".join(filter(str.isdigit, cnpj_raw))
            if not validador_cnpj.validate(cnpj_limpo):
                flash('CNPJ inválido. Por favor, verifique o número digitado.', 'danger')
                return redirect(url_for('adicionar_cliente'))
            novo_cliente = Cliente(
                tipo_pessoa='JURIDICA',
                razao_social=request.form.get('razao_social', '').upper(),
                cnpj=cnpj_limpo,
                inscricao_estadual="".join(filter(str.isdigit, request.form.get('inscricao_estadual', '')))
            )
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
    return render_template('adicionar_cliente.html', cliente=Cliente())

@app.route('/cliente/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    if request.method == 'POST':
        cliente.tipo_pessoa = request.form['tipo_pessoa']
        validador_cpf, validador_cnpj = CPF(), CNPJ()
        if cliente.tipo_pessoa == 'FISICA':
            cliente.nome = request.form.get('nome', '').upper()
            cliente.cpf = "".join(filter(str.isdigit, request.form.get('cpf', '')))
            if not validador_cpf.validate(cliente.cpf):
                flash('CPF inválido.', 'danger')
                return redirect(url_for('editar_cliente', id=id))
        else:
            cliente.razao_social = request.form.get('razao_social', '').upper()
            cliente.cnpj = "".join(filter(str.isdigit, request.form.get('cnpj', '')))
            cliente.inscricao_estadual = "".join(filter(str.isdigit, request.form.get('inscricao_estadual', '')))
            if not validador_cnpj.validate(cliente.cnpj):
                flash('CNPJ inválido.', 'danger')
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
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar: {e}', 'danger')
            return redirect(url_for('editar_cliente', id=id))
    return render_template('editar_cliente.html', cliente=cliente)

@app.route('/cliente/deletar/<int:id>', methods=['POST'])
@login_required
def deletar_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    if cliente.ordens:
        flash(f'Não é possível deletar "{cliente.nome_exibicao}", pois ele possui Ordens de Serviço.', 'warning')
        return redirect(url_for('gerenciar_clientes'))
    try:
        db.session.delete(cliente)
        db.session.commit()
        flash('Cliente deletado com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao deletar o cliente: {e}', 'danger')
    return redirect(url_for('gerenciar_clientes'))

@app.route('/relatorio/clientes/pdf')
@login_required
def relatorio_clientes_pdf():
    clientes = Cliente.query.order_by(Cliente.id.asc()).all()
    data_geracao = datetime.datetime.now()
    logo_data_uri = None
    try:
        project_path = pathlib.Path(__file__).parent
        logo_path = project_path / 'static' / 'images' / 'logo.png'
        with open(logo_path, 'rb') as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        logo_data_uri = f"data:image/png;base64,{encoded_string}"
    except FileNotFoundError:
        logging.warning("Arquivo logo.png não encontrado para o PDF do relatório de clientes.")

    # Certifique-se de que você tem o template 'relatorio_clientes_pdf.html' na pasta templates
    html_renderizado = render_template('relatorio_clientes_pdf.html',
                                       clientes=clientes,
                                       data_geracao=data_geracao,
                                       logo_path=logo_data_uri)
    pdf = HTML(string=html_renderizado).write_pdf()
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': 'inline; filename=relatorio_clientes.pdf'})

@app.route('/relatorio/clientes/excel')
@login_required
def relatorio_clientes_excel():
    clientes = Cliente.query.order_by(Cliente.id.asc()).all()
    dados_para_excel = []
    for c in clientes:
        dados_para_excel.append({
            'ID': c.id,
            'Nome/Razão Social': c.nome_exibicao,
            'Documento': c.documento_exibicao,
            'Telefone': c.telefone_formatado,
            'Email': c.email,
            'Cidade/UF': f"{c.cidade or ''}/{c.uf or ''}"
        })

    df = pd.DataFrame(dados_para_excel)
    output = io.BytesIO()
    # No seu app.py, a biblioteca para Excel é 'openpyxl', então vamos mantê-la
    writer = pd.ExcelWriter(output, engine='openpyxl')
    df.to_excel(writer, index=False, sheet_name='RelatorioClientes')
    # O método close() é o correto para a versão mais recente do pandas/openpyxl
    writer.close()
    output.seek(0)

    return Response(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename=relatorio_clientes.xlsx'})

# --- FORNECEDORES ---
@app.route('/fornecedores')
@login_required
def gerenciar_fornecedores():
    search_term = request.args.get('q', '')
    query = Fornecedor.query
    if search_term:
        search_filter = or_(Fornecedor.razao_social.ilike(f'%{search_term}%'), Fornecedor.nome_fantasia.ilike(f'%{search_term}%'), Fornecedor.cnpj.ilike(f'%{search_term}%'))
        query = query.filter(search_filter)
    todos_fornecedores = query.order_by(Fornecedor.razao_social).all()
    return render_template('fornecedores.html', fornecedores=todos_fornecedores, search_term=search_term)

@app.route('/fornecedor/adicionar', methods=['GET', 'POST'])
@login_required
def adicionar_fornecedor():
    if request.method == 'POST':
        validador_cnpj = CNPJ()
        cnpj_limpo = "".join(filter(str.isdigit, request.form.get('cnpj', '')))
        if cnpj_limpo and not validador_cnpj.validate(cnpj_limpo):
            flash('CNPJ inválido.', 'danger')
            return redirect(url_for('adicionar_fornecedor'))
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
    return render_template('adicionar_fornecedor.html', fornecedor=Fornecedor())

@app.route('/fornecedor/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_fornecedor(id):
    fornecedor = Fornecedor.query.get_or_404(id)
    if request.method == 'POST':
        try:
            fornecedor.razao_social = request.form.get('razao_social', '').upper()
            fornecedor.nome_fantasia = request.form.get('nome_fantasia', '').upper()
            fornecedor.cnpj = "".join(filter(str.isdigit, request.form.get('cnpj', '')))
            fornecedor.telefone = "".join(filter(str.isdigit, request.form.get('telefone', '')))
            fornecedor.email = request.form.get('email')
            fornecedor.cep = "".join(filter(str.isdigit, request.form.get('cep', '')))
            fornecedor.rua = request.form.get('rua', '').upper()
            fornecedor.numero = request.form.get('numero')
            fornecedor.bairro = request.form.get('bairro', '').upper()
            fornecedor.cidade = request.form.get('cidade', '').upper()
            fornecedor.uf = request.form.get('uf', '').upper()
            db.session.commit()
            flash('Fornecedor atualizado com sucesso!', 'success')
            return redirect(url_for('gerenciar_fornecedores'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro ao atualizar o fornecedor: {e}', 'danger')
    return render_template('editar_fornecedor.html', fornecedor=fornecedor)

@app.route('/fornecedor/deletar/<int:id>', methods=['POST'])
@login_required
def deletar_fornecedor(id):
    fornecedor = Fornecedor.query.get_or_404(id)
    conta_vinculada = ContaPagar.query.filter_by(fornecedor_id=id).first()
    if conta_vinculada:
        flash(f'Não é possível excluir "{fornecedor.razao_social}", pois ele está vinculado a contas a pagar.', 'danger')
        return redirect(url_for('gerenciar_fornecedores'))
    try:
        db.session.delete(fornecedor)
        db.session.commit()
        flash(f'Fornecedor "{fornecedor.razao_social}" deletado com sucesso.', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao deletar o fornecedor: {e}', 'danger')
    return redirect(url_for('gerenciar_fornecedores'))

# --- PRODUTOS ---
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
    return render_template('adicionar_produto.html', produto=Produto())

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
    return render_template('editar_produto.html', produto=produto)

@app.route('/produtos/deletar/<int:produto_id>', methods=['POST'])
@login_required
def deletar_produto(produto_id):
    produto = Produto.query.get_or_404(produto_id)
    movimento_entrada = EntradaEstoqueItem.query.filter_by(produto_id=produto.id).first()
    movimento_saida = Peca.query.filter_by(descricao=produto.descricao).first()
    if movimento_entrada or movimento_saida:
        flash(f'Não é possível excluir o produto "{produto.descricao}", pois ele já possui movimentações.', 'danger')
        return redirect(url_for('estoque'))
    try:
        db.session.delete(produto)
        db.session.commit()
        flash(f'Produto "{produto.descricao}" deletado com sucesso.', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao deletar o produto: {e}', 'danger')
    return redirect(url_for('estoque'))

# --- STATUS DA O.S. ---
@app.route('/cadastros/status-os', methods=['GET', 'POST'])
@login_required
def gerenciar_status_os():
    if request.method == 'POST':
        novo_status = StatusOS(nome=request.form['nome'].upper(), cor=request.form['cor'])
        try:
            db.session.add(novo_status)
            db.session.commit()
            flash(f'Status "{novo_status.nome}" criado com sucesso!', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('Erro: Já existe um status com este nome.', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro: {e}', 'danger')
        return redirect(url_for('gerenciar_status_os'))
    status_cadastrados = StatusOS.query.all()
    return render_template('status_os.html', status_cadastrados=status_cadastrados)

@app.route('/cadastros/status-os/deletar/<int:id>', methods=['POST'])
@login_required
def deletar_status_os(id):
    status_para_deletar = StatusOS.query.get_or_404(id)
    try:
        db.session.delete(status_para_deletar)
        db.session.commit()
        flash('Status deletado com sucesso.', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao deletar o status: {e}', 'danger')
    return redirect(url_for('gerenciar_status_os'))


# ==============================================================================
# 5. ROTAS DE MOVIMENTAÇÃO (O.S., ESTOQUE, ORÇAMENTOS)
# ==============================================================================

# --- ESTOQUE ---
@app.route('/estoque')
@login_required
def estoque():
    produtos = Produto.query.order_by(Produto.descricao).all()
    return render_template('estoque.html', produtos=produtos)

@app.route('/estoque/entrada', methods=['GET', 'POST'])
@login_required
def entrada_estoque():
    if request.method == 'POST':
        try:
            fornecedor_id = request.form.get('fornecedor_id') if request.form.get('fornecedor_id') else None
            nova_entrada = EntradaEstoque(
                data_entrada=datetime.datetime.strptime(request.form['data_entrada'], '%Y-%m-%d').date(),
                fornecedor_id=fornecedor_id,
                observacao=request.form.get('observacao', '').upper()
            )
            db.session.add(nova_entrada)
            produtos_ids = request.form.getlist('produto_id[]')
            quantidades = request.form.getlist('quantidade[]')
            custos = request.form.getlist('custo[]')
            for i in range(len(produtos_ids)):
                produto_id, quantidade, custo = int(produtos_ids[i]), int(quantidades[i]), float(custos[i])
                item = EntradaEstoqueItem(entrada=nova_entrada, produto_id=produto_id, quantidade=quantidade, valor_custo_unitario=custo)
                db.session.add(item)
                produto = Produto.query.get(produto_id)
                produto.quantidade_estoque += quantidade
                produto.valor_custo = custo
            db.session.commit()
            flash('Entrada de estoque registrada com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro ao registrar a entrada: {e}', 'danger')
        return redirect(url_for('estoque'))
    fornecedores = Fornecedor.query.order_by(Fornecedor.razao_social).all()
    produtos = Produto.query.order_by(Produto.descricao).all()
    return render_template('entrada_estoque.html', fornecedores=fornecedores, produtos=produtos, today_date=datetime.date.today())

# --- ORDENS DE SERVIÇO ---
@app.route('/ordens')
@login_required
def listar_ordens():
    search_term = request.args.get('q', '')
    query = OrdemServico.query
    if search_term:
        search_filter = or_(Cliente.nome.ilike(f'%{search_term}%'), OrdemServico.problema.ilike(f'%{search_term}%'))
        if search_term.isdigit(): search_filter = or_(search_filter, OrdemServico.id == int(search_term))
        query = query.filter(search_filter)
    ordens = query.order_by(OrdemServico.data_criacao.desc()).all()
    clientes = Cliente.query.order_by(Cliente.nome).all()
    return render_template('index.html', ordens=ordens, clientes=clientes, search_term=search_term)

@app.route('/os/adicionar', methods=['POST'])
@login_required
def adicionar_os():
    try:
        status_aberta = StatusOS.query.filter(func.upper(StatusOS.nome) == 'ABERTA').first()
        if not status_aberta:
            flash('Status "ABERTA" não encontrado. Crie-o no cadastro de status.', 'danger')
            return redirect(url_for('listar_ordens'))
        nova_os = OrdemServico(
            cliente_id=request.form['cliente_id'],
            problema=request.form['problema'].upper(),
            status_id=status_aberta.id
        )
        if request.form.get('data_criacao'):
            nova_os.data_criacao = datetime.datetime.fromisoformat(request.form.get('data_criacao'))
        db.session.add(nova_os)
        db.session.commit()
        flash('Ordem de Serviço criada com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao criar a Ordem de Serviço: {e}', 'danger')
    return redirect(url_for('listar_ordens'))

@app.route('/os/<int:id>', methods=['GET', 'POST'])
@login_required
def detalhe_os(id):
    os = OrdemServico.query.get_or_404(id)

    if request.method == 'POST':
        os.problema = request.form['problema'].upper()
        os.valor_servicos = float(request.form.get('valor_servicos', 0) or 0)
        try:
            db.session.commit()
            flash('Ordem de Serviço atualizada com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar a Ordem de Serviço: {e}', 'danger')
        return redirect(url_for('detalhe_os', id=os.id))

    # Lógica GET atualizada para buscar os produtos
    produtos = Produto.query.order_by(Produto.descricao).all()
    return render_template('detalhe_os.html', os=os, produtos=produtos)

@app.route('/os/atualizar-status/<int:os_id>', methods=['POST'])
@login_required
def atualizar_status_os(os_id):
    os = OrdemServico.query.get_or_404(os_id)
    novo_status_id = request.form.get('status_id')
    status_finalizada = StatusOS.query.filter_by(nome='FINALIZADA').first()
    if status_finalizada and int(novo_status_id) == status_finalizada.id:
        os.data_fechamento = datetime.datetime.utcnow()
    else:
        os.data_fechamento = None
    try:
        os.status_id = novo_status_id
        db.session.commit()
        flash('Status da O.S. atualizado com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao atualizar o status: {e}', 'danger')
    return redirect(url_for('detalhe_os', id=os_id))

@app.route('/os/<int:os_id>/adicionar_peca', methods=['POST'])
@login_required
def adicionar_peca(os_id):
    os = OrdemServico.query.get_or_404(os_id)
    if os.status and os.status.nome.upper() != 'ABERTA':
        flash(f'Não é possível adicionar peças pois o status da O.S. é "{os.status.nome}".', 'warning')
        return redirect(url_for('detalhe_os', id=os_id))
    try:
        produto_id, quantidade = request.form['produto_id'], int(request.form['quantidade'])
        produto = Produto.query.get(produto_id)
        if not produto:
            flash('Produto não encontrado.', 'danger')
        elif produto.quantidade_estoque < quantidade:
            flash(f'Estoque insuficiente para "{produto.descricao}". Disponível: {produto.quantidade_estoque}', 'danger')
        else:
            nova_peca = Peca(descricao=produto.descricao, quantidade=quantidade, valor_unitario=produto.valor_venda, ordem_servico_id=os_id)
            produto.quantidade_estoque -= quantidade
            db.session.add(nova_peca)
            db.session.commit()
            flash('Peça adicionada e estoque atualizado!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao adicionar a peça: {e}', 'danger')
    return redirect(url_for('detalhe_os', id=os_id))

@app.route('/peca/deletar/<int:peca_id>')
@login_required
def deletar_peca(peca_id):
    peca = Peca.query.get_or_404(peca_id)
    os_id = peca.ordem_servico.id
    if peca.ordem_servico.status and peca.ordem_servico.status.nome.upper() != 'ABERTA':
        flash(f'Não é possível remover peças pois o status da O.S. é "{peca.ordem_servico.status.nome}".', 'warning')
        return redirect(url_for('detalhe_os', id=os_id))
    try:
        produto = Produto.query.filter_by(descricao=peca.descricao).first()
        if produto:
            produto.quantidade_estoque += peca.quantidade
        db.session.delete(peca)
        db.session.commit()
        flash('Peça removida e estoque estornado!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao remover a peça: {e}', 'danger')
    return redirect(url_for('detalhe_os', id=os_id))

# --- ORÇAMENTOS ---
@app.route('/orcamentos')
@login_required
def listar_orcamentos():
    orcamentos = Orcamento.query.order_by(Orcamento.data_criacao.desc()).all()
    return render_template('listar_orcamentos.html', orcamentos=orcamentos)

@app.route('/orcamentos/adicionar', methods=['GET', 'POST'])
@login_required
def adicionar_orcamento():
    if request.method == 'POST':
        try:
            novo_orcamento = Orcamento(
                cliente_id=request.form['cliente_id'],
                descricao=request.form['descricao'].upper(),
                valor_servicos=float(request.form.get('valor_servicos', 0))
            )
            db.session.add(novo_orcamento)
            db.session.commit()
            flash('Orçamento criado com sucesso! Adicione os itens.', 'success')
            return redirect(url_for('detalhe_orcamento', id=novo_orcamento.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao criar orçamento: {e}', 'danger')
    clientes = Cliente.query.order_by(Cliente.nome).all()
    return render_template('adicionar_orcamento.html', clientes=clientes)

@app.route('/orcamentos/<int:id>', methods=['GET', 'POST'])
@login_required
def detalhe_orcamento(id):
    orcamento = Orcamento.query.get_or_404(id)
    if request.method == 'POST':
        try:
            orcamento.descricao = request.form['descricao'].upper()
            orcamento.valor_servicos = float(request.form.get('valor_servicos', 0))
            db.session.commit()
            flash('Orçamento atualizado com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar orçamento: {e}', 'danger')
        return redirect(url_for('detalhe_orcamento', id=id))
    produtos = Produto.query.order_by(Produto.descricao).all()
    return render_template('detalhe_orcamento.html', orcamento=orcamento, produtos=produtos)

@app.route('/orcamentos/<int:orcamento_id>/adicionar_item', methods=['POST'])
@login_required
def adicionar_item_orcamento(orcamento_id):
    try:
        produto = Produto.query.get(request.form['produto_id'])
        novo_item = OrcamentoItem(
            orcamento_id=orcamento_id,
            produto_id=produto.id,
            descricao=produto.descricao,
            quantidade=int(request.form['quantidade']),
            valor_unitario=produto.valor_venda
        )
        db.session.add(novo_item)
        db.session.commit()
        flash('Item adicionado ao orçamento.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao adicionar item: {e}', 'danger')
    return redirect(url_for('detalhe_orcamento', id=orcamento_id))

@app.route('/orcamentos/item/deletar/<int:item_id>')
@login_required
def deletar_item_orcamento(item_id):
    item = OrcamentoItem.query.get_or_404(item_id)
    orcamento_id = item.orcamento_id
    try:
        db.session.delete(item)
        db.session.commit()
        flash('Item removido do orçamento.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao remover item: {e}', 'danger')
    return redirect(url_for('detalhe_orcamento', id=orcamento_id))

@app.route('/orcamentos/converter/<int:id>', methods=['POST'])
@login_required
def converter_orcamento_para_os(id):
    orcamento = Orcamento.query.get_or_404(id)
    if not orcamento.itens and orcamento.valor_servicos == 0:
        flash('Não é possível converter um orçamento vazio.', 'warning')
        return redirect(url_for('detalhe_orcamento', id=id))
    try:
        status_aberta = StatusOS.query.filter(func.upper(StatusOS.nome) == 'ABERTA').first()
        if not status_aberta:
            flash('Status "ABERTA" não encontrado. Crie-o no cadastro de status.', 'danger')
            return redirect(url_for('detalhe_orcamento', id=id))
        nova_os = OrdemServico(
            cliente_id=orcamento.cliente_id,
            problema=orcamento.descricao,
            valor_servicos=orcamento.valor_servicos,
            status_id=status_aberta.id
        )
        db.session.add(nova_os)
        for item in orcamento.itens:
            peca = Peca(
                ordem_servico=nova_os,
                descricao=item.descricao,
                quantidade=item.quantidade,
                valor_unitario=item.valor_unitario
            )
            db.session.add(peca)
            produto = Produto.query.get(item.produto_id)
            if produto.quantidade_estoque < item.quantidade:
                flash(f'Atenção: Estoque insuficiente para "{produto.descricao}". Baixa não realizada.', 'warning')
            else:
                produto.quantidade_estoque -= item.quantidade
        orcamento.status = 'Aprovado'
        db.session.commit()
        flash(f'Orçamento #{id} convertido com sucesso para a O.S. #{nova_os.id}!', 'success')
        return redirect(url_for('detalhe_os', id=nova_os.id))
    except Exception as e:
        db.session.rollback()
        flash(f'Ocorreu um erro ao converter o orçamento: {e}', 'danger')
        return redirect(url_for('detalhe_orcamento', id=id))


@app.route('/orcamentos/deletar/<int:id>', methods=['POST'])
@login_required
def deletar_orcamento(id):
    orcamento = Orcamento.query.get_or_404(id)
    
    # Amarração: Não permite excluir orçamentos que já foram aprovados/convertidos
    if orcamento.status != 'Em Aberto':
        flash(f'Não é possível excluir o orçamento #{id}, pois ele já foi "{orcamento.status}".', 'danger')
        return redirect(url_for('listar_orcamentos'))

    try:
        db.session.delete(orcamento)
        db.session.commit()
        flash(f'Orçamento #{id} deletado com sucesso.', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao deletar o orçamento: {e}', 'danger')
    
    return redirect(url_for('listar_orcamentos'))

@app.route('/orcamentos/pdf/<int:id>')
@login_required
def gerar_orcamento_pdf(id):
    orcamento = Orcamento.query.get_or_404(id)
    logo_data_uri = None
    try:
        project_path = pathlib.Path(__file__).parent
        logo_path = project_path / 'static' / 'images' / 'logo.png'
        with open(logo_path, 'rb') as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
        logo_data_uri = f"data:image/png;base64,{encoded_string}"
    except FileNotFoundError:
        logging.warning("Arquivo logo.png não encontrado para o PDF do orçamento.")

    html_renderizado = render_template('orcamento_pdf_template.html', orcamento=orcamento, logo_path=logo_data_uri)
    pdf = HTML(string=html_renderizado, base_url=str(project_path)).write_pdf()
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': f'inline; filename=orcamento_{orcamento.id}.pdf'})

# ==============================================================================
# 6. ROTAS FINANCEIRAS (FATURAMENTO, CONTAS A PAGAR/RECEBER)
# ==============================================================================

# --- FATURAMENTO ---
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
            status_faturada = StatusOS.query.filter(func.upper(StatusOS.nome) == 'FATURADA').first()
            if not status_faturada:
                flash('Status "FATURADA" não encontrado. Crie-o no cadastro de status.', 'danger')
                return redirect(url_for('faturamento'))
            for os in ordens:
                os.status_id = status_faturada.id
            db.session.add(nova_fatura)
            db.session.commit()
            flash(f'Fatura #{nova_fatura.id} gerada com sucesso!', 'success')
            return redirect(url_for('relatorio_faturamento', open_pdf=nova_fatura.id))
        except Exception as e:
            db.session.rollback()
            logging.error(f"Erro ao gerar fatura: {e}")
            flash(f'Ocorreu um erro ao gerar a fatura: {e}', 'danger')
            return redirect(url_for('faturamento'))

    data_inicio_str, data_fim_str, cliente_id = request.args.get('data_inicio'), request.args.get('data_fim'), request.args.get('cliente_id', 'todos')
    status_finalizada = StatusOS.query.filter(func.upper(StatusOS.nome) == 'FINALIZADA').first()
    query = OrdemServico.query.filter(OrdemServico.status_id == status_finalizada.id) if status_finalizada else OrdemServico.query.filter(False)
    if data_inicio_str: query = query.filter(OrdemServico.data_fechamento >= datetime.datetime.strptime(data_inicio_str, '%Y-%m-%d').date())
    if data_fim_str: query = query.filter(OrdemServico.data_fechamento <= datetime.datetime.strptime(data_fim_str, '%Y-%m-%d').date())
    if cliente_id != 'todos': query = query.filter(OrdemServico.cliente_id == int(cliente_id))
    ordens_para_faturar = query.order_by(OrdemServico.data_criacao.desc()).all()
    todos_clientes = Cliente.query.order_by(Cliente.nome).all()
    return render_template('faturamento.html', ordens=ordens_para_faturar, todos_clientes=todos_clientes, data_inicio=data_inicio_str, data_fim=data_fim_str, cliente_id_filtro=cliente_id)

@app.route('/faturamento/cancelar/<int:fatura_id>', methods=['POST'])
@login_required
def cancelar_fatura(fatura_id):
    fatura = Faturamento.query.get_or_404(fatura_id)
    pagamentos_recebidos = Pagamento.query.filter_by(faturamento_id=fatura_id, status='Recebido').first()
    if pagamentos_recebidos:
        flash(f'A Fatura #{fatura_id} não pode ser cancelada pois possui pagamentos recebidos.', 'danger')
        return redirect(url_for('relatorio_faturamento'))
    try:
        status_finalizada = StatusOS.query.filter(func.upper(StatusOS.nome) == 'FINALIZADA').first()
        for os in fatura.ordens.all():
            os.status_id = status_finalizada.id if status_finalizada else None
        db.session.delete(fatura)
        db.session.commit()
        flash(f'Fatura #{fatura_id} cancelada! As O.S. foram liberadas.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao cancelar a fatura: {e}', 'danger')
    return redirect(url_for('relatorio_faturamento'))

# --- CONTAS A RECEBER ---
@app.route('/contas-a-receber')
@login_required
def gerenciar_contas_a_receber():
    contas = Pagamento.query.order_by(Pagamento.status.asc(), Pagamento.data_vencimento.asc()).all()
    return render_template('contas_a_receber.html', contas=contas, today_date=datetime.date.today())

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

# --- CONTAS A PAGAR ---
@app.route('/contas-a-pagar', methods=['GET', 'POST'])
@login_required
def gerenciar_contas_a_pagar():
    if request.method == 'POST':
        try:
            descricao = request.form['descricao'].upper()
            fornecedor_id = request.form.get('fornecedor_id') if request.form.get('fornecedor_id') else None
            valor_total = float(request.form['valor'])
            data_emissao = datetime.datetime.strptime(request.form.get('data_emissao'), '%Y-%m-%d').date() if request.form.get('data_emissao') else datetime.date.today()
            primeiro_vencimento = datetime.datetime.strptime(request.form['data_vencimento'], '%Y-%m-%d').date()
            num_parcelas = int(request.form.get('num_parcelas', 1))
            valor_parcela = round(valor_total / num_parcelas, 2)
            resto = round(valor_total - (valor_parcela * num_parcelas), 2)
            for i in range(num_parcelas):
                descricao_parcela = f"{descricao} {i+1}/{num_parcelas}" if num_parcelas > 1 else descricao
                vencimento_parcela = primeiro_vencimento + relativedelta(months=i)
                valor_final_parcela = valor_parcela + resto if i == 0 else valor_parcela
                nova_conta = ContaPagar(
                    descricao=descricao_parcela, fornecedor_id=fornecedor_id, valor=valor_final_parcela,
                    data_emissao=data_emissao, data_vencimento=vencimento_parcela, status='Pendente'
                )
                db.session.add(nova_conta)
            db.session.commit()
            flash(f'{num_parcelas} conta(s) a pagar cadastrada(s)!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Ocorreu um erro ao cadastrar a conta: {e}', 'danger')
        return redirect(url_for('gerenciar_contas_a_pagar'))
    contas = ContaPagar.query.order_by(ContaPagar.status.asc(), ContaPagar.data_vencimento.asc()).all()
    fornecedores = Fornecedor.query.order_by(Fornecedor.razao_social).all()
    return render_template('contas_a_pagar.html', contas=contas, fornecedores=fornecedores, today_date=datetime.date.today())

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

@app.route('/conta/deletar/<int:conta_id>', methods=['POST'])
@login_required
def deletar_conta_a_pagar(conta_id):
    conta = ContaPagar.query.get_or_404(conta_id)
    if conta.status == 'Pago':
        flash(f'A conta "{conta.descricao}" não pode ser excluída pois já foi paga.', 'danger')
        return redirect(url_for('gerenciar_contas_a_pagar'))
    try:
        db.session.delete(conta)
        db.session.commit()
        flash(f'Conta #{conta.id} deletada com sucesso!', 'info')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao deletar a conta: {e}', 'danger')
    return redirect(url_for('gerenciar_contas_a_pagar'))

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
    fornecedores = Fornecedor.query.order_by(Fornecedor.razao_social).all()
    return render_template('editar_conta_a_pagar.html', conta=conta, fornecedores=fornecedores)


# ==============================================================================
# 7. ROTAS DE RELATÓRIOS E EXPORTAÇÃO
# ==============================================================================
@app.route('/relatorio/os')
@login_required
def relatorio_os():
    data_inicio_str, data_fim_str = request.args.get('data_inicio'), request.args.get('data_fim')
    status_id, cliente_id = request.args.get('status_id', 'todos'), request.args.get('cliente_id', 'todos')
    query = OrdemServico.query
    if data_inicio_str: query = query.filter(OrdemServico.data_criacao >= datetime.datetime.strptime(data_inicio_str, '%Y-%m-%d').date())
    if data_fim_str: query = query.filter(OrdemServico.data_criacao < datetime.datetime.strptime(data_fim_str, '%Y-%m-%d').date() + datetime.timedelta(days=1))
    if status_id != 'todos': query = query.filter(OrdemServico.status_id == int(status_id))
    if cliente_id != 'todos': query = query.filter(OrdemServico.cliente_id == int(cliente_id))
    ordens = query.order_by(OrdemServico.data_criacao.desc()).all()
    todos_clientes = Cliente.query.order_by(Cliente.nome).all()
    status_disponiveis = StatusOS.query.all()
    return render_template('relatorio_os.html', ordens=ordens, todos_clientes=todos_clientes, status_disponiveis=status_disponiveis,
                           data_inicio=data_inicio_str, data_fim=data_fim_str, status_filtro=status_id, cliente_id_filtro=cliente_id)

@app.route('/relatorio/faturamento')
@login_required
def relatorio_faturamento():
    data_inicio_str, data_fim_str, cliente_id = request.args.get('data_inicio'), request.args.get('data_fim'), request.args.get('cliente_id', 'todos')
    query_faturas = Faturamento.query
    if data_inicio_str: query_faturas = query_faturas.filter(Faturamento.data_emissao >= datetime.datetime.strptime(data_inicio_str, '%Y-%m-%d').date())
    if data_fim_str: query_faturas = query_faturas.filter(Faturamento.data_emissao < datetime.datetime.strptime(data_fim_str, '%Y-%m-%d').date() + datetime.timedelta(days=1))
    if cliente_id != 'todos': query_faturas = query_faturas.filter(Faturamento.cliente_id == int(cliente_id))
    faturas_filtradas = query_faturas.order_by(Faturamento.id.desc()).all()
    total_servicos = sum(os.valor_servicos for f in faturas_filtradas for os in f.ordens)
    total_pecas = sum(os.valor_pecas for f in faturas_filtradas for os in f.ordens)
    faturamento_total = total_servicos + total_pecas
    num_os_finalizadas = len(set(os.id for f in faturas_filtradas for os in f.ordens))
    ticket_medio = (faturamento_total / num_os_finalizadas) if num_os_finalizadas > 0 else 0
    todos_clientes = Cliente.query.order_by(Cliente.nome).all()
    return render_template('relatorio_faturamento.html', faturas=faturas_filtradas, faturamento_total=faturamento_total,
                           total_servicos=total_servicos, total_pecas=total_pecas, num_os_finalizadas=num_os_finalizadas,
                           ticket_medio=ticket_medio, todos_clientes=todos_clientes, data_inicio=data_inicio_str,
                           data_fim=data_fim_str, cliente_id_filtro=cliente_id)

@app.route('/relatorio/faturamento-por-cliente')
@login_required
def relatorio_faturamento_cliente():
    data_inicio_str, data_fim_str = request.args.get('data_inicio'), request.args.get('data_fim')
    data_inicio = datetime.datetime.strptime(data_inicio_str, '%Y-%m-%d').date() if data_inicio_str else None
    data_fim = datetime.datetime.strptime(data_fim_str, '%Y-%m-%d').date() if data_fim_str else None
    query = db.session.query(
        Cliente, func.count(Faturamento.id).label('num_faturas'), func.sum(Pagamento.valor).label('total_faturado')
    ).join(Faturamento, Faturamento.cliente_id == Cliente.id).join(Pagamento, Pagamento.faturamento_id == Faturamento.id)
    if data_inicio: query = query.filter(Faturamento.data_emissao >= data_inicio)
    if data_fim: query = query.filter(Faturamento.data_emissao <= data_fim)
    faturamento_por_cliente = query.group_by(Cliente.id).order_by(desc('total_faturado')).all()
    return render_template('relatorio_faturamento_cliente.html', faturamento_por_cliente=faturamento_por_cliente,
                           data_inicio=data_inicio_str, data_fim=data_fim_str)

@app.route('/relatorio/fluxo-caixa')
@login_required
def relatorio_fluxo_caixa():
    data_inicio_str, data_fim_str = request.args.get('data_inicio'), request.args.get('data_fim')
    data_inicio = datetime.datetime.strptime(data_inicio_str, '%Y-%m-%d').date() if data_inicio_str else None
    data_fim = datetime.datetime.strptime(data_fim_str, '%Y-%m-%d').date() if data_fim_str else None
    query_receber = Pagamento.query.filter(Pagamento.status == 'Pendente')
    if data_inicio: query_receber = query_receber.filter(Pagamento.data_vencimento >= data_inicio)
    if data_fim: query_receber = query_receber.filter(Pagamento.data_vencimento <= data_fim)
    contas_a_receber = query_receber.all()
    query_pagar = ContaPagar.query.filter(ContaPagar.status == 'Pendente')
    if data_inicio: query_pagar = query_pagar.filter(ContaPagar.data_vencimento >= data_inicio)
    if data_fim: query_pagar = query_pagar.filter(ContaPagar.data_vencimento <= data_fim)
    contas_a_pagar = query_pagar.all()
    lancamentos = []
    for conta in contas_a_receber:
        lancamentos.append({'data': conta.data_vencimento, 'descricao': f"Recebimento Fatura #{conta.faturamento.id}", 'entrada': conta.valor, 'saida': 0})
    for conta in contas_a_pagar:
        lancamentos.append({'data': conta.data_vencimento, 'descricao': conta.descricao, 'entrada': 0, 'saida': conta.valor})
    lancamentos.sort(key=lambda x: x['data'])
    saldo = 0
    for lancamento in lancamentos:
        saldo += lancamento['entrada'] - lancamento['saida']
        lancamento['saldo'] = saldo
    return render_template('fluxo_caixa.html', lancamentos=lancamentos, data_inicio=data_inicio_str, data_fim=data_fim_str)

@app.route('/faturamento/pdf/<int:fatura_id>')
@login_required
def gerar_fatura_pdf(fatura_id):
    fatura = Faturamento.query.get_or_404(fatura_id)
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


# ==============================================================================
# 8. ROTAS DE API E UTILIDADES
# ==============================================================================
@app.route('/consulta-cnpj/<cnpj>')
@login_required
def consulta_cnpj(cnpj):
    cnpj_limpo = "".join(filter(str.isdigit, cnpj))
    if len(cnpj_limpo) != 14: return jsonify({'erro': 'CNPJ inválido'}), 400
    try:
        response = requests.get(f'https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}')
        return jsonify(response.json()) if response.status_code == 200 else jsonify({'erro': 'CNPJ não encontrado'}), 404
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao consultar BrasilAPI: {e}")
        return jsonify({'erro': 'Falha na comunicação com o serviço'}), 500

@app.route('/consulta-cep/<cep>')
@login_required
def consulta_cep(cep):
    cep_limpo = "".join(filter(str.isdigit, cep))
    if len(cep_limpo) != 8: return jsonify({'erro': 'CEP inválido'}), 400
    try:
        response = requests.get(f'https://brasilapi.com.br/api/cep/v1/{cep_limpo}')
        return jsonify(response.json()) if response.status_code == 200 else jsonify({'erro': 'CEP não encontrado'}), 404
    except requests.exceptions.RequestException as e:
        logging.error(f"Erro ao consultar BrasilAPI (CEP): {e}")
        return jsonify({'erro': 'Falha na comunicação com o serviço'}), 500


# ==============================================================================
# 9. COMANDOS DE TERMINAL (CLI) E INICIALIZAÇÃO
# ==============================================================================
@app.cli.command("create-admin")
def create_admin_command():
    import getpass
    username = input("Digite o nome de usuário do admin: ")
    password = getpass.getpass("Digite a senha do admin: ")
    user_existente = User.query.filter_by(username=username).first()
    if user_existente:
        print(f"Erro: O usuário '{username}' já existe.")
        return
    novo_admin = User(username=username.upper())
    novo_admin.set_password(password)
    db.session.add(novo_admin)
    db.session.commit()
    print(f"Administrador '{username.upper()}' criado com sucesso!")

@app.cli.command("migrate-suppliers")
def migrate_suppliers_command():
    print("Iniciando migração da tabela de fornecedores...")
    colunas = {'cep': 'TEXT', 'rua': 'TEXT', 'numero': 'TEXT', 'bairro': 'TEXT', 'cidade': 'TEXT', 'uf': 'TEXT'}
    for nome, tipo in colunas.items():
        try:
            with app.app_context():
                comando_sql = text(f'ALTER TABLE fornecedor ADD COLUMN {nome} {tipo}')
                db.session.execute(comando_sql)
                db.session.commit()
                print(f"  - Coluna '{nome}' adicionada com sucesso.")
        except OperationalError as e:
            if "duplicate column name" in str(e): print(f"  - Coluna '{nome}' já existe, pulando.")
            else: print(f"  - Erro ao adicionar coluna '{nome}': {e}"); db.session.rollback()
        except Exception as e:
            print(f"  - Um erro inesperado ocorreu: {e}"); db.session.rollback()
    print("Migração da tabela de fornecedores concluída.")

@app.cli.command("migrate-produtos")
def migrate_produtos_command():
    print("Iniciando migração da tabela de produtos...")
    try:
        comando_sql = text('ALTER TABLE produto ADD COLUMN quantidade_estoque INTEGER DEFAULT 0')
        db.session.execute(comando_sql)
        db.session.commit()
        print("  - Coluna 'quantidade_estoque' adicionada com sucesso.")
    except Exception as e:
        if "duplicate column name" in str(e): print("  - Coluna 'quantidade_estoque' já existe, pulando.")
        else: print(f"  - Aviso ao adicionar coluna em 'produto': {e}")
        db.session.rollback()
    print("Migração de produtos concluída.")

@app.cli.command("migrate-produtos-fiscais")
def migrate_produtos_fiscais_command():
    print("Iniciando migração fiscal da tabela de produtos...")
    colunas = {'sku': 'TEXT', 'ncm': 'TEXT', 'cest': 'TEXT', 'origem': 'TEXT', 'unidade_medida': 'TEXT'}
    for nome, tipo in colunas.items():
        try:
            comando_sql = text(f'ALTER TABLE produto ADD COLUMN {nome} {tipo}')
            db.session.execute(comando_sql)
            db.session.commit()
            print(f"  - Coluna '{nome}' adicionada com sucesso.")
        except Exception as e:
            if "duplicate column name" in str(e): print(f"  - Coluna '{nome}' já existe, pulando.")
            else: print(f"  - Aviso ao adicionar coluna '{nome}': {e}")
            db.session.rollback()
    print("Migração fiscal de produtos concluída.")

@app.cli.command("migrate-os-status")
def migrate_os_status_command():
    print("Iniciando migração de status da O.S....")
    try:
        comando_add_col = text('ALTER TABLE ordem_servico ADD COLUMN status_id INTEGER REFERENCES status_os(id)')
        db.session.execute(comando_add_col)
        db.session.commit()
        print("  - Coluna 'status_id' adicionada à tabela 'ordem_servico'.")
    except Exception as e:
        if "duplicate column name" in str(e): print("  - Coluna 'status_id' já existe, pulando.")
        else: print(f"  - Aviso ao adicionar coluna: {e}")
        db.session.rollback()
    with app.app_context():
        if not StatusOS.query.all():
            print("  - Criando status padrão (Aberta, Finalizada, Faturada)...")
            db.session.add_all([StatusOS(nome='ABERTA', cor='warning'), StatusOS(nome='FINALIZADA', cor='success'), StatusOS(nome='FATURADA', cor='secondary')])
            db.session.commit()
    print("Migração de status concluída.")

@app.cli.command("fix-os-status-data")
def fix_os_status_data_command():
    print("Iniciando a correção dos dados de status das Ordens de Serviço...")
    try:
        with app.app_context():
            status_map = {s.nome: s.id for s in StatusOS.query.all()}
            if not status_map:
                print("ERRO: Status padrão não encontrados."); return
            os_para_atualizar = db.session.execute(text("SELECT id, status FROM ordem_servico WHERE status_id IS NULL")).fetchall()
            if not os_para_atualizar:
                print("Nenhuma O.S. para atualizar."); return
            print(f"Encontradas {len(os_para_atualizar)} Ordens de Serviço para atualizar...")
            for os_id, old_status_str in os_para_atualizar:
                if old_status_str:
                    os_obj = OrdemServico.query.get(os_id)
                    status_nome_padrao = old_status_str.upper()
                    if status_nome_padrao in status_map:
                        os_obj.status_id = status_map[status_nome_padrao]
                        print(f"  - O.S. #{os_id} atualizada para o status '{status_nome_padrao}'")
                    else:
                        print(f"  - AVISO: Status antigo '{old_status_str}' na O.S. #{os_id} não encontrado.")
            db.session.commit()
            print("Atualização dos dados concluída!")
    except Exception as e:
        db.session.rollback()
        print(f"Ocorreu um erro durante a correção dos dados: {e}")

@app.cli.command("migrate-financeiro")
def migrate_financeiro_command():
    print("Iniciando migração financeira...")
    try:
        comando_sql = text('ALTER TABLE pagamento ADD COLUMN status TEXT DEFAULT "Pendente"')
        db.session.execute(comando_sql)
        db.session.commit()
        print("  - Coluna 'status' adicionada à tabela 'pagamento'.")
    except Exception as e:
        if "duplicate column name" in str(e): print("  - Coluna 'status' já existe em 'pagamento', pulando.")
        else: print(f"  - Aviso ao adicionar coluna em 'pagamento': {e}")
        db.session.rollback()
    with app.app_context():
        db.create_all()
    print("Tabelas financeiras verificadas/criadas.")
    print("Migração financeira concluída.")

# ======================================================================
# 10. ROTAS API (JSON) PARA MOBILE
# ======================================================================

@app.route('/api/login', methods=['POST'])
def api_login_route():
    data = request.get_json()
    if not data:
        return jsonify({
    "status": "ok",
    "mensagem": "Login efetuado com sucesso!",
    "user_id": user.id,
    "username": user.username
    }), 200


    username = data.get('username')
    password = data.get('password')
    user = User.query.filter_by(username=username).first()

    if user and user.check_password(password):
        return jsonify({
            "status": "ok",
            "message": "Login efetuado com sucesso!",
            "user_id": user.id,
            "username": user.username
        }), 200
    else:
        return jsonify({"status": "error", "message": "Credenciais inválidas"}), 401

@app.route('/api/clientes', methods=['GET'])
def api_listar_clientes():
    clientes = Cliente.query.all()
    clientes_json = [
        {
            "id": c.id,
            "nome": c.nome_exibicao,
            "documento": c.documento_exibicao,
            "telefone": c.telefone_formatado,
            "email": c.email
        } for c in clientes
    ]
    return jsonify(clientes_json), 200

@app.route('/api/ordens', methods=['GET'])
def api_listar_ordens():
    ordens = OrdemServico.query.order_by(OrdemServico.data_criacao.desc()).all()
    ordens_json = [
        {
            "id": os.id,
            "cliente": os.cliente.nome_exibicao,
            "problema": os.problema,
            "status": os.status.nome if os.status else "N/A",
            "valor_total": os.valor_total,
            "data_criacao": os.data_criacao.strftime("%Y-%m-%d %H:%M:%S")
        } for os in ordens
    ]
    return jsonify(ordens_json), 200

@app.route('/api/ordens/<int:id>', methods=['GET'])
def api_detalhe_ordem(id):
    os = OrdemServico.query.get_or_404(id)
    os_json = {
        "id": os.id,
        "cliente": os.cliente.nome_exibicao,
        "problema": os.problema,
        "status": os.status.nome if os.status else "N/A",
        "valor_servicos": os.valor_servicos,
        "valor_pecas": os.valor_pecas,
        "valor_total": os.valor_total,
        "pecas": [
            {
                "descricao": p.descricao,
                "quantidade": p.quantidade,
                "valor_unitario": p.valor_unitario,
                "valor_total": p.valor_total
            } for p in os.pecas
        ]
    }
    return jsonify(os_json), 200

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0')