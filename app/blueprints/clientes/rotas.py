# app/blueprints/clientes/rotas.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from sqlalchemy import or_
from app.modelos import Cliente, Contato # Certifique-se de que seus modelos estão sendo importados
from app import db # Certifique-se de que a instância do SQLAlchemy está importada
import requests
from validate_docbr import CPF # Biblioteca para validação de CPF/CNPJ
from email_validator import validate_email, EmailNotValidError # Biblioteca para validação de email


clientes = Blueprint('clientes', __name__, template_folder='templates', url_prefix='/clientes')

@clientes.route('/')
@login_required
def listar():
    """Rota para a tela de listagem de clientes."""
    # Como o JS agora carrega os dados via API, essa rota pode retornar uma lista vazia ou todos.
    # Optamos por retornar todos inicialmente para que, se o JS falhar, o usuário ainda veja algo.
    lista_de_clientes = Cliente.query.all()
    return render_template('clientes/listar.html', clientes=lista_de_clientes)


# ----------------------------------------------------------------------
# ROTAS ESSENCIAIS PARA O FUNCIONAMENTO DAS URLS NO listar.html (LIVE SEARCH)
# ----------------------------------------------------------------------

@clientes.route('/<int:cliente_id>/editar', methods=['GET', 'POST'])
@login_required
def editar(cliente_id):
    """Rota de placeholder para a edição de cliente."""
    # IMPLEMENTAR A LÓGICA DE EDIÇÃO AQUI
    flash(f'Funcionalidade de Edição do Cliente ID: {cliente_id} pendente de implementação.', 'warning')
    return redirect(url_for('clientes.listar'))

@clientes.route('/<int:cliente_id>/deletar', methods=['POST'])
@login_required
def deletar(cliente_id):
    """Rota de placeholder para a exclusão de cliente."""
    # IMPLEMENTAR A LÓGICA DE EXCLUSÃO AQUI
    flash(f'Funcionalidade de Exclusão do Cliente ID: {cliente_id} pendente de implementação.', 'danger')
    return redirect(url_for('clientes.listar'))


# ----------------------------------------------------------------------
# ROTA DE CRIAÇÃO E VALIDAÇÃO
# ----------------------------------------------------------------------

@clientes.route('/novo', methods=['GET', 'POST'])
@login_required
def criar():
    """Rota para criar um novo cliente com validação de dados e contatos dinâmicos."""
    if request.method == 'POST':
        try:
            # 1. VALIDAÇÃO DOS CAMPOS OBRIGATÓRIOS DO CLIENTE
            dados_cliente = {
                'nome': request.form.get('nome', '').strip(),
                'documento': request.form.get('documento', '').strip(),
                'inscricao_estadual': request.form.get('inscricao_estadual', '').strip(),
                'endereco': request.form.get('endereco', '').strip(),
                'numero': request.form.get('numero', '').strip(),
                'cidade': request.form.get('cidade', '').strip(),
                'uf': request.form.get('uf', '').strip(),
                'cep': request.form.get('cep', '').strip()
            }
            
            campos_cliente_obrigatorios = ['nome', 'documento', 'endereco', 'numero', 'cidade', 'uf', 'cep']
            
            for campo in campos_cliente_obrigatorios:
                if not dados_cliente[campo]:
                    nome_amigavel = campo.replace('_', ' ').capitalize()
                    raise ValueError(f"O campo '{nome_amigavel}' do cliente é obrigatório.")

            # Validação do Documento (CPF/CNPJ)
            documento_limpo = ''.join(filter(str.isdigit, dados_cliente['documento']))
            if len(documento_limpo) == 11:
                cpf_validator = CPF()
                if not cpf_validator.validate(documento_limpo):
                    raise ValueError("O CPF informado é inválido.")
            # TODO: Adicionar validação de CNPJ se a biblioteca 'validate_docbr' suportar CNPJ também

            # 2. VALIDAÇÃO E TRATAMENTO DOS CONTATOS
            nomes_contato = request.form.getlist('contato_nome')
            emails_contato = request.form.getlist('contato_email')
            telefones_contato = request.form.getlist('contato_telefone')

            # Validação do PRIMEIRO CONTATO (índice 0) - OBRIGATÓRIO
            if (not nomes_contato or not nomes_contato[0].strip() or 
                not emails_contato[0].strip() or not telefones_contato[0].strip()):
                raise ValueError("O primeiro contato (Nome, Email e Telefone) é obrigatório e não pode estar vazio.")

            for i in range(len(nomes_contato)):
                nome = nomes_contato[i].strip()
                email = emails_contato[i].strip() if i < len(emails_contato) else ''
                telefone = telefones_contato[i].strip() if i < len(telefones_contato) else ''
                
                # Para contatos adicionais: Se o nome não estiver preenchido, ignoramos.
                if i >= 1 and not nome:
                    continue
                
                # Validação de Email (apenas se preenchido)
                if email:
                    validate_email(email) 
                
                # Validação de Telefone (apenas se preenchido)
                if telefone:
                    telefone_limpo = ''.join(filter(str.isdigit, telefone))
                    if len(telefone_limpo) not in [10, 11]:
                        raise ValueError(f"O telefone '{telefone}' é inválido. Deve ter 10 ou 11 dígitos.")

            # 3. CRIAÇÃO DO CLIENTE E CONTATOS
            novo_cliente = Cliente(
                nome=dados_cliente['nome'],
                documento=dados_cliente['documento'],
                ie=dados_cliente['inscricao_estadual'], 
                endereco=dados_cliente['endereco'],
                numero=dados_cliente['numero'],
                cidade=dados_cliente['cidade'],
                uf=dados_cliente['uf'],
                cep=dados_cliente['cep']
            )

            for i, nome_contato in enumerate(nomes_contato):
                nome_contato = nome_contato.strip()
                
                if i >= 1 and not nome_contato:
                    continue
                
                if nome_contato:
                    novo_contato = Contato(
                        nome=nome_contato,
                        email=emails_contato[i].strip(),
                        telefone=telefones_contato[i].strip()
                    )
                    novo_cliente.contatos.append(novo_contato)

            db.session.add(novo_cliente)
            db.session.commit()
            flash('Cliente e contatos cadastrados com sucesso!', 'success')
            return redirect(url_for('clientes.listar'))

        except (ValueError, EmailNotValidError) as e:
            flash(str(e), 'danger')
            return render_template('clientes/criar.html', form_data=request.form)
        except Exception as e:
            db.session.rollback()
            flash(f'Erro interno. Detalhe: {e}', 'danger')
            return render_template('clientes/criar.html', form_data=request.form)

    return render_template('clientes/criar.html', form_data={})

# ----------------------------------------------------------------------
# ROTA DE CONSULTA EXTERNA (CNPJ)
# ----------------------------------------------------------------------

@clientes.route('/consultar-cnpj/<cnpj>')
@login_required
def consultar_cnpj(cnpj):
    """Consulta dados de CNPJ em uma API externa."""
    try:
        cnpj_limpo = ''.join(filter(str.isdigit, cnpj))
        url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            dados = response.json()
            # Mapeamento dos campos da API para os campos do formulário
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


# ----------------------------------------------------------------------
# ROTA DE API PARA LIVE SEARCH (Busca Dinâmica)
# ----------------------------------------------------------------------

@clientes.route('/api/clientes/buscar', methods=['GET'])
@login_required 
def api_buscar_clientes():
    """Endpoint de API para busca dinâmica na listagem de clientes."""
    termo = request.args.get('termo', '').strip()
    
    query = Cliente.query.order_by(Cliente.nome)
    
    if termo:
        search_pattern = f'%{termo}%'
        
        query = query.filter(
            or_(
                Cliente.nome.ilike(search_pattern),
                Cliente.documento.ilike(search_pattern)
            )
        )
    
    clientes_encontrados = query.all()

    resultado = []
    for cliente in clientes_encontrados:
        # Pega o telefone do primeiro contato (se houver)
        primeiro_contato = cliente.contatos[0] if cliente.contatos else None
        
        resultado.append({
            'id': cliente.id,
            'nome': cliente.nome,
            'documento': cliente.documento, 
            'telefone': primeiro_contato.telefone if primeiro_contato else None,
        })
    
    return jsonify(resultado)