# criar_db.py

# Importamos tudo o que precisamos do nosso arquivo principal app.py
from run import app, db, bcrypt, Usuario

# Empurramos o contexto da aplicação para o script
with app.app_context():
    print("Criando o banco de dados e as tabelas...")
    # Cria todas as tabelas definidas nos modelos (no nosso caso, a tabela Usuario)
    db.create_all()
    print("Tabelas criadas com sucesso.")

    # --- Criação do usuário Administrador ---
    
    # Primeiro, verificamos se o usuário já não existe
    usuario_existente = Usuario.query.filter_by(nome_usuario='Administrador').first()

    if not usuario_existente:
        # Criptografamos a senha que será usada
        senha_hash = bcrypt.generate_password_hash('admin123').decode('utf-8')
        
        # Criamos o objeto do novo usuário
        admin = Usuario(nome_usuario='Administrador', senha_hash=senha_hash)
        
        # Adicionamos o novo usuário à sessão do banco de dados
        db.session.add(admin)
        
        # Comitamos (salvamos) as mudanças no banco de dados
        db.session.commit()
        
        print("Usuário 'Administrador' criado com sucesso!")
    else:
        print("Usuário 'Administrador' já existe.")