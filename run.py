# run.py

from app import criar_app, db, bcrypt
from app.modelos import Usuario

# Cria a aplicação chamando a nossa função de fábrica
app = criar_app()

# --- COMANDO CUSTOMIZADO PARA O TERMINAL ---
@app.cli.command("criar_db")
def criar_banco_de_dados():
    """Cria as tabelas do banco de dados e o usuário admin."""
    with app.app_context():
        print("Criando tabelas...")
        db.create_all()
        print("Tabelas criadas com sucesso.")

        # Verifica se o admin já existe
        usuario_existente = Usuario.query.filter_by(nome_usuario='Administrador').first()
        if not usuario_existente:
            senha_hash = bcrypt.generate_password_hash('admin123').decode('utf-8')
            admin = Usuario(nome_usuario='Administrador', senha_hash=senha_hash)
            db.session.add(admin)
            db.session.commit()
            print("Usuário 'Administrador' criado.")
        else:
            print("Usuário 'Administrador' já existe.")
# -----------------------------------------

# Executa o servidor de desenvolvimento
if __name__ == '__main__':
    app.run(debug=True)