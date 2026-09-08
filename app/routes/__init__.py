# app/__init__.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_migrate import Migrate
from .config import Config

db = SQLAlchemy()
bcrypt = Bcrypt()
migrate = Migrate()

def create_app(config_class=Config):
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config.from_object(config_class)

    db.init_app(app)
    bcrypt.init_app(app)
    migrate.init_app(app, db)

    # Importar modelos para que SQLAlchemy los conozca
    from . import models  # <--- ESTO ES CRÍTICO

    # Registrar blueprints
    from .routes.main import main_bp
    from .routes.auth import auth_bp
    from .routes.productos import productos_bp
    from .routes.ventas import ventas_bp
    from .routes.pedidos import pedidos_bp
    from .routes.clientes import clientes_bp
    from .routes.bloqueos import bloqueos_bp
    from .routes.api import api_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(productos_bp, url_prefix='/productos')
    app.register_blueprint(ventas_bp, url_prefix='/ventas')
    app.register_blueprint(pedidos_bp, url_prefix='/pedidos')
    app.register_blueprint(clientes_bp, url_prefix='/cliente')
    app.register_blueprint(bloqueos_bp, url_prefix='/bloqueos')
    app.register_blueprint(api_bp, url_prefix='/api')

    # Context processor para categorías (inyectar en todas las plantillas)
    @app.context_processor
    def inject_categorias():
        from .models.categoria import Categoria
        categorias = Categoria.query.filter_by(activo=True).all()
        return dict(categorias=categorias)

    return app