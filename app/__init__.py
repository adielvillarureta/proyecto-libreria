# app/__init__.py
import os
import sys

# Windows (cp1252) rompe los print con emojis: UTF-8 para que
# ningún print tumbe una petición.
try:
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_migrate import Migrate
from werkzeug.middleware.proxy_fix import ProxyFix
from .config import Config

# 1) Instancias GLOBALES (antes de la fábrica)
db = SQLAlchemy()
bcrypt = Bcrypt()
migrate = Migrate()


def create_app(config_class=Config):
    # 2) Crear la app
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config.from_object(config_class)

    # 2b) Confiar en cabeceras de proxy (ngrok, nginx): esquema https + dominio público
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # 2c) Carpeta de subida de imágenes de productos
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

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
    from .routes.pagos import pagos_bp
    from .routes.configuracion import configuracion_bp
    from .routes.bloqueos import bloqueos_bp
    from .routes.api import api_bp

    # 6) Registrar blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(clientes_bp)
    app.register_blueprint(productos_bp)
    app.register_blueprint(ventas_bp)
    app.register_blueprint(pedidos_bp)
    app.register_blueprint(pagos_bp)
    app.register_blueprint(configuracion_bp)
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

    # 8) Crear tablas y columnas que falten, más los ajustes por defecto
    with app.app_context():
        try:
            db.create_all()
            # db.create_all() no agrega columnas a tablas ya existentes.
            from .esquema import sincronizar_columnas
            sincronizar_columnas()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ No se pudieron crear las tablas: {e}")

        try:
            from .ajustes_pago import asegurar_defaults
            asegurar_defaults()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"⚠️ No se pudieron crear los ajustes de pago: {e}")

    # 9) Lo guardado en el panel de configuración manda sobre el .env
    try:
        from .config_sistema import aplicar_a_app
        aplicar_a_app(app)
    except Exception as e:
        print(f"⚠️ No se pudo aplicar la configuración guardada: {e}")

    return app