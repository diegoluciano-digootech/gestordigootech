# app/blueprints/fornecedores/rotas.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from sqlalchemy import or_
# Importe os NOVOS modelos de Fornecedor
from app.modelos import db, Fornecedor, ContatoFornecedor 
import requests
from validate_docbr import CPF
from email_validator import validate_email, EmailNotValidError


fornecedores = Blueprint('fornecedores', __name__, template_folder='templates', url_prefix='/fornecedores')


# -----------------------------------------------------
# ROTA DE LISTAGEM
# -----------------------------------------------------
@fornecedores.route('/')
@login_required
def listar():
    lista_de_fornecedores = Fornecedor.query.all()
    # Note que o template será 'fornecedores/listar.html'
    return render_template('fornecedores/listar.html', fornecedores=lista_de_fornecedores)


# -----------------------------------------------------
# ROTA DE CRIAÇÃO (Adaptada do cliente)
# -----------------------------------------------------
@fornecedores.route('/novo', methods=['GET', 'POST'])
@login_required
def criar():
    if request.method == 'POST':
        try:
            # Lógica de validação do Cliente APLICADA ao Fornecedor
            dados_fornecedor = {
                'nome': request.form.get('nome', '').strip(),
                'documento': request.form.get('documento', '').strip(),
                'inscricao_estadual': request.form.get('inscricao_estadual', '').strip(),
                'endereco': request.form.get('endereco', '').strip(),
                'numero': request.form.get('numero', '').strip(),
                'cidade': request.form.get('cidade', '').strip(),
                'uf': request.form.get('uf', '').strip(),
                'cep': request.form.get('cep', '').strip()
            }
            
            campos_obrigatórios = ['nome', 'documento', 'endereco', 'numero', 'cidade', 'uf', 'cep']
            for campo in campos_obrigatórios:
                if not dados_fornecedor[campo]:
                    nome_amigavel = campo.replace('_', ' ').capitalize()
                    raise ValueError(f"O campo '{nome_amigavel}' do fornecedor é obrigatório.")

            # Validação Documento (simplificada)
            documento_limpo = ''.join(filter(str.isdigit, dados_fornecedor['documento']))
            if len(documento_limpo) == 11 and not CPF().validate(documento_limpo):
                 raise ValueError("O CPF informado é inválido.")

            # Validação de Contatos (a mesma lógica do cliente)
            nomes_contato = request.form.getlist('contato_nome')
            emails_contato = request.form.getlist('contato_email')
            telefones_contato = request.form.getlist('contato_telefone')

            if (not nomes_contato or not nomes_contato[0].strip() or 
                not emails_contato[0].strip() or not telefones_contato[0].strip()):
                raise ValueError("O primeiro contato (Nome, Email e Telefone) é obrigatório.")

            # Validação dos contatos adicionais... (Mantenha a lógica de validação do Cliente aqui)

            # CRIAÇÃO DO FORNECEDOR (USANDO O NOVO MODELO)
            novo_fornecedor = Fornecedor(
                nome=dados_fornecedor['nome'], documento=dados_fornecedor['documento'],
                ie=dados_fornecedor['inscricao_estadual'], endereco=dados_fornecedor['endereco'],
                numero=dados_fornecedor['numero'], cidade=dados_fornecedor['cidade'],
                uf=dados_fornecedor['uf'], cep=dados_fornecedor['cep']
            )

            # Adiciona os contatos (USANDO O NOVO MODELO ContatoFornecedor)
            for i, nome_contato in enumerate(nomes_contato):
                nome_contato = nome_contato.strip()
                if i >= 1 and not nome_contato: continue
                
                if nome_contato:
                    novo_contato = ContatoFornecedor(
                        nome=nome_contato,
                        email=emails_contato[i].strip(),
                        telefone=telefones_contato[i].strip()
                    )
                    # Note a mudança na relação: contatos_fornecedor
                    novo_fornecedor.contatos_fornecedor.append(novo_contato)

            db.session.add(novo_fornecedor)
            db.session.commit()
            flash('Fornecedor e contatos cadastrados com sucesso!', 'success')
            return redirect(url_for('fornecedores.listar'))

        except (ValueError, EmailNotValidError) as e:
            flash(str(e), 'danger')
            return render_template('fornecedores/criar.html', form_data=request.form)
        except Exception as e:
            db.session.rollback()
            flash(f'Erro interno. Detalhe: {e}', 'danger')
            return render_template('fornecedores/criar.html', form_data=request.form)

    # Note que o template será 'fornecedores/criar.html'
    return render_template('fornecedores/criar.html', form_data={})


# -----------------------------------------------------
# ROTA DE CONSULTA CNPJ (Adaptada do cliente)
# -----------------------------------------------------
@fornecedores.route('/consultar-cnpj/<cnpj>')
@login_required
def consultar_cnpj(cnpj):
    # A lógica é IDÊNTICA à do cliente
    try:
        cnpj_limpo = ''.join(filter(str.isdigit, cnpj))
        url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            dados = response.json()
            dados_mapeados = {
                'nome': dados.get('razao_social'), 'endereco': dados.get('logradouro'),
                'numero': dados.get('numero'), 'cidade': dados.get('municipio'),
                'uf': dados.get('uf'), 'cep': dados.get('cep'),
                'telefone': dados.get('ddd_telefone_1')
            }
            return jsonify(dados_mapeados)
        else:
            return jsonify({'erro': 'CNPJ não encontrado ou inválido'}), 404
    except requests.exceptions.RequestException as e:
        return jsonify({'erro': f'Erro ao acessar a API externa: {e}'}), 500


# -----------------------------------------------------
# ROTA DE API PARA LIVE SEARCH (Adaptada do cliente)
# -----------------------------------------------------
@fornecedores.route('/api/buscar', methods=['GET'])
@login_required 
def api_buscar_fornecedores():
    termo = request.args.get('termo', '').strip()
    
    # Busca na tabela de Fornecedores
    query = Fornecedor.query.order_by(Fornecedor.nome)
    
    if termo:
        search_pattern = f'%{termo}%'
        
        query = query.filter(
            or_(
                Fornecedor.nome.ilike(search_pattern),
                Fornecedor.documento.ilike(search_pattern)
            )
        )
    
    fornecedores_encontrados = query.all()

    resultado = []
    for fornecedor in fornecedores_encontrados:
        # Busca o contato na relação contatos_fornecedor
        primeiro_contato = fornecedor.contatos_fornecedor[0] if fornecedor.contatos_fornecedor else None
        
        resultado.append({
            'id': fornecedor.id,
            'nome': fornecedor.nome,
            'documento': fornecedor.documento, 
            'telefone': primeiro_contato.telefone if primeiro_contato else None,
        })
    
    return jsonify(resultado)

# -----------------------------------------------------
# ROTAS PLACEHOLDERS (Para evitar BuildError no listar.html)
# -----------------------------------------------------
@fornecedores.route('/<int:fornecedor_id>/editar', methods=['GET', 'POST'])
@login_required
def editar(fornecedor_id):
    flash(f'Edição do Fornecedor ID: {fornecedor_id} pendente.', 'warning')
    return redirect(url_for('fornecedores.listar'))

@fornecedores.route('/<int:fornecedor_id>/deletar', methods=['POST'])
@login_required
def deletar(fornecedor_id):
    flash(f'Exclusão do Fornecedor ID: {fornecedor_id} pendente.', 'danger')
    return redirect(url_for('fornecedores.listar'))