# app/blueprints/clientes/rotas.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required
from app.modelos import Cliente, Contato
from app import db
import requests
from validate_docbr import CPF
from email_validator import validate_email, EmailNotValidError

clientes = Blueprint('clientes', __name__, template_folder='templates', url_prefix='/clientes')

@clientes.route('/')
@login_required
def listar():
    # ... (sem alterações) ...
    lista_de_clientes = Cliente.query.all()
    return render_template('clientes/listar.html', clientes=lista_de_clientes)

@clientes.route('/novo', methods=['GET', 'POST'])
@login_required
def criar():
    if request.method == 'POST':
        try:
            # Validação do Documento (CPF)
            documento_form = request.form['documento']
            documento_limpo = ''.join(filter(str.isdigit, documento_form))
            if len(documento_limpo) == 11:
                cpf_validator = CPF()
                if not cpf_validator.validate(documento_limpo):
                    raise ValueError("O CPF informado é inválido.")

            # Validação do Primeiro Contato Obrigatório
            nomes_contato = request.form.getlist('contato_nome')
            emails_contato = request.form.getlist('contato_email')
            telefones_contato = request.form.getlist('contato_telefone')

            if not nomes_contato or not nomes_contato[0] or not emails_contato[0] or not telefones_contato[0]:
                raise ValueError("O primeiro contato (Nome, Email e Telefone) é obrigatório.")

            # Validação de todos os emails preenchidos
            for email in emails_contato:
                if email:
                    validate_email(email)
            
            # --- NOVA VALIDAÇÃO DE TELEFONE ADICIONADA ---
            for telefone in telefones_contato:
                # Só valida se o campo não estiver vazio
                if telefone:
                    telefone_limpo = ''.join(filter(str.isdigit, telefone))
                    # Verifica se o número de dígitos é diferente de 10 e 11
                    if len(telefone_limpo) not in [10, 11]:
                        raise ValueError(f"O telefone '{telefone}' é inválido. Deve ter 10 dígitos (fixo) ou 11 dígitos (celular).")
            # --- FIM DA NOVA VALIDAÇÃO ---

            novo_cliente = Cliente(
                nome=request.form['nome'], documento=documento_form,
                endereco=request.form.get('endereco'), numero=request.form.get('numero'),
                cidade=request.form.get('cidade'), uf=request.form.get('uf'),
                cep=request.form.get('cep')
            )
            
            for i, nome in enumerate(nomes_contato):
                if nome:
                    novo_contato = Contato(nome=nome, email=emails_contato[i], telefone=telefones_contato[i])
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
            flash(f'Erro ao cadastrar cliente. Verifique se o documento ou email já não estão cadastrados.', 'danger')
            return render_template('clientes/criar.html', form_data=request.form)

    return render_template('clientes/criar.html', form_data={})

@clientes.route('/consultar-cnpj/<cnpj>')
@login_required
def consultar_cnpj(cnpj):
    # ... (esta função continua a mesma, sem alterações) ...
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