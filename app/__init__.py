# app/__init__.py
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_migrate import Migrate
from .config import Config

# 1) Instancias GLOBALES (antes de la fábrica)
db = SQLAlchemy()
bcrypt = Bcrypt()
migrate = Migrate()


def create_app(config_class=Config):
    # 2) Crear la app
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config.from_object(config_class)

    # 3) Inicializar extensiones
    db.init_app(app)
    bcrypt.init_app(app)
    migrate.init_app(app, db)

    # 4) Importar modelos (para que SQLAlchemy los conozca)
    from . import models

    # 5) Importar los blueprints AQUÍ DENTRO (no arriba del archivo)
    from .routes.main import main_bp
    from .routes.auth import auth_bp
    from .routes.clientes import clientes_bp
    from .routes.productos import productos_bp
    from .routes.ventas import ventas_bp
    from .routes.pedidos import pedidos_bp
    from .routes.bloqueos import bloqueos_bp
    from .routes.api import api_bp

    # 6) Registrar blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(clientes_bp)
    app.register_blueprint(productos_bp)
    app.register_blueprint(ventas_bp)
    app.register_blueprint(pedidos_bp)
    app.register_blueprint(bloqueos_bp)
    app.register_blueprint(api_bp)

    # 7) Context processor global (categorías en todas las plantillas)
    @app.context_processor
    def inject_categorias():
        from .models import Categoria
        try:
            categorias = Categoria.query.filter_by(activo=True).all()
            return dict(categorias=categorias)
        except Exception:
            return dict(categorias=[])

    # 8) Crear tablas si no existen (opcional)
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            print(f"⚠️ No se pudieron crear las tablas: {e}")

    return app