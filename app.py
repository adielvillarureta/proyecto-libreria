import os
import time
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.utils import secure_filename
from flask_bcrypt import Bcrypt
from flask_sqlalchemy import SQLAlchemy
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy import func, text
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

db_host = os.getenv('DB_HOST')
db_user = os.getenv('DB_USER')
db_password = os.getenv('DB_PASSWORD')
db_name = os.getenv('DB_NAME')
secret_key = os.getenv('SECRET_KEY')

# Configurar la conexión
app.config['SQLALCHEMY_DATABASE_URI'] = f"mysql+pymysql://{db_user}:{db_password}@{db_host}/{db_name}"
app.config['SECRET_KEY'] = secret_key

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "clave_secreta_segura")
app.config["TEMPLATES_AUTO_RELOAD"] = True

UPLOAD_FOLDER = "static/img/productos"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["SQLALCHEMY_DATABASE_URI"] = "mysql+pymysql://librospe:75535870@mysql-librospe.alwaysdata.net/librospe_db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"ssl": {"ssl_mode": "REQUIRED"}}}


EMAIL_HOST = "smtp-librospe.alwaysdata.net"
EMAIL_PORT = 587
EMAIL_USER = "librospe@alwaysdata.net"
EMAIL_PASSWORD = "Ventas2026!"  
EMAIL_FROM = "librospe@alwaysdata.net"


db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

class Bloqueo(db.Model):
    __tablename__ = "bloqueos"
    id = db.Column(db.Integer, primary_key=True)
    tipo_usuario = db.Column(db.Enum('sistema', 'cliente'), nullable=False)
    usuario_sistema_id = db.Column(db.Integer, db.ForeignKey("usuarios_sistema.id"), nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=True)
    motivo = db.Column(db.String(255), nullable=True)
    bloqueado_por = db.Column(db.Integer, db.ForeignKey("usuarios_sistema.id"), nullable=True)
    fecha_bloqueo = db.Column(db.DateTime, default=datetime.now)
    fecha_desbloqueo = db.Column(db.DateTime, nullable=True)
    desbloqueado_por = db.Column(db.Integer, db.ForeignKey("usuarios_sistema.id"), nullable=True)
    estado = db.Column(db.Boolean, default=True)
    permanente = db.Column(db.Boolean, default=False)
    minutos_bloqueo = db.Column(db.Integer, nullable=True)

class IntentosLogin(db.Model):
    __tablename__ = "intentos_login"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150))
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=True)  # ← NUEVO
    usuario_sistema_id = db.Column(db.Integer, db.ForeignKey("usuarios_sistema.id"), nullable=True)  # ← NUEVO
    ip = db.Column(db.String(45))
    intentos = db.Column(db.Integer, default=1)
    ultimo_intento = db.Column(db.DateTime, default=datetime.now)
    usuarios_distintos = db.Column(db.Integer, default=0)
    ips_bloqueadas = db.Column(db.DateTime, nullable=True)  
    email_bloqueado = db.Column(db.DateTime, nullable=True)
    intentos_totales = db.Column(db.Integer, default=0)  # ← NUEVO

class Proveedor(db.Model):
    __tablename__ = "proveedores"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    contacto = db.Column(db.String(20), nullable=False)
    ruc_empresa_id = db.Column(db.Integer, db.ForeignKey("ruc_empresas.id"), nullable=True)
    estado = db.Column(db.Integer, default=1)
    productos = db.relationship("Producto", back_populates="proveedor")

class Producto(db.Model):
    __tablename__ = "productos"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    cantidad = db.Column(db.Integer, default=0)
    proveedor_id = db.Column(db.Integer, db.ForeignKey("proveedores.id"), nullable=True)
    precio = db.Column(db.Numeric(10,2), default=0.0)
    imagen = db.Column(db.String(255))
    destacado = db.Column(db.Integer, default=0)
    precio_oferta = db.Column(db.Numeric(10,2), nullable=True) 
    codigo_barras = db.Column(db.String(50), nullable=True)
    id_categoria = db.Column(db.Integer, db.ForeignKey("categorias.id_categoria"), nullable=True)
    
    ventas = db.relationship("Venta", back_populates="producto")
    proveedor = db.relationship("Proveedor", back_populates="productos")
    categoria_rel = db.relationship("Categoria", back_populates="productos")  

class UsuarioSistema(db.Model):
    __tablename__ = "usuarios_sistema"
    id = db.Column(db.Integer, primary_key=True)
    correo = db.Column(db.String(150), unique=True, nullable=False)
    nombres = db.Column(db.String(100), nullable=False)
    apellidos = db.Column(db.String(100), nullable=False)
    clave = db.Column(db.String(255), nullable=False)
    estado = db.Column(db.Integer, default=1)
    rol_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    rol = db.Column(db.String(20), nullable=False)  # ← Mantener para compatibilidad
    ventas = db.relationship("Venta", back_populates="vendedor")

class Categoria(db.Model):
    __tablename__ = "categorias"
    id_categoria = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True)
    
    productos = db.relationship("Producto", back_populates="categoria_rel") 
class Venta(db.Model):
    __tablename__ = "ventas"
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)
    vendedor_id = db.Column(db.Integer, db.ForeignKey("usuarios_sistema.id"), nullable=False)
    fecha_venta = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    cantidad = db.Column(db.Integer, default=1)
    tipo_comprobante = db.Column(db.String(20), default="boleta")
    numero_comprobante = db.Column(db.String(50), nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=True)
    estado = db.Column(db.Integer, default=1)
    producto = db.relationship("Producto", back_populates="ventas")
    vendedor = db.relationship("UsuarioSistema", back_populates="ventas")
    cliente = db.relationship("Cliente", back_populates="ventas")

    @property
    def proveedor(self):
        return self.producto.proveedor

    @property
    def cliente_nombre_completo(self):
        if self.cliente_nombres and self.cliente_apellidos:
            return f"{self.cliente_nombres} {self.cliente_apellidos}"
        return self.cliente_nombres or ""

class Cliente(db.Model):
    __tablename__ = "clientes"
    id = db.Column(db.Integer, primary_key=True)
    dni = db.Column(db.String(8))
    nombres = db.Column(db.String(100), nullable=False)
    apellidos = db.Column(db.String(100), nullable=False)
    correo = db.Column(db.String(150), unique=True, nullable=False)  # ← CAMBIADO de email a correo
    telefono = db.Column(db.String(15))
    direccion = db.Column(db.Text)
    clave = db.Column(db.String(255), nullable=False)
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
    puntos = db.Column(db.Integer, default=0)
    token_recuperacion = db.Column(db.String(100), nullable=True)
    token_expiracion = db.Column(db.DateTime, nullable=True)
    estado = db.Column(db.Integer, default=1)  # ← AGREGAR campo estado
    pedidos = db.relationship("Pedido", back_populates="cliente")
    ventas = db.relationship("Venta", back_populates="cliente")
class Rol(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    estado = db.Column(db.Integer, default=1)
class Pedido(db.Model):
    __tablename__ = "pedidos"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))
    fecha_pedido = db.Column(db.DateTime, default=datetime.now)
    estado = db.Column(db.String(20), default="pendiente")
    total = db.Column(db.Float)
    direccion_entrega = db.Column(db.Text)
    tipo_entrega = db.Column(db.String(20), default="recojo")
    nota = db.Column(db.Text)
    cliente = db.relationship("Cliente", back_populates="pedidos")
    detalles = db.relationship("DetallePedido", back_populates="pedido")

class DetallePedido(db.Model):
    __tablename__ = "detalle_pedido"
    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"))
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"))
    cantidad = db.Column(db.Integer)
    precio_unitario = db.Column(db.Float)
    subtotal = db.Column(db.Float)
    pedido = db.relationship("Pedido", back_populates="detalles")
    producto = db.relationship("Producto")

class RucEmpresa(db.Model):
    __tablename__ = "ruc_empresas"
    id = db.Column(db.Integer, primary_key=True)
    ruc = db.Column(db.String(11), unique=True, nullable=False)
    razon_social = db.Column(db.String(200), nullable=False)
    direccion = db.Column(db.Text, nullable=True)


def obtener_ip_cliente():
    """Obtiene la IP real del cliente"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr

def registrar_intento_fallido(email, ip, es_cliente=False):
    """
    Registra un intento fallido de login con bloqueo progresivo:
    - 3 intentos fallidos → bloqueo temporal (10 minutos)
    - 5 intentos fallidos → bloqueo permanente (solo admin desbloquea)
    """
    ahora = datetime.now()
    
    # Verificar si el email existe
    email_existe = False
    if es_cliente:
        email_existe = Cliente.query.filter_by(correo=email).first() is not None
    else:
        email_existe = UsuarioSistema.query.filter_by(correo=email).first() is not None
    
    # Verificar bloqueo de IP
    ip_bloqueada = IntentosLogin.query.filter(
        IntentosLogin.ip == ip,
        IntentosLogin.ips_bloqueadas > ahora
    ).first()
    
    if ip_bloqueada:
        return {"bloqueado": True, "tipo": "ip", "mensaje": "IP bloqueada por 10 minutos"}
    
    # Si el email no existe, registrar intento con email inexistente
    if not email_existe:
        registro = IntentosLogin.query.filter_by(email=email).first()
        
        if not registro:
            registro = IntentosLogin(
                email=email, 
                ip=ip, 
                intentos=1, 
                ultimo_intento=ahora, 
                usuarios_distintos=0,
                intentos_totales=1
            )
            db.session.add(registro)
            db.session.commit()
            return {"bloqueado": False, "intentos_restantes": 999, "email_no_existe": True}
        
        registro.intentos += 1
        registro.intentos_totales += 1
        registro.ultimo_intento = ahora
        registro.ip = ip
        db.session.commit()
        
        emails_fallidos = IntentosLogin.query.filter(
            IntentosLogin.ip == ip,
            IntentosLogin.intentos >= 1
        ).count()
        
        if emails_fallidos >= 2 and not registro.ips_bloqueadas:
            IntentosLogin.query.filter(
                IntentosLogin.ip == ip
            ).update({IntentosLogin.ips_bloqueadas: ahora + timedelta(minutes=10)})
            db.session.commit()
            return {"bloqueado": True, "tipo": "ip", "mensaje": "IP bloqueada por 10 minutos (múltiples intentos con emails inexistentes)"}
        
        return {"bloqueado": False, "intentos_restantes": 999, "email_no_existe": True}
    
    # ==========================================
    # EL EMAIL EXISTE - PROCESAR INTENTOS
    # ==========================================
    registro = IntentosLogin.query.filter_by(email=email).first()
    
    if not registro:
        registro = IntentosLogin(
            email=email, 
            ip=ip, 
            intentos=1, 
            ultimo_intento=ahora, 
            usuarios_distintos=1,  # ← NUEVO: Primer usuario desde esta IP
            intentos_totales=1
        )
        db.session.add(registro)
        db.session.commit()
        return {"bloqueado": False, "intentos_restantes": 2, "intentos_totales": 1}
    
    # ==========================================
    # ACTUALIZAR usuarios_distintos
    # ==========================================
    # Contar cuántos emails diferentes han intentado login desde esta IP
    emails_desde_ip = db.session.execute(text("""
        SELECT COUNT(DISTINCT email) 
        FROM intentos_login 
        WHERE ip = :ip 
        AND email != :email
    """), {"ip": ip, "email": email}).scalar()
    
    # Si es un nuevo email desde esta IP, incrementar usuarios_distintos
    if emails_desde_ip > 0:
        # Verificar si este email ya existe en intentos_login para esta IP
        existe_email_ip = db.session.execute(text("""
            SELECT COUNT(*) 
            FROM intentos_login 
            WHERE ip = :ip 
            AND email = :email
        """), {"ip": ip, "email": email}).scalar()
        
        if existe_email_ip == 0:
            # Es un nuevo email desde esta IP
            registro.usuarios_distintos = emails_desde_ip + 1
        else:
            # El email ya existe, mantener el contador
            registro.usuarios_distintos = emails_desde_ip
    else:
        # Es el primer email desde esta IP
        registro.usuarios_distintos = 1
    
    # Incrementar contadores
    registro.intentos += 1
    registro.intentos_totales += 1
    registro.ultimo_intento = ahora
    registro.ip = ip
    
    # ==========================================
    # VERIFICAR BLOQUEO POR IP (múltiples usuarios distintos)
    # ==========================================
    # Si hay 2 o más usuarios distintos desde esta IP, bloquear la IP
    if registro.usuarios_distintos >= 2 and not registro.ips_bloqueadas:
        registro.ips_bloqueadas = ahora + timedelta(minutes=10)
        db.session.commit()
        return {"bloqueado": True, "tipo": "ip", "mensaje": "IP bloqueada por 10 minutos (múltiples usuarios desde la misma IP)"}
    
    # ==========================================
    # VERIFICAR BLOQUEO PERMANENTE
    # ==========================================
    # Verificar si ya está bloqueado permanentemente
    if es_cliente:
        bloqueo_permanente = db.session.execute(text("""
            SELECT id FROM bloqueos 
            WHERE cliente_id = (SELECT id FROM clientes WHERE correo = :email)
            AND tipo_usuario = 'cliente' 
            AND estado = 1 
            AND permanente = 1
        """), {"email": email}).fetchone()
    else:
        bloqueo_permanente = db.session.execute(text("""
            SELECT id FROM bloqueos 
            WHERE usuario_sistema_id = (SELECT id FROM usuarios_sistema WHERE correo = :email)
            AND tipo_usuario = 'sistema' 
            AND estado = 1 
            AND permanente = 1
        """), {"email": email}).fetchone()
    
    if bloqueo_permanente:
        db.session.commit()
        return {"bloqueado": True, "tipo": "permanente", "mensaje": "CUENTA BLOQUEADA PERMANENTEMENTE. Contacta al administrador."}
    
    # ==========================================
    # NIVEL 1: 3 INTENTOS → BLOQUEO TEMPORAL (10 min)
    # ==========================================
    if registro.intentos >= 3 and not registro.email_bloqueado:
        registro.email_bloqueado = ahora + timedelta(minutes=10)
        
        if es_cliente:
            cliente = Cliente.query.filter_by(correo=email).first()
            if cliente:
                existe_bloqueo = db.session.execute(text("""
                    SELECT id FROM bloqueos 
                    WHERE cliente_id = :cliente_id 
                    AND tipo_usuario = 'cliente' 
                    AND estado = 1
                    AND permanente = 0
                """), {"cliente_id": cliente.id}).fetchone()
                
                if not existe_bloqueo:
                    db.session.execute(text("""
                        INSERT INTO bloqueos 
                        (tipo_usuario, cliente_id, motivo, fecha_bloqueo, bloqueado_por, estado, permanente, minutos_bloqueo)
                        VALUES ('cliente', :cliente_id, :motivo, NOW(), 1, 1, 0, 10)
                    """), {
                        "cliente_id": cliente.id,
                        "motivo": "Bloqueo temporal por 3 intentos fallidos de login"
                    })
        else:
            usuario = UsuarioSistema.query.filter_by(correo=email).first()
            if usuario:
                existe_bloqueo = db.session.execute(text("""
                    SELECT id FROM bloqueos 
                    WHERE usuario_sistema_id = :usuario_id 
                    AND tipo_usuario = 'sistema' 
                    AND estado = 1
                    AND permanente = 0
                """), {"usuario_id": usuario.id}).fetchone()
                
                if not existe_bloqueo:
                    db.session.execute(text("""
                        INSERT INTO bloqueos 
                        (tipo_usuario, usuario_sistema_id, motivo, fecha_bloqueo, bloqueado_por, estado, permanente, minutos_bloqueo)
                        VALUES ('sistema', :usuario_id, :motivo, NOW(), 1, 1, 0, 10)
                    """), {
                        "usuario_id": usuario.id,
                        "motivo": "Bloqueo temporal por 3 intentos fallidos de login"
                    })
        
        db.session.commit()
        return {"bloqueado": True, "tipo": "email", "mensaje": "Correo bloqueado temporalmente por 10 minutos. 3 intentos fallidos."}
    
    # ==========================================
    # NIVEL 2: 5 INTENTOS → BLOQUEO PERMANENTE
    # ==========================================
    if registro.intentos_totales >= 5:
        registro.email_bloqueado = None
        registro.intentos = 0
        db.session.commit()
        
        if es_cliente:
            cliente = Cliente.query.filter_by(correo=email).first()
            if cliente:
                existe_permanente = db.session.execute(text("""
                    SELECT id FROM bloqueos 
                    WHERE cliente_id = :cliente_id 
                    AND tipo_usuario = 'cliente' 
                    AND estado = 1
                    AND permanente = 1
                """), {"cliente_id": cliente.id}).fetchone()
                
                if not existe_permanente:
                    db.session.execute(text("""
                        INSERT INTO bloqueos 
                        (tipo_usuario, cliente_id, motivo, fecha_bloqueo, bloqueado_por, estado, permanente)
                        VALUES ('cliente', :cliente_id, :motivo, NOW(), 1, 1, 1)
                    """), {
                        "cliente_id": cliente.id,
                        "motivo": "BLOQUEO PERMANENTE por 5 intentos fallidos de login"
                    })
        else:
            usuario = UsuarioSistema.query.filter_by(correo=email).first()
            if usuario:
                existe_permanente = db.session.execute(text("""
                    SELECT id FROM bloqueos 
                    WHERE usuario_sistema_id = :usuario_id 
                    AND tipo_usuario = 'sistema' 
                    AND estado = 1
                    AND permanente = 1
                """), {"usuario_id": usuario.id}).fetchone()
                
                if not existe_permanente:
                    db.session.execute(text("""
                        INSERT INTO bloqueos 
                        (tipo_usuario, usuario_sistema_id, motivo, fecha_bloqueo, bloqueado_por, estado, permanente)
                        VALUES ('sistema', :usuario_id, :motivo, NOW(), 1, 1, 1)
                    """), {
                        "usuario_id": usuario.id,
                        "motivo": "BLOQUEO PERMANENTE por 5 intentos fallidos de login"
                    })
        
        db.session.commit()
        return {"bloqueado": True, "tipo": "permanente", "mensaje": "CUENTA BLOQUEADA PERMANENTEMENTE por 5 intentos fallidos. Contacta al administrador."}
    
    # ==========================================
    # MENOS DE 3 INTENTOS → AÚN NO BLOQUEADO
    # ==========================================
    db.session.commit()
    
    intentos_restantes_temporales = 3 - registro.intentos
    intentos_restantes_permanentes = 5 - registro.intentos_totales
    
    return {
        "bloqueado": False, 
        "intentos_restantes": intentos_restantes_temporales if intentos_restantes_temporales > 0 else 0,
        "intentos_totales": registro.intentos_totales,
        "intentos_para_bloqueo_permanente": intentos_restantes_permanentes if intentos_restantes_permanentes > 0 else 0,
        "usuarios_distintos": registro.usuarios_distintos,
        "mensaje": f"Intento {registro.intentos_totales} de 5. {intentos_restantes_temporales} intentos para bloqueo temporal, {intentos_restantes_permanentes} para bloqueo permanente."
    }

def verificar_bloqueo_ip(ip):
    """Verifica si la IP está bloqueada"""
    ahora = datetime.now()
    bloqueado = IntentosLogin.query.filter(
        IntentosLogin.ip == ip,
        IntentosLogin.ips_bloqueadas > ahora
    ).first()
    
    if bloqueado:
        print(f"IP {ip} BLOQUEADA hasta {bloqueado.ips_bloqueadas}", flush=True)
        return True
    
    print(f"IP {ip} NO BLOQUEADA", flush=True)
    return False


def verificar_bloqueo_email(email):
    """
    Verifica si el email está bloqueado (temporal o permanentemente)
    Retorna True si está bloqueado, False si no
    """
    ahora = datetime.now()
    
    # 1. Verificar bloqueo temporal en intentos_login
    registro = IntentosLogin.query.filter_by(email=email).first()
    if registro and registro.email_bloqueado and registro.email_bloqueado > ahora:
        print(f"Email {email} BLOQUEADO TEMPORALMENTE hasta {registro.email_bloqueado}", flush=True)
        return True
    
    # 2. Verificar bloqueo permanente en tabla bloqueos
    # Primero verificar si es un cliente
    cliente = Cliente.query.filter_by(correo=email).first()
    if cliente:
        bloqueo = db.session.execute(text("""
            SELECT id FROM bloqueos 
            WHERE cliente_id = :cliente_id 
            AND tipo_usuario = 'cliente' 
            AND estado = 1 
            AND permanente = 1
        """), {"cliente_id": cliente.id}).fetchone()
        
        if bloqueo:
            print(f"Email {email} BLOQUEADO PERMANENTEMENTE (cliente)", flush=True)
            return True
    
    # Verificar si es un usuario del sistema
    usuario = UsuarioSistema.query.filter_by(correo=email).first()
    if usuario:
        bloqueo = db.session.execute(text("""
            SELECT id FROM bloqueos 
            WHERE usuario_sistema_id = :usuario_id 
            AND tipo_usuario = 'sistema' 
            AND estado = 1 
            AND permanente = 1
        """), {"usuario_id": usuario.id}).fetchone()
        
        if bloqueo:
            print(f"Email {email} BLOQUEADO PERMANENTEMENTE (usuario sistema)", flush=True)
            return True
    
    return False


def limpiar_intentos_exitosos(email, ip):
    """
    Limpia los intentos fallidos cuando el login es exitoso.
    - Resetea intentos a 0
    - Resetea intentos_totales a 0 (para que empiece de nuevo el contador)
    - Elimina bloqueos temporales
    """
    try:
        print(f"🔍 Limpiando intentos para {email}")
        
        # 1. Buscar el registro de intentos
        registro = IntentosLogin.query.filter_by(email=email).first()
        
        if registro:
            # Resetear TODO
            registro.intentos = 0
            registro.intentos_totales = 0  # ← NUEVO: Resetear también
            registro.email_bloqueado = None
            registro.ultimo_intento = datetime.now()
            db.session.commit()
            print(f"✅ Intentos y totales reseteados para {email}")
        else:
            print(f"ℹ️ No hay registro de intentos para {email}")
        
        # 2. Desactivar bloqueos temporales en tabla 'bloqueos'
        # Buscar si es cliente
        cliente = Cliente.query.filter_by(correo=email).first()
        if cliente:
            db.session.execute(text("""
                UPDATE bloqueos 
                SET estado = 0, fecha_desbloqueo = NOW() 
                WHERE cliente_id = :cliente_id 
                AND tipo_usuario = 'cliente' 
                AND permanente = 0 
                AND estado = 1
            """), {"cliente_id": cliente.id})
            db.session.commit()
            print(f"✅ Bloqueos temporales desactivados para cliente {email}")
        
        # Buscar si es usuario del sistema
        usuario = UsuarioSistema.query.filter_by(correo=email).first()
        if usuario:
            db.session.execute(text("""
                UPDATE bloqueos 
                SET estado = 0, fecha_desbloqueo = NOW() 
                WHERE usuario_sistema_id = :usuario_id 
                AND tipo_usuario = 'sistema' 
                AND permanente = 0 
                AND estado = 1
            """), {"usuario_id": usuario.id})
            db.session.commit()
            print(f"✅ Bloqueos temporales desactivados para usuario {email}")
        
        # 3. Verificar si la IP ya no tiene bloqueos activos
        ahora = datetime.now()
        emails_bloqueados = IntentosLogin.query.filter(
            IntentosLogin.ip == ip,
            IntentosLogin.email_bloqueado > ahora
        ).count()
        
        if emails_bloqueados == 0:
            IntentosLogin.query.filter_by(ip=ip).update({IntentosLogin.ips_bloqueadas: None})
            db.session.commit()
            print(f"✅ IP {ip} desbloqueada")
        
        return True
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error al limpiar intentos: {e}")
        return False

def limpiar_bloqueos_expirados():
    """Limpia bloqueos temporales que ya expiraron (no toca los permanentes)"""
    ahora = datetime.now()
    
    # Limpiar bloqueos temporales en intentos_login
    IntentosLogin.query.filter(
        IntentosLogin.email_bloqueado < ahora,
        IntentosLogin.email_bloqueado.isnot(None)
    ).update({IntentosLogin.email_bloqueado: None, IntentosLogin.intentos: 0})
    
    IntentosLogin.query.filter(
        IntentosLogin.ips_bloqueadas < ahora,
        IntentosLogin.ips_bloqueadas.isnot(None)
    ).update({IntentosLogin.ips_bloqueadas: None})
    
    # Limpiar bloqueos temporales en tabla bloqueos (NO los permanentes)
    db.session.execute(text("""
        UPDATE bloqueos 
        SET estado = 0, fecha_desbloqueo = NOW() 
        WHERE permanente = 0 
        AND estado = 1 
        AND fecha_bloqueo < DATE_SUB(NOW(), INTERVAL minutos_bloqueo MINUTE)
    """))
    
    db.session.commit()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("rol") != "administrador":
            return "Acceso denegado", 403
        return f(*args, **kwargs)
    return decorated_function

def requerir_permisos_escritura(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("rol") == "vendedor":
            return "Acceso denegado: Los vendedores solo pueden registrar ventas.", 403
        return f(*args, **kwargs)
    return decorated_function

def login_required_cliente(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "cliente_id" not in session:
            flash("Debes iniciar sesión para continuar", "warning")
            return redirect(url_for("login_cliente"))
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def generar_token_recuperacion():
    return secrets.token_urlsafe(32)

def generar_comprobante_html(venta, producto, precio, cantidad, total, vendedor_nombre=""):
    titulo = "LIBRERÍA SALESIANA DON BOSCO"
    gracias = "¡Gracias por su compra! Que Dios lo bendiga."
    if venta.tipo_comprobante == "factura":
        subtitulo = "FACTURA ELECTRÓNICA"
        documento_label = "RUC"
        documento_valor = venta.cliente_documento or "—"
        direccion_html = f"<p><strong>📍 Dirección:</strong> {venta.cliente_direccion or '—'}</p>"
    else:
        subtitulo = "BOLETA DE VENTA ELECTRÓNICA"
        documento_label = "Documento"
        documento_valor = venta.cliente_documento or "—"
        direccion_html = ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Comprobante</title></head>
<body><div style="font-family:Arial;max-width:600px;margin:auto;">
<div style="background:#007bff;color:white;padding:20px;text-align:center;">
<h2>📚 {titulo}</h2><p>{subtitulo}</p><p><strong>N° {venta.numero_comprobante}</strong></p>
</div><div style="padding:20px;">
<p><strong>�� Fecha:</strong> {venta.fecha_venta.strftime('%d/%m/%Y %H:%M')}</p>
<p><strong>👤 Cliente:</strong> {venta.cliente_nombre_completo}</p>
<p><strong>{documento_label}:</strong> {documento_valor}</p>
{direccion_html}
<hr><p><strong>🛒 Producto:</strong> {producto.nombre}</p>
<p><strong>Cantidad:</strong> {cantidad}</p>
<p><strong>Precio:</strong> S/. {precio:.2f}</p>
<p><strong>Total:</strong> S/. {total:.2f}</p>
</div><div style="background:#f8f9fa;text-align:center;padding:10px;">
<p>✨ {gracias} ✨</p>
<p>Válido como comprobante de pago</p>
</div></div></body></html>"""

def enviar_comprobante_email(destinatario, cliente_nombre, tipo_comprobante, numero_comprobante, fecha, productos, total_venta):
    """Envía el comprobante por correo electrónico usando SMTP de AlwaysData"""
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        smtp_server = EMAIL_HOST
        smtp_port = EMAIL_PORT
        smtp_user = EMAIL_USER
        smtp_password = EMAIL_PASSWORD

        if not destinatario or '@' not in destinatario:
            print(f"❌ Email inválido: {destinatario}")
            return False
        
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = destinatario
        msg['Subject'] = f"{tipo_comprobante.upper()} ELECTRÓNICA N° {numero_comprobante}"
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; }}
                .header {{ background: linear-gradient(135deg, #1e3a8a, #3b82f6); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ padding: 30px; background: #f8f9fa; }}
                .producto {{ border-bottom: 1px solid #dee2e6; padding: 12px 0; }}
                .total {{ font-size: 20px; font-weight: bold; color: #28a745; text-align: right; padding-top: 15px; margin-top: 15px; border-top: 2px solid #28a745; }}
                .footer {{ background: #e9ecef; padding: 15px; text-align: center; font-size: 12px; color: #6c757d; border-radius: 0 0 10px 10px; }}
                table {{ width: 100%; border-collapse: collapse; }}
                th {{ background: #1e3a8a; color: white; padding: 10px; }}
                td {{ padding: 8px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h2>📚 LIBRERÍA SALESIANA DON BOSCO</h2>
                <h3>{tipo_comprobante.upper()} DE VENTA ELECTRÓNICA</h3>
                <p><strong>N° {numero_comprobante}</strong></p>
            </div>
            <div class="content">
                <p><strong>📅 Fecha:</strong> {fecha.strftime('%d/%m/%Y %H:%M:%S')}</p>
                <p><strong>👤 Cliente:</strong> {cliente_nombre or 'Consumidor Final'}</p>
                
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr>
                            <th style="background: #1e3a8a; color: white; padding: 10px;">Producto</th>
                            <th style="background: #1e3a8a; color: white; padding: 10px;">Cantidad</th>
                            <th style="background: #1e3a8a; color: white; padding: 10px;">Precio Unit.</th>
                            <th style="background: #1e3a8a; color: white; padding: 10px;">Total</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        
        for p in productos:
            html += f"""
                        <tr class="producto">
                            <td style="padding: 8px;">{p['nombre']}</td>
                            <td style="padding: 8px; text-align: center;">{p['cantidad']}</td>
                            <td style="padding: 8px; text-align: right;">S/. {p['precio_unitario']:.2f}</td>
                            <td style="padding: 8px; text-align: right;">S/. {p['total']:.2f}</td>
                        </tr>
            """
        
        html += f"""
                    </tbody>
                </table>
                
                <div class="total">
                    <p><strong>TOTAL: S/. {total_venta:.2f}</strong></p>
                </div>
                
                <p style="text-align: center; margin-top: 25px;">
                    <strong>✨ ¡Gracias por su compra! ✨</strong><br>
                    <small>Este es un comprobante de venta electrónico válido</small>
                </p>
            </div>
            <div class="footer">
                <p>Librería Salesiana Don Bosco | Todos los derechos reservados</p>
                <p>📧 ventas@librospe.alwaysdata.net | 📞 (01) 123-4567</p>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html, 'html'))
        
        print(f"📧 Enviando a {destinatario}...")
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        
        print(f"✅ Correo enviado a {destinatario}")
        return True
        
    except Exception as e:
        print(f"❌ Error al enviar correo: {e}")
        return False



@app.route("/")
def inicio():
    return render_template("index.html")

# ===============================
# CONTEXT PROCESSOR - CATEGORÍAS
# ===============================

@app.context_processor
def inject_categorias():
    """Inyecta categorías en todas las plantillas"""
    try:
        categorias = Categoria.query.filter_by(activo=True).all()
        return dict(categorias=categorias)
    except:
        return dict(categorias=[])

@app.route("/login", methods=["GET", "POST"])
def login():
    try:
        ip_cliente = obtener_ip_cliente()
        limpiar_bloqueos_expirados()
        
        if verificar_bloqueo_ip(ip_cliente):
            flash("⛔ ACCESO DENEGADO: Esta IP ha sido bloqueada por múltiples intentos fallidos de diferentes usuarios. Espera 10 minutos.", "danger")
            return render_template("login.html")
        
        if request.method == "POST":
            correo = request.form.get("correo", "").strip()
            clave = request.form.get("clave", "")
            
            if not correo or not clave:
                flash("❌ Ingresa correo y contraseña", "danger")
                return render_template("login.html")
            
            if verificar_bloqueo_email(correo):
                flash("⛔ CUENTA BLOQUEADA: Has agotado tus 3 intentos. Espera 10 minutos.", "danger")
                return render_template("login.html")
            
            if verificar_bloqueo_ip(ip_cliente):
                flash("⛔ ACCESO DENEGADO: Esta IP ha sido bloqueada. Espera 10 minutos.", "danger")
                return render_template("login.html")
            
            try:
                usuario = UsuarioSistema.query.filter_by(correo=correo).first()
                
                if not usuario:
                    resultado = registrar_intento_fallido(correo, ip_cliente, es_cliente=False)
                    flash("❌ Acceso denegado. Este correo no está registrado en el sistema.", "danger")
                    if resultado.get("bloqueado") and resultado["tipo"] == "ip":
                        flash(f"⛔ {resultado['mensaje']}", "danger")
                        return redirect(url_for("login"))
                    return render_template("login.html")
                
                # ============================================
                # VERIFICAR SI EL USUARIO SISTEMA ESTÁ BLOQUEADO
                # ============================================
                # 1. Verificar bloqueo manual en tabla 'bloqueos'
                bloqueo = db.session.execute(text("""
                    SELECT id, motivo, fecha_bloqueo 
                    FROM bloqueos 
                    WHERE usuario_sistema_id = :usuario_id 
                    AND tipo_usuario = 'sistema' 
                    AND estado = 1
                """), {"usuario_id": usuario.id}).mappings().first()
                
                if bloqueo:
                    flash(f"⛔ CUENTA BLOQUEADA", "danger")
                    flash(f"📝 Motivo: {bloqueo['motivo'] or 'No especificado'}", "warning")
                    flash(f"📅 Fecha de bloqueo: {bloqueo['fecha_bloqueo'].strftime('%d/%m/%Y %H:%M') if bloqueo['fecha_bloqueo'] else 'N/A'}", "info")
                    flash("🔒 Contacta al administrador para desbloquear tu cuenta.", "warning")
                    return render_template("login.html")
                
                # 2. Verificar bloqueo automático en 'intentos_login'
                bloqueo_auto = db.session.execute(text("""
                    SELECT email_bloqueado, intentos 
                    FROM intentos_login 
                    WHERE email = :email 
                    AND email_bloqueado IS NOT NULL 
                    AND email_bloqueado > NOW()
                """), {"email": correo}).mappings().first()
                
                if bloqueo_auto:
                    flash(f"⛔ CUENTA BLOQUEADA TEMPORALMENTE", "danger")
                    flash(f"📝 Motivo: Bloqueo automático por {bloqueo_auto['intentos']} intentos fallidos de login", "warning")
                    flash(f"⏳ Tiempo restante: {(bloqueo_auto['email_bloqueado'] - datetime.now()).seconds // 60} minutos", "info")
                    flash("🔄 Espera a que se desbloquee automáticamente o contacta al administrador.", "warning")
                    return render_template("login.html")
                # ============================================
                
                if bcrypt.check_password_hash(usuario.clave, clave):
                    limpiar_intentos_exitosos(correo, ip_cliente)
                    session["usuario_id"] = usuario.id
                    session["rol"] = usuario.rol
                    session["nombre"] = usuario.nombres
                    flash(f"✅ Bienvenido {usuario.nombres}", "success")
                    return redirect(url_for("productos"))
                else:
                    resultado = registrar_intento_fallido(correo, ip_cliente, es_cliente=False)
                    if resultado.get("bloqueado"):
                        flash(f"⛔ {resultado['mensaje']}", "danger")
                        if resultado["tipo"] == "ip":
                            flash("⚠️ A partir de ahora, NINGÚN usuario podrá iniciar sesión desde esta IP durante 10 minutos.", "warning")
                            return redirect(url_for("login"))
                    else:
                        intentos = resultado.get("intentos_restantes", 0)
                        if intentos > 0 and intentos != 999:
                            flash(f"❌ Contraseña incorrecta. Te quedan {intentos} intento(s).", "danger")
                        else:
                            flash("❌ Contraseña incorrecta. Próximo intento bloqueará la cuenta.", "warning")
                    return render_template("login.html")
                    
            except Exception as e:
                print(f"❌ Error en login POST: {e}")
                import traceback
                traceback.print_exc()
                flash("❌ Error al procesar el login", "danger")
                return render_template("login.html")
        
        return render_template("login.html")
        
    except Exception as e:
        print(f"❌ ERROR EN LOGIN: {e}")
        import traceback
        traceback.print_exc()
        flash(f"❌ Error interno del servidor", "danger")
        return render_template("login.html")

@app.route("/login-cliente", methods=["GET", "POST"])
def login_cliente():
    ip_cliente = obtener_ip_cliente()
    limpiar_bloqueos_expirados()
    
    # Variables para el template
    template_data = {
        "bloqueo_permanente": None,
        "bloqueo_temporal": False,
        "minutos_restantes": 0,
        "intentos_restantes": None,
        "intentos_totales": None,
        "intentos_para_permanente": None
    }
    
    if verificar_bloqueo_ip(ip_cliente):
        flash("⛔ ACCESO DENEGADO: Esta IP ha sido bloqueada. Espera 10 minutos.", "danger")
        return render_template("login_cliente.html", **template_data)
    
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        clave = request.form.get("clave", "")
        
        if not email or not clave:
            flash("❌ Ingresa email y contraseña", "danger")
            return render_template("login_cliente.html", **template_data)
        
        # ============================================
        # VERIFICAR BLOQUEO DE EMAIL (TEMPORAL O PERMANENTE)
        # ============================================
        if verificar_bloqueo_email(email):
            cliente_tmp = Cliente.query.filter_by(correo=email).first()
            if cliente_tmp:
                bloqueo_permanente = db.session.execute(text("""
                    SELECT id, motivo, permanente 
                    FROM bloqueos 
                    WHERE cliente_id = :cliente_id 
                    AND tipo_usuario = 'cliente' 
                    AND estado = 1 
                    AND permanente = 1
                """), {"cliente_id": cliente_tmp.id}).mappings().first()
                
                if bloqueo_permanente:
                    flash("⛔ CUENTA BLOQUEADA PERMANENTEMENTE", "danger")
                    flash(f"📝 Motivo: {bloqueo_permanente['motivo'] or '5 intentos fallidos de login'}", "warning")
                    flash("🔒 Contacta al administrador para desbloquear tu cuenta.", "warning")
                    template_data["bloqueo_permanente"] = {
                        "motivo": bloqueo_permanente['motivo'] or "Has excedido el número máximo de intentos permitidos."
                    }
                else:
                    # Bloqueo temporal
                    registro = IntentosLogin.query.filter_by(email=email).first()
                    if registro and registro.email_bloqueado:
                        minutos_restantes = (registro.email_bloqueado - datetime.now()).seconds // 60
                        flash("⛔ CUENTA BLOQUEADA TEMPORALMENTE", "danger")
                        flash(f"⏳ Has agotado tus 3 intentos. Espera {minutos_restantes} minutos para volver a intentar.", "warning")
                        template_data["bloqueo_temporal"] = True
                        template_data["minutos_restantes"] = minutos_restantes
            else:
                flash("⛔ CUENTA BLOQUEADA", "danger")
                flash("⏳ Espera 10 minutos para volver a intentar.", "warning")
            
            return render_template("login_cliente.html", **template_data)
        
        if verificar_bloqueo_ip(ip_cliente):
            flash("⛔ ACCESO DENEGADO: Esta IP ha sido bloqueada. Espera 10 minutos.", "danger")
            return render_template("login_cliente.html", **template_data)
        
        cliente = Cliente.query.filter_by(correo=email).first()
        
        if not cliente:
            resultado = registrar_intento_fallido(email, ip_cliente, es_cliente=True)
            flash("❌ Este correo no está registrado. ¿Deseas crear una cuenta nueva?", "warning")
            flash("💡 Haz clic en 'Registrarme' para crear una cuenta.", "info")
            if resultado.get("bloqueado") and resultado["tipo"] == "ip":
                flash(f"⛔ {resultado['mensaje']}", "danger")
                return redirect(url_for("login_cliente"))
            return render_template("login_cliente.html", **template_data)
        
        # ============================================
        # VERIFICAR BLOQUEOS ACTIVOS DEL CLIENTE
        # ============================================
        # 1. Verificar bloqueo permanente
        bloqueo_permanente = db.session.execute(text("""
            SELECT id, motivo, permanente, fecha_bloqueo
            FROM bloqueos 
            WHERE cliente_id = :cliente_id 
            AND tipo_usuario = 'cliente' 
            AND estado = 1 
            AND permanente = 1
        """), {"cliente_id": cliente.id}).mappings().first()
        
        if bloqueo_permanente:
            flash("⛔ CUENTA BLOQUEADA PERMANENTEMENTE", "danger")
            flash(f"📝 Motivo: {bloqueo_permanente['motivo'] or '5 intentos fallidos de login'}", "warning")
            flash(f"📅 Fecha de bloqueo: {bloqueo_permanente['fecha_bloqueo'].strftime('%d/%m/%Y %H:%M') if bloqueo_permanente['fecha_bloqueo'] else 'N/A'}", "info")
            flash("🔒 Contacta al administrador para desbloquear tu cuenta.", "warning")
            template_data["bloqueo_permanente"] = {
                "motivo": bloqueo_permanente['motivo'] or "Has excedido el número máximo de intentos permitidos."
            }
            return render_template("login_cliente.html", **template_data)
        
        # 2. Verificar bloqueo temporal (debe estar en intentos_login)
        registro_intentos = IntentosLogin.query.filter_by(email=email).first()
        if registro_intentos and registro_intentos.email_bloqueado and registro_intentos.email_bloqueado > datetime.now():
            minutos_restantes = (registro_intentos.email_bloqueado - datetime.now()).seconds // 60
            flash("⛔ CUENTA BLOQUEADA TEMPORALMENTE", "danger")
            flash(f"⏳ Has agotado tus 3 intentos. Espera {minutos_restantes} minutos para volver a intentar.", "warning")
            template_data["bloqueo_temporal"] = True
            template_data["minutos_restantes"] = minutos_restantes
            return render_template("login_cliente.html", **template_data)
        
        # ============================================
        # VERIFICAR CONTRASEÑA
        # ============================================
        if bcrypt.check_password_hash(cliente.clave, clave):
            # Login exitoso - limpiar intentos
            limpiar_intentos_exitosos(email, ip_cliente)
            
            # Si tenía un bloqueo temporal en tabla bloqueos, desactivarlo
            db.session.execute(text("""
                UPDATE bloqueos 
                SET estado = 0, fecha_desbloqueo = NOW() 
                WHERE cliente_id = :cliente_id 
                AND tipo_usuario = 'cliente' 
                AND permanente = 0 
                AND estado = 1
            """), {"cliente_id": cliente.id})
            db.session.commit()
            
            session["cliente_id"] = cliente.id
            session["cliente_nombres"] = cliente.nombres
            session["cliente_apellidos"] = cliente.apellidos
            session["cliente_correo"] = cliente.correo
            session["cliente_telefono"] = cliente.telefono
            session["cliente_direccion"] = cliente.direccion
            session["cliente_dni"] = cliente.dni
            flash(f"✅ ¡Bienvenido {cliente.nombres}!", "success")
            return redirect("/catalogo")
        else:
            # ============================================
            # REGISTRAR INTENTO FALLIDO
            # ============================================
            resultado = registrar_intento_fallido(email, ip_cliente, es_cliente=True)
            
            # Actualizar template_data con los intentos
            template_data["intentos_restantes"] = resultado.get("intentos_restantes", 0)
            template_data["intentos_totales"] = resultado.get("intentos_totales", 0)
            template_data["intentos_para_permanente"] = resultado.get("intentos_para_bloqueo_permanente", 5)
            
            if resultado.get("bloqueado"):
                if resultado["tipo"] == "permanente":
                    flash("⛔ ¡CUENTA BLOQUEADA PERMANENTEMENTE!", "danger")
                    flash("📝 Motivo: 5 intentos fallidos de login", "warning")
                    flash("🔒 Contacta al administrador para desbloquear tu cuenta.", "warning")
                    template_data["bloqueo_permanente"] = {
                        "motivo": "Has excedido el número máximo de intentos permitidos (5 fallos)."
                    }
                elif resultado["tipo"] == "email":
                    flash(f"⛔ {resultado['mensaje']}", "danger")
                    flash("⏳ Espera 10 minutos antes de volver a intentar.", "warning")
                    # Verificar si hay minutos restantes
                    registro = IntentosLogin.query.filter_by(email=email).first()
                    if registro and registro.email_bloqueado:
                        minutos_restantes = (registro.email_bloqueado - datetime.now()).seconds // 60
                        template_data["bloqueo_temporal"] = True
                        template_data["minutos_restantes"] = minutos_restantes
                elif resultado["tipo"] == "ip":
                    flash(f"⛔ {resultado['mensaje']}", "danger")
                    flash("⚠️ NINGÚN cliente podrá iniciar sesión desde esta IP durante 10 minutos.", "warning")
                else:
                    flash(f"⛔ {resultado['mensaje']}", "danger")
            else:
                intentos_restantes = resultado.get("intentos_restantes", 0)
                intentos_totales = resultado.get("intentos_totales", 0)
                intentos_para_permanente = resultado.get("intentos_para_bloqueo_permanente", 5)
                
                if intentos_restantes > 0 and intentos_restantes != 999:
                    if intentos_restantes <= 1:
                        flash(f"⚠️ ¡ATENCIÓN! Contraseña incorrecta. Te queda {intentos_restantes} intento para bloqueo TEMPORAL.", "danger")
                        flash(f"💡 Si fallas 2 veces más (total {intentos_totales + 2} de 5), tu cuenta será BLOQUEADA PERMANENTEMENTE.", "warning")
                    else:
                        flash(f"❌ Contraseña incorrecta. Te quedan {intentos_restantes} intentos para bloqueo TEMPORAL.", "danger")
                        flash(f"ℹ️ Intentos totales: {intentos_totales} de 5. Si llegas a 5, tu cuenta será BLOQUEADA PERMANENTEMENTE.", "info")
                else:
                    # Mostrar información del progreso hacia bloqueo permanente
                    if intentos_totales >= 4:
                        flash(f"⚠️ ¡ÚLTIMO INTENTO! Contraseña incorrecta. Si fallas una vez más (5 de 5), tu cuenta será BLOQUEADA PERMANENTEMENTE.", "danger")
                    else:
                        flash(f"❌ Contraseña incorrecta. Próximo intento (3 de 3) bloqueará la cuenta TEMPORALMENTE por 10 minutos.", "warning")
                        flash(f"ℹ️ Intentos totales: {intentos_totales} de 5. Con 5 fallos, bloqueo PERMANENTE.", "info")
            
            return render_template("login_cliente.html", **template_data)
    
    # GET - Mostrar intentos actuales si existen
    email_cookie = request.cookies.get('email_actual')
    if email_cookie:
        registro = IntentosLogin.query.filter_by(email=email_cookie).first()
        if registro and not registro.email_bloqueado:
            template_data["intentos_restantes"] = 3 - registro.intentos
            template_data["intentos_totales"] = registro.intentos_totales
            template_data["intentos_para_permanente"] = 5 - registro.intentos_totales
    
    return render_template("login_cliente.html", **template_data)

@app.route("/bloqueos-sistema")
@login_required
def ver_bloqueos_sistema():
    if session.get("rol") != "administrador":
        flash("❌ Solo administradores pueden ver bloqueos", "danger")
        return redirect(url_for("dashboard"))
    
    try:
        # ============================================
        # 1. BLOQUEOS MANUALES DE USUARIOS SISTEMA
        # ============================================
        bloqueos_sistema = db.session.execute(text("""
            SELECT 
                b.id,
                b.usuario_sistema_id,
                b.motivo,
                b.fecha_bloqueo,
                b.bloqueado_por,
                b.estado,
                u.correo AS usuario_correo,
                u.nombres AS usuario_nombres,
                u.apellidos AS usuario_apellidos,
                u.rol AS usuario_rol,
                CONCAT(bloq.nombres, ' ', bloq.apellidos) AS bloqueado_por_nombre
            FROM bloqueos b
            LEFT JOIN usuarios_sistema u ON b.usuario_sistema_id = u.id
            LEFT JOIN usuarios_sistema bloq ON b.bloqueado_por = bloq.id
            WHERE b.tipo_usuario = 'sistema' AND b.estado = 1
            ORDER BY b.fecha_bloqueo DESC
        """)).mappings().all()
        
        # ============================================
        # 2. BLOQUEOS AUTOMÁTICOS DE USUARIOS SISTEMA
        # ============================================
        intentos_sistema = db.session.execute(text("""
            SELECT 
                i.id,
                i.email,
                i.intentos,
                i.email_bloqueado,
                i.ip,
                u.id AS usuario_id,
                u.nombres AS usuario_nombres,
                u.apellidos AS usuario_apellidos,
                u.rol AS usuario_rol
            FROM intentos_login i
            JOIN usuarios_sistema u ON i.email = u.correo
            WHERE i.email_bloqueado IS NOT NULL AND i.email_bloqueado > NOW()
            ORDER BY i.email_bloqueado DESC
        """)).mappings().all()
        
        # ============================================
        # 3. UNIFICAR
        # ============================================
        bloqueos_lista = []
        
        # Manuales
        for b in bloqueos_sistema:
            bloqueo_dict = {
                'id_bloqueo': b['id'],
                'tipo': 'Sistema',
                'nombre_completo': f"{b['usuario_nombres'] or ''} {b['usuario_apellidos'] or ''}".strip(),
                'email': b['usuario_correo'],
                'rol': b['usuario_rol'],
                'motivo': b['motivo'] or 'Sin motivo',
                'fecha_bloqueo': b['fecha_bloqueo'],
                'bloqueado_por': b['bloqueado_por_nombre'] or 'Sistema',
                'origen': 'Manual',
                'tipo_origen': 'bloqueos',
                'id_usuario': b['usuario_sistema_id']
            }
            bloqueos_lista.append(bloqueo_dict)
        
        # Automáticos
        for i in intentos_sistema:
            bloqueo_dict = {
                'id_bloqueo': i['id'],
                'tipo': 'Sistema',
                'nombre_completo': f"{i['usuario_nombres'] or ''} {i['usuario_apellidos'] or ''}".strip() or 'Desconocido',
                'email': i['email'],
                'rol': i['usuario_rol'],
                'motivo': f"Bloqueo automático por {i['intentos']} intentos fallidos de login",
                'fecha_bloqueo': i['email_bloqueado'],
                'bloqueado_por': 'Sistema',
                'origen': 'Automático',
                'tipo_origen': 'intentos_login',
                'id_usuario': i['usuario_id'],
                'ip': i['ip']
            }
            bloqueos_lista.append(bloqueo_dict)
        
        return render_template("bloqueos_sistema.html", bloqueos=bloqueos_lista)
        
    except Exception as e:
        print(f"❌ Error en bloqueos_sistema: {e}")
        flash(f"Error al cargar bloqueos: {e}", "danger")
        return render_template("bloqueos_sistema.html", bloqueos=[])

@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("✅ Sesión cerrada", "success")
    return redirect(url_for("login"))

@app.route("/usuarios/nuevo", methods=["GET", "POST"])
@login_required
@admin_required
def nuevo_usuario():
    if request.method == "POST":
        try:
            clave_hash = bcrypt.generate_password_hash("123456").decode("utf-8")
            nuevo = UsuarioSistema(
                correo=request.form["correo"],
                nombres=request.form["nombres"],
                apellidos=request.form["apellidos"],
                rol=request.form["rol"],
                clave=clave_hash,
            )
            db.session.add(nuevo)
            db.session.commit()
            flash("✅ Usuario registrado. Contraseña: 123456", "success")
            return redirect(url_for("proveedores"))
        except Exception:
            db.session.rollback()
            flash("❌ Error: El correo ya existe", "danger")
            return redirect(url_for("nuevo_usuario"))
    return render_template("usuarios_sistema_form.html")

@app.route("/usuario/bloquear/<int:usuario_id>", methods=["POST"])
@login_required
def bloquear_usuario_sistema(usuario_id):
    """Bloquear un usuario del sistema"""
    if session.get("rol") != "administrador":
        flash("❌ No autorizado", "danger")
        return redirect(url_for("usuarios_sistema"))
    
    motivo = request.form.get("motivo", "Bloqueo manual por administrador")
    
    try:
        # Verificar si el usuario existe
        usuario = UsuarioSistema.query.get(usuario_id)
        if not usuario:
            flash("❌ Usuario no encontrado", "danger")
            return redirect(url_for("usuarios_sistema"))
        
        # Verificar si ya tiene un bloqueo activo
        existe = db.session.execute(text("""
            SELECT id FROM bloqueos 
            WHERE usuario_sistema_id = :usuario_id 
            AND tipo_usuario = 'sistema' 
            AND estado = 1
        """), {"usuario_id": usuario_id}).fetchone()
        
        if existe:
            flash("⚠️ El usuario ya está bloqueado", "warning")
            return redirect(url_for("usuarios_sistema"))
        
        # Crear bloqueo
        db.session.execute(text("""
            INSERT INTO bloqueos 
            (tipo_usuario, usuario_sistema_id, motivo, fecha_bloqueo, bloqueado_por, estado)
            VALUES ('sistema', :usuario_id, :motivo, NOW(), :admin_id, 1)
        """), {"usuario_id": usuario_id, "motivo": motivo, "admin_id": session["usuario_id"]})
        
        db.session.commit()
        flash(f"✅ Usuario {usuario.nombres} bloqueado exitosamente", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al bloquear: {e}", "danger")
    
    return redirect(url_for("usuarios_sistema"))


@app.route("/usuario/desbloquear/<int:usuario_id>", methods=["POST"])
@login_required
def desbloquear_usuario_sistema(usuario_id):
    """Desbloquear un usuario del sistema"""
    if session.get("rol") != "administrador":
        flash("❌ No autorizado", "danger")
        return redirect(url_for("usuarios_sistema"))
    
    try:
        # Buscar bloqueo activo
        bloqueo = db.session.execute(text("""
            SELECT id FROM bloqueos 
            WHERE usuario_sistema_id = :usuario_id 
            AND tipo_usuario = 'sistema' 
            AND estado = 1
        """), {"usuario_id": usuario_id}).fetchone()
        
        if bloqueo:
            # Desbloquear manual
            db.session.execute(text("""
                UPDATE bloqueos 
                SET estado = 0, 
                    fecha_desbloqueo = NOW(),
                    desbloqueado_por = :admin_id
                WHERE id = :bloqueo_id
            """), {"bloqueo_id": bloqueo[0], "admin_id": session["usuario_id"]})
            flash("✅ Usuario desbloqueado exitosamente", "success")
        else:
            # Verificar si tiene bloqueo automático en intentos_login
            usuario = UsuarioSistema.query.get(usuario_id)
            if usuario:
                db.session.execute(text("""
                    UPDATE intentos_login 
                    SET email_bloqueado = NULL, intentos = 0 
                    WHERE email = :email
                """), {"email": usuario.correo})
                flash("✅ Bloqueo automático removido", "success")
            else:
                flash("⚠️ El usuario no tiene bloqueos activos", "warning")
        
        db.session.commit()
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al desbloquear: {e}", "danger")
    
    return redirect(url_for("usuarios_sistema"))

@app.route("/cambiar_clave", methods=["GET", "POST"])
@login_required
def cambiar_clave():
    if request.method == "POST":
        actual = request.form.get("actual")
        nueva = request.form["nueva"]
        confirmar = request.form["confirmar"]

        usuario = db.session.get(UsuarioSistema, session["usuario_id"])
        if not bcrypt.check_password_hash(usuario.clave, actual):
            flash("❌ Contraseña actual incorrecta", "danger")
            return render_template("cambiar_clave.html")

        if nueva != confirmar:
            flash("❌ Las contraseñas no coinciden", "danger")
            return render_template("cambiar_clave.html")

        if len(nueva) < 8:
            flash("❌ La contraseña debe tener al menos 8 caracteres", "danger")
            return render_template("cambiar_clave.html")

        usuario.clave = bcrypt.generate_password_hash(nueva).decode("utf-8")
        db.session.commit()
        flash("✅ Contraseña actualizada", "success")
        return redirect(url_for("productos"))

    return render_template("cambiar_clave.html")


@app.route("/proveedores")
@login_required
def proveedores():
    proveedoreslocal = Proveedor.query.all()
    return render_template("proveedores.html", proveedores=proveedoreslocal)

@app.route("/proveedores/nuevo")
@login_required
@requerir_permisos_escritura
def nuevo_proveedor():
    return render_template("proveedor_form.html")

@app.route("/proveedores/guardar", methods=["POST"])
@login_required
@requerir_permisos_escritura
def guardar_proveedor():
    nuevo = Proveedor(
        nombre=request.form["nombre"],
        email=request.form["email"],
        contacto=request.form["contacto"],
    )
    db.session.add(nuevo)
    db.session.commit()
    flash("✅ Proveedor registrado", "success")
    return redirect(url_for("proveedores"))

@app.route("/proveedores/editar/<int:id>")
@login_required
@requerir_permisos_escritura
def editar_proveedor(id):
    proveedor = db.session.get(Proveedor, id)
    if not proveedor:
        flash("❌ Proveedor no encontrado", "error")
        return redirect(url_for("proveedores"))
    return render_template("proveedor_form.html", proveedor=proveedor)

@app.route("/proveedores/actualizar/<int:id>", methods=["POST"])
@login_required
@requerir_permisos_escritura
def actualizar_proveedor(id):
    proveedor = db.session.get(Proveedor, id)
    if not proveedor:
        flash("❌ Proveedor no encontrado", "error")
        return redirect(url_for("proveedores"))
    proveedor.nombre = request.form["nombre"]
    proveedor.email = request.form["email"]
    proveedor.contacto = request.form["contacto"]
    db.session.commit()
    flash("✅ Proveedor actualizado", "success")
    return redirect(url_for("proveedores"))

@app.route("/proveedores/eliminar/<int:id>")
@login_required
@requerir_permisos_escritura
def eliminar_proveedor(id):
    proveedor = db.session.get(Proveedor, id)
    if not proveedor:
        flash("❌ Proveedor no encontrado", "error")
        return redirect(url_for("proveedores"))
    db.session.delete(proveedor)
    db.session.commit()
    flash("✅ Proveedor eliminado", "success")
    return redirect(url_for("proveedores"))


@app.route("/productos")
@login_required
def productos():
    categoria_id = request.args.get("categoria", type=int)
    destacado = request.args.get("destacado")
    
    query = Producto.query
    
    if categoria_id:
        query = query.filter_by(id_categoria=categoria_id)
    if destacado:
        query = query.filter_by(destacado=1)
    
    productos_lista = query.order_by(Producto.destacado.desc(), Producto.nombre.asc()).all()
    
    categorias = Categoria.query.filter_by(activo=True).all()
    
    return render_template("productos.html", 
                          productos=productos_lista,
                          categorias=categorias,
                          categoria_seleccionada=categoria_id)

@app.route("/productos/nuevo", methods=["GET"])
@login_required
@requerir_permisos_escritura
def nuevo_producto():
    proveedores = Proveedor.query.all()
    categorias = Categoria.query.filter_by(activo=True).all()  # ← Obtener categorías activas
    return render_template("producto_form.html", 
                          proveedores=proveedores,
                          categorias=categorias)

@app.route("/productos/guardar", methods=["POST"])
@login_required
@requerir_permisos_escritura
def guardar_producto():
    try:
        precio_oferta = request.form.get("precio_oferta")
        precio_oferta = float(precio_oferta) if precio_oferta and precio_oferta.strip() else None
        
        destacado = 1 if request.form.get("destacado") else 0
        
        id_categoria = request.form.get("id_categoria")
        id_categoria = int(id_categoria) if id_categoria and id_categoria.strip() else None
        
        nuevo = Producto(
            nombre=request.form["nombre"],
            descripcion=request.form["descripcion"],
            cantidad=int(request.form["cantidad"]),
            proveedor_id=request.form.get("proveedor") or None,
            precio=float(request.form["precio"]),
            id_categoria=id_categoria,  
            precio_oferta=precio_oferta,
            destacado=destacado,
            codigo_barras=request.form.get("codigo_barras") or None,
        )
        db.session.add(nuevo)
        db.session.flush()
        
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        if "imagen" in request.files:
            file = request.files["imagen"]
            if file and file.filename and allowed_file(file.filename):
                filename = f"{nuevo.id}_{int(time.time())}_{secure_filename(file.filename)}"
                filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(filepath)
                nuevo.imagen = filename
        
        db.session.commit()
        flash("✅ Producto creado exitosamente", "success")
        return redirect(url_for("productos"))
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al guardar: {str(e)}", "danger")
        return redirect(url_for("nuevo_producto"))

@app.route("/productos/editar/<int:id>")
@login_required
@requerir_permisos_escritura
def editar_producto(id):
    producto = db.session.get(Producto, id)
    if not producto:
        flash("❌ Producto no encontrado", "error")
        return redirect(url_for("productos"))
    
    proveedores = Proveedor.query.all()
    categorias = Categoria.query.filter_by(activo=True).all()  # ← Obtener categorías activas
    
    return render_template("producto_form.html", 
                          producto=producto, 
                          proveedores=proveedores,
                          categorias=categorias)

@app.route("/productos/actualizar/<int:id>", methods=["POST"])
@login_required
@requerir_permisos_escritura
def actualizar_producto(id):
    producto_obj = db.session.get(Producto, id)
    if not producto_obj:
        flash("❌ Producto no encontrado", "error")
        return redirect(url_for("productos"))
    
    try:
        precio_oferta = request.form.get("precio_oferta")
        precio_oferta = float(precio_oferta) if precio_oferta and precio_oferta.strip() else None
        
        id_categoria = request.form.get("id_categoria")
        id_categoria = int(id_categoria) if id_categoria and id_categoria.strip() else None
        
        producto_obj.nombre = request.form["nombre"]
        producto_obj.descripcion = request.form["descripcion"]
        producto_obj.cantidad = int(request.form["cantidad"])
        producto_obj.proveedor_id = request.form.get("proveedor") or None
        producto_obj.precio = float(request.form["precio"])
        producto_obj.id_categoria = id_categoria  # ← USAR id_categoria
        producto_obj.precio_oferta = precio_oferta
        producto_obj.destacado = 1 if request.form.get("destacado") else 0
        producto_obj.codigo_barras = request.form.get("codigo_barras") or None
        
        file = request.files.get("imagen")
        if file and file.filename and allowed_file(file.filename):
            if producto_obj.imagen:
                old_path = os.path.join(app.config["UPLOAD_FOLDER"], producto_obj.imagen)
                if os.path.exists(old_path):
                    os.remove(old_path)
            filename = f"{id}_{int(time.time())}_{secure_filename(file.filename)}"
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            producto_obj.imagen = filename
        
        db.session.commit()
        flash("✅ Producto actualizado exitosamente", "success")
        return redirect(url_for("productos"))
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al actualizar: {str(e)}", "danger")
        return redirect(url_for("editar_producto", id=id))

@app.route("/productos/eliminar/<int:id>")
@login_required
@requerir_permisos_escritura
def eliminar_producto(id):
    producto_obj = db.session.get(Producto, id)
    if not producto_obj:
        flash("❌ Producto no encontrado", "error")
        return redirect(url_for("productos"))
    
    try:
        if producto_obj.imagen:
            img_path = os.path.join(app.config["UPLOAD_FOLDER"], producto_obj.imagen)
            if os.path.exists(img_path):
                os.remove(img_path)
        
        db.session.delete(producto_obj)
        db.session.commit()
        flash("✅ Producto eliminado exitosamente", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al eliminar: {str(e)}", "danger")
    
    return redirect(url_for("productos"))

@app.route("/producto/preview/<int:producto_id>")
@login_required
def producto_preview(producto_id):
    producto = db.session.get(Producto, producto_id)
    if not producto:
        return {"error": "Producto no encontrado"}, 404
    
    imagen_url = None
    if producto.imagen:
        imagen_url = url_for("static", filename=f"img/productos/{producto.imagen}")
    
    return {
        "id": producto.id,
        "nombre": producto.nombre,
        "descripcion": producto.descripcion[:60] + "..." if len(producto.descripcion or "") > 60 else (producto.descripcion or ""),
        "precio": float(producto.precio or 0),
        "cantidad": producto.cantidad,
        "categoria": producto.categoria_rel.nombre if producto.categoria_rel else None,  # ← AGREGAR
        "imagen_url": imagen_url,
    }



@app.route("/ventas/nueva", methods=["GET", "POST"])
@login_required
def venta_nueva():
    lista_productos = Producto.query.filter(Producto.cantidad > 0).order_by(Producto.nombre).all()
    
    if session.get("rol") == "administrador":
        vendedores = UsuarioSistema.query.filter(UsuarioSistema.rol.in_(['administrador', 'vendedor'])).order_by(UsuarioSistema.nombres).all()
    else:
        vendedor = UsuarioSistema.query.filter_by(id=session.get("usuario_id")).first()
        vendedores = [vendedor] if vendedor else []
    
    if request.method == "POST":
        try:
            producto_id = int(request.form["producto_id"])
            cantidad = int(request.form["cantidad"])
            fecha_venta = datetime.now()
            tipo_comprobante = request.form.get("tipo_comprobante", "boleta")
            
            if session.get("rol") == "administrador":
                vendedor_id = int(request.form.get("vendedor_id", session.get("usuario_id")))
            else:
                vendedor_id = session.get("usuario_id")
            
            # ============================================
            # RECOLECTAR DATOS DEL CLIENTE (SOLO PARA EMAIL)
            # ============================================
            cliente_email = request.form.get("cliente_email", "")
            cliente_nombres = request.form.get("cliente_nombres", "")
            enviar_email = request.form.get("enviar_email", "0")
            
            print(f"\n📋 VENTA: Producto ID={producto_id}, Cantidad={cantidad}, Email={cliente_email}")
            
            # Generar número de comprobante
            numero_comprobante = f"{datetime.now().strftime('%Y%m%d')}-{datetime.now().strftime('%H%M%S')}"
            
            producto = Producto.query.get(producto_id)
            if not producto:
                flash("❌ Producto no encontrado", "danger")
                return render_template("ventas_form.html", productos=lista_productos, vendedores=vendedores, now=datetime.now())
            
            if producto.cantidad < cantidad:
                flash(f"❌ Stock insuficiente. Disponible: {producto.cantidad}", "danger")
                return render_template("ventas_form.html", productos=lista_productos, vendedores=vendedores, now=datetime.now())
            
            precio_unitario = float(producto.precio or 0)
            total_venta = precio_unitario * cantidad
            
            # ============================================
            # CREAR VENTA - SOLO COLUMNAS QUE EXISTEN
            # ============================================
            nueva_venta = Venta(
                producto_id=producto_id,
                cantidad=cantidad,
                fecha_venta=fecha_venta,
                vendedor_id=vendedor_id,
                tipo_comprobante=tipo_comprobante,
                numero_comprobante=numero_comprobante,
                # cliente_id se deja NULL (no tenemos el ID del cliente)
                # estado = 1 (por defecto)
            )
            db.session.add(nueva_venta)
            producto.cantidad -= cantidad
            db.session.commit()
            
            print(f"✅ Venta #{nueva_venta.id} registrada - Total: S/. {total_venta:.2f}")
            
            # ============================================
            # ENVIAR CORREO (si se solicitó)
            # ============================================
            if enviar_email == "1" and cliente_email and '@' in cliente_email:
                try:
                    enviar_comprobante_email(
                        destinatario=cliente_email,
                        cliente_nombre=cliente_nombres if cliente_nombres else "Cliente",
                        tipo_comprobante=tipo_comprobante,
                        numero_comprobante=numero_comprobante,
                        fecha=fecha_venta,
                        productos=[{'nombre': producto.nombre, 'cantidad': cantidad, 'precio_unitario': precio_unitario, 'total': total_venta}],
                        total_venta=total_venta
                    )
                    flash(f"✅ {tipo_comprobante.upper()} registrada y enviada a {cliente_email}", "success")
                except Exception as e:
                    print(f"❌ Error enviando email: {e}")
                    flash(f"⚠️ Venta registrada, pero error al enviar correo", "warning")
            else:
                flash(f"✅ Venta #{nueva_venta.id} registrada - Total: S/. {total_venta:.2f}", "success")
            
            return redirect(url_for("ver_comprobante", venta_id=nueva_venta.id))
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            flash(f"❌ Error al registrar la venta: {str(e)}", "danger")
            return render_template("ventas_form.html", productos=lista_productos, vendedores=vendedores, now=datetime.now())
    
    return render_template("ventas_form.html", productos=lista_productos, vendedores=vendedores, now=datetime.now())

# ===============================
# BLOQUEOS - VER Y DESBLOQUEAR
# ===============================
@app.route("/bloqueos")
@login_required
def ver_bloqueos():
    if session.get("rol") != "administrador":
        flash("❌ Solo administradores pueden ver bloqueos", "danger")
        return redirect(url_for("dashboard"))
    
    try:
        # ============================================
        # 1. BLOQUEOS PERMANENTES DE CLIENTES
        # ============================================
        bloqueos_permanentes = db.session.execute(text("""
            SELECT 
                b.id,
                b.cliente_id,
                b.motivo,
                b.fecha_bloqueo,
                b.bloqueado_por,
                b.estado,
                b.permanente,
                c.correo AS cliente_correo,
                c.nombres AS cliente_nombres,
                c.apellidos AS cliente_apellidos,
                CONCAT(bloq.nombres, ' ', bloq.apellidos) AS bloqueado_por_nombre
            FROM bloqueos b
            LEFT JOIN clientes c ON b.cliente_id = c.id
            LEFT JOIN usuarios_sistema bloq ON b.bloqueado_por = bloq.id
            WHERE b.tipo_usuario = 'cliente' AND b.estado = 1 AND b.permanente = 1
            ORDER BY b.fecha_bloqueo DESC
        """)).mappings().all()
        
        # ============================================
        # 2. BLOQUEOS TEMPORALES DE CLIENTES
        # ============================================
        bloqueos_temporales = db.session.execute(text("""
            SELECT 
                b.id,
                b.cliente_id,
                b.motivo,
                b.fecha_bloqueo,
                b.bloqueado_por,
                b.estado,
                b.permanente,
                b.minutos_bloqueo,
                c.correo AS cliente_correo,
                c.nombres AS cliente_nombres,
                c.apellidos AS cliente_apellidos,
                CONCAT(bloq.nombres, ' ', bloq.apellidos) AS bloqueado_por_nombre,
                DATE_ADD(b.fecha_bloqueo, INTERVAL b.minutos_bloqueo MINUTE) AS fecha_desbloqueo
            FROM bloqueos b
            LEFT JOIN clientes c ON b.cliente_id = c.id
            LEFT JOIN usuarios_sistema bloq ON b.bloqueado_por = bloq.id
            WHERE b.tipo_usuario = 'cliente' AND b.estado = 1 AND b.permanente = 0
            ORDER BY b.fecha_bloqueo DESC
        """)).mappings().all()
        
        # ============================================
        # 3. UNIFICAR RESULTADOS
        # ============================================
        bloqueos_lista = []
        
        # Permanentes
        for b in bloqueos_permanentes:
            bloqueo_dict = {
                'id_bloqueo': b['id'],
                'tipo': 'Cliente',
                'nombre_completo': f"{b['cliente_nombres'] or ''} {b['cliente_apellidos'] or ''}".strip(),
                'email': b['cliente_correo'],
                'motivo': b['motivo'] or 'Sin motivo',
                'fecha_bloqueo': b['fecha_bloqueo'],
                'bloqueado_por': b['bloqueado_por_nombre'] or 'Sistema',
                'origen': 'Permanente',
                'tipo_origen': 'bloqueos',
                'permanente': True
            }
            bloqueos_lista.append(bloqueo_dict)
        
        # Temporales
        for b in bloqueos_temporales:
            bloqueo_dict = {
                'id_bloqueo': b['id'],
                'tipo': 'Cliente',
                'nombre_completo': f"{b['cliente_nombres'] or ''} {b['cliente_apellidos'] or ''}".strip(),
                'email': b['cliente_correo'],
                'motivo': b['motivo'] or 'Sin motivo',
                'fecha_bloqueo': b['fecha_bloqueo'],
                'bloqueado_por': b['bloqueado_por_nombre'] or 'Sistema',
                'origen': 'Temporal (10 min)',
                'tipo_origen': 'bloqueos',
                'permanente': False,
                'fecha_desbloqueo': b['fecha_desbloqueo']
            }
            bloqueos_lista.append(bloqueo_dict)
        
        return render_template("bloqueos.html", bloqueos=bloqueos_lista)
        
    except Exception as e:
        print(f"❌ Error en bloqueos: {e}")
        flash(f"Error al cargar bloqueos: {e}", "danger")
        return render_template("bloqueos.html", bloqueos=[])

@app.route("/desbloquear-intento-login", methods=["POST"])
@login_required
def desbloquear_intento_login():
    """Desbloquear un email de la tabla intentos_login"""
    if session.get("rol") != "administrador":
        flash("❌ No autorizado", "danger")
        return redirect(url_for("ver_bloqueos"))
    
    email = request.form.get("email")
    
    if not email:
        flash("❌ Email no proporcionado", "danger")
        return redirect(url_for("ver_bloqueos"))
    
    try:
        db.session.execute(text("""
            UPDATE intentos_login 
            SET email_bloqueado = NULL, intentos = 0 
            WHERE email = :email
        """), {"email": email})
        
        db.session.commit()
        flash(f"✅ Usuario {email} desbloqueado exitosamente", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al desbloquear: {e}", "danger")
    
    return redirect(url_for("ver_bloqueos"))

@app.route("/bloqueos/desbloquear/<int:bloqueo_id>", methods=["POST"])
@login_required
def desbloquear_usuario_admin(bloqueo_id):
    """Desbloquear un usuario o cliente desde el panel de administración"""
    if session.get("rol") != "administrador":
        return jsonify({"success": False, "error": "No autorizado"}), 403
    
    try:
        # Obtener el bloqueo
        bloqueo = db.session.execute(text("""
            SELECT * FROM bloqueos WHERE id = :id AND estado = 1
        """), {"id": bloqueo_id}).mappings().first()
        
        if not bloqueo:
            return jsonify({"success": False, "error": "Bloqueo no encontrado"}), 404
        
        # Desbloquear usando el procedimiento
        db.session.execute(text("""
            CALL desbloquear_usuario(:bloqueo_id, :admin_id)
        """), {"bloqueo_id": bloqueo_id, "admin_id": session["usuario_id"]})
        
        db.session.commit()
        
        return jsonify({"success": True, "message": "Usuario desbloqueado exitosamente"})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/bloqueos/desbloquear", methods=["POST"])
@login_required
def desbloquear_usuario_form():
    """Desbloquear usuario desde formulario"""
    if session.get("rol") != "administrador":
        flash("❌ No autorizado", "danger")
        return redirect(url_for("ver_bloqueos"))
    
    bloqueo_id = request.form.get("bloqueo_id")
    
    if not bloqueo_id:
        flash("❌ ID de bloqueo no proporcionado", "danger")
        return redirect(url_for("ver_bloqueos"))
    
    try:
        db.session.execute(text("""
            CALL desbloquear_usuario(:bloqueo_id, :admin_id)
        """), {"bloqueo_id": bloqueo_id, "admin_id": session["usuario_id"]})
        
        db.session.commit()
        flash("✅ Usuario desbloqueado exitosamente", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al desbloquear: {str(e)}", "danger")
    
    return redirect(url_for("ver_bloqueos"))


@app.route("/api/bloqueos")
@login_required
def api_bloqueos():
    """API para obtener bloqueos activos de CLIENTES (para el contador)"""
    try:
        # 🔥 PRIMERO: Limpiar bloqueos expirados
        limpiar_bloqueos_expirados()
        
        # ============================================
        # 1. BLOQUEOS DE LA TABLA 'bloqueos' (manuales y temporales)
        # ============================================
        bloqueos_bd = db.session.execute(text("""
            SELECT 
                b.id,
                b.cliente_id,
                b.motivo,
                b.fecha_bloqueo,
                b.permanente,
                b.minutos_bloqueo,
                c.correo AS cliente_correo,
                c.nombres AS cliente_nombres,
                c.apellidos AS cliente_apellidos
            FROM bloqueos b
            LEFT JOIN clientes c ON b.cliente_id = c.id
            WHERE b.tipo_usuario = 'cliente' 
            AND b.estado = 1
            AND (
                b.permanente = 1 
                OR b.fecha_bloqueo > DATE_SUB(NOW(), INTERVAL b.minutos_bloqueo MINUTE)
            )
            ORDER BY b.fecha_bloqueo DESC
        """)).mappings().all()
        
        # ============================================
        # 2. BLOQUEOS AUTOMÁTICOS (intentos_login)
        # ============================================
        intentos_bloqueados = db.session.execute(text("""
            SELECT 
                i.id,
                i.email,
                i.intentos,
                i.email_bloqueado,
                c.id AS cliente_id,
                c.nombres AS cliente_nombres,
                c.apellidos AS cliente_apellidos,
                c.correo AS cliente_correo
            FROM intentos_login i
            JOIN clientes c ON i.email = c.correo
            WHERE i.email_bloqueado IS NOT NULL 
            AND i.email_bloqueado > NOW()
            ORDER BY i.email_bloqueado DESC
        """)).mappings().all()
        
        # ============================================
        # 3. UNIFICAR RESULTADOS SIN DUPLICADOS
        # ============================================
        resultado = []
        emails_vistos = set()
        
        # Procesar bloqueos de la tabla 'bloqueos'
        for b in bloqueos_bd:
            email = b['cliente_correo']
            # Si ya vimos este email en intentos_login, usar el de intentos_login (más reciente)
            if email in emails_vistos:
                continue
            
            emails_vistos.add(email)
            
            resultado.append({
                'id': b['id'],
                'tipo': 'Cliente',
                'nombre_completo': f"{b['cliente_nombres'] or ''} {b['cliente_apellidos'] or ''}".strip(),
                'email': email,
                'motivo': b['motivo'] or 'Sin motivo',
                'fecha_bloqueo': b['fecha_bloqueo'],
                'origen': 'Permanente' if b['permanente'] else 'Temporal',
                'permanente': bool(b['permanente'])
            })
        
        # Procesar bloqueos automáticos de intentos_login
        for i in intentos_bloqueados:
            email = i['email']
            # Si ya vimos este email, saltar (el de intentos_login es más reciente)
            if email in emails_vistos:
                continue
            
            emails_vistos.add(email)
            
            resultado.append({
                'id': i['id'],
                'tipo': 'Cliente',
                'nombre_completo': f"{i['cliente_nombres'] or ''} {i['cliente_apellidos'] or ''}".strip(),
                'email': email,
                'motivo': f"Bloqueo automático por {i['intentos']} intentos fallidos",
                'fecha_bloqueo': i['email_bloqueado'],
                'origen': 'Automático',
                'permanente': False
            })
        
        return jsonify(resultado)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/ventas")
@login_required
def ventas():
    try:
        # Si es vendedor, solo ve sus propias ventas
        if session.get("rol") == "vendedor":
            vendedor_id = session.get("usuario_id")
            vendedor_filtro = vendedor_id
        else:
            vendedor_filtro = request.args.get('vendedor_id', type=int)
        
        # ============================================
        # CONSULTA SIN COLUMNAS QUE NO EXISTEN
        # ============================================
        query = """
            SELECT 
                v.id, 
                v.cantidad, 
                v.fecha_venta, 
                v.tipo_comprobante, 
                v.numero_comprobante,
                p.nombre as producto, 
                p.precio,
                u.id as vendedor_id, 
                u.nombres as vendedor_nombres, 
                u.apellidos as vendedor_apellidos
            FROM ventas v
            JOIN productos p ON v.producto_id = p.id
            LEFT JOIN usuarios_sistema u ON v.vendedor_id = u.id
        """
        
        params = {}
        if vendedor_filtro:
            query += " WHERE v.vendedor_id = :vendedor_id"
            params['vendedor_id'] = vendedor_filtro
        
        query += " ORDER BY v.id DESC"
        
        resultados = db.session.execute(db.text(query), params).mappings().all()
        
        # Convertir a lista de diccionarios
        ventas_lista = []
        for row in resultados:
            venta_dict = dict(row)
            venta_dict['precio_unitario'] = float(venta_dict.get('precio') or 0)
            venta_dict['total_venta'] = venta_dict['precio_unitario'] * venta_dict.get('cantidad', 1)
            ventas_lista.append(venta_dict)
        
        # Obtener lista de vendedores para el filtro (solo para administradores)
        vendedores = []
        vendedor_seleccionado = None
        vendedor_id_actual = None
        
        if session.get("rol") == "administrador":
            vendedores = UsuarioSistema.query.filter_by(rol='vendedor').all()
            vendedor_id_actual = vendedor_filtro
            if vendedor_filtro:
                vendedor_seleccionado = UsuarioSistema.query.get(vendedor_filtro)
        
        return render_template("ventas.html", 
                              ventas=ventas_lista, 
                              vendedores=vendedores,
                              vendedor_seleccionado=vendedor_seleccionado,
                              vendedor_id_actual=vendedor_id_actual,
                              rol_usuario=session.get("rol"))
        
    except Exception as e:
        print(f"Error en ventas: {e}")
        flash(f"Error al cargar ventas: {str(e)}", "danger")
        return render_template("ventas.html", ventas=[], vendedores=[])

@app.route("/comprobante/<int:venta_id>")
@login_required
def ver_comprobante(venta_id):
    venta = db.session.query(Venta, 
                              Producto.nombre.label("producto_nombre"), 
                              Producto.precio,
                              UsuarioSistema.nombres.label("vendedor_nombres"),
                              UsuarioSistema.apellidos.label("vendedor_apellidos")
                             ).join(Producto, Venta.producto_id == Producto.id)\
                              .outerjoin(UsuarioSistema, Venta.vendedor_id == UsuarioSistema.id)\
                              .filter(Venta.id == venta_id).first()
    
    if not venta:
        flash("❌ Venta no encontrada", "danger")
        return redirect(url_for("ventas"))
    
    total = venta.Venta.cantidad * venta.precio
    
    return render_template("comprobante.html", venta=venta, total=total)

@app.route("/ver_ventas", methods=["GET", "POST"])
@login_required
@requerir_permisos_escritura
def ver_ventas():
    ventas_lista = []
    totalProductos = 0
    totalPrecio = 0
    fecha_seleccionada = request.args.get("fecha") or request.form.get("fecha")
    if fecha_seleccionada:
        fecha_obj = datetime.strptime(fecha_seleccionada, "%Y-%m-%d").date()
        ventas_lista = (
            db.session.query(
                Venta.id,
                func.concat(UsuarioSistema.nombres, " ", UsuarioSistema.apellidos).label("vendedor"),
                Producto.nombre.label("producto"),
                Venta.cantidad,
                Venta.fecha_venta,
                Producto.precio,
                (Venta.cantidad * Producto.precio).label("subtotal"),
            )
            .join(Producto, Venta.producto_id == Producto.id)
            .outerjoin(UsuarioSistema, Venta.vendedor_id == UsuarioSistema.id)
            .filter(func.date(Venta.fecha_venta) == fecha_obj)
            .order_by(Venta.id.asc())
            .all()
        )
        ventas_lista = [
            {
                "id": v.id,
                "vendedor": v.vendedor,
                "producto": v.producto,
                "cantidad": v.cantidad,
                "fecha_venta": v.fecha_venta,
                "precio": float(v.precio),
                "subtotal": float(v.subtotal),
            }
            for v in ventas_lista
        ]
        totalProductos = sum(v["cantidad"] for v in ventas_lista)
        totalPrecio = sum(v["cantidad"] * v["precio"] for v in ventas_lista)
    return render_template("ver_ventas.html", ventas=ventas_lista, totalProductos=totalProductos, totalPrecio=totalPrecio, fecha_seleccionada=fecha_seleccionada)

@app.route("/ver_productos_proveedor", methods=["GET", "POST"])
@login_required
@requerir_permisos_escritura
def ver_productos_proveedor():
    proveedores = Proveedor.query.all()
    productos = []
    proveedor_seleccionado = None
    proveedor_id = request.args.get("proveedor_id") or request.form.get("proveedor_id")
    if proveedor_id:
        proveedor_seleccionado = db.session.get(Proveedor, int(proveedor_id))
        productos = (
            db.session.query(
                Producto.id,
                Producto.nombre,
                Producto.cantidad,
                func.count(Venta.id).label("total_ventas"),
            )
            .outerjoin(Venta, Producto.id == Venta.producto_id)
            .filter(Producto.proveedor_id == proveedor_id)
            .group_by(Producto.id, Producto.nombre, Producto.cantidad)
            .all()
        )
    return render_template("ver_producto_proveedor.html", proveedores=proveedores, productos=productos, proveedor_id=int(proveedor_id) if proveedor_id else None, proveedor_seleccionado=proveedor_seleccionado)

# ===============================
# API PARA SISTEMA INTERNO
# ===============================

@app.route("/api/productos/<int:producto_id>/stock")
def api_producto_stock(producto_id):
    """API para obtener stock actual de un producto"""
    producto = Producto.query.get(producto_id)
    if not producto:
        return jsonify({"error": "Producto no encontrado"}), 404
    return jsonify({
        "id": producto.id,
        "stock": producto.cantidad,
        "nombre": producto.nombre
    })

@app.route("/api/productos", methods=["GET"])
@login_required
def api_listar_productos():
    productos = Producto.query.filter(Producto.cantidad > 0).all()
    return jsonify([
        {
            "id": p.id,
            "nombre": p.nombre,
            "descripcion": p.descripcion,
            "precio": p.precio,
            "imagen_url": url_for("static", filename=f"img/productos/{p.imagen}") if p.imagen else None,
        }
        for p in productos
    ])

@app.route("/api/buscar_producto")
@login_required
def api_buscar_producto():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Parámetro requerido"}), 400
    if q.isdigit():
        producto = Producto.query.get(int(q))
    else:
        producto = Producto.query.filter(Producto.nombre.like(f"%{q}%")).first()
    if producto and producto.cantidad > 0:
        return jsonify({
            "id": producto.id,
            "nombre": producto.nombre,
            "precio": float(producto.precio),
            "stock": producto.cantidad,
        })
    return jsonify({"error": "No encontrado o sin stock"}), 404

@app.route("/api/productos/top")
@login_required
def productos_top():
    top = (
        db.session.query(
            Producto.id,
            Producto.nombre,
            Producto.precio,
            func.sum(Venta.cantidad).label("total_vendido"),
        )
        .join(Venta)
        .filter(func.date(Venta.fecha_venta) == datetime.now().date())
        .group_by(Producto.id)
        .order_by(func.sum(Venta.cantidad).desc())
        .limit(10)
        .all()
    )
    return jsonify([
        {
            "id": p.id,
            "nombre": p.nombre,
            "precio": float(p.precio),
            "vendidos": p.total_vendido,
        }
        for p in top
    ])

@app.route("/api/ventas/rapida", methods=["POST"])
@login_required
def venta_rapida():
    data = request.get_json()
    items = data.get("items", [])
    if not items:
        return jsonify({"success": False, "error": "Carrito vacío"})
    try:
        for item in items:
            producto = Producto.query.get(item["id"])
            if not producto or producto.cantidad < item["cantidad"]:
                return jsonify({"success": False, "error": f'Stock insuficiente: {item["nombre"]}'})
        venta_ids = []
        total_general = 0
        for item in items:
            producto = Producto.query.get(item["id"])
            total = producto.precio * item["cantidad"]
            nueva_venta = Venta(
                producto_id=item["id"],
                cantidad=item["cantidad"],
                vendedor_id=session["usuario_id"],
                fecha_venta=datetime.now(),
                tipo_comprobante="boleta",
                numero_comprobante=f"POS-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                cliente_nombres=data.get("cliente_nombre", ""),
                cliente_apellidos=data.get("cliente_apellido", ""),
                cliente_documento=data.get("cliente_dni", ""),
            )
            db.session.add(nueva_venta)
            producto.cantidad -= item["cantidad"]
            total_general += total
            venta_ids.append(nueva_venta.id)
        db.session.commit()
        return jsonify({"success": True, "venta_id": venta_ids[0], "total": total_general})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)})

# ===============================
# CLIENTES (TIENDA ONLINE)
# ===============================

@app.route("/catalogo", methods=["GET"])
def catalogo_cliente():
    try:
        # Obtener el ID de categoría desde la URL
        categoria_id = request.args.get('categoria', type=int)
        
        # Obtener todas las categorías activas
        categorias = Categoria.query.filter_by(activo=True).all()
        
        # Construir la consulta de productos
        query = Producto.query.filter(Producto.cantidad > 0)
        
        # Si hay una categoría seleccionada, filtrar
        if categoria_id:
            query = query.filter(Producto.id_categoria == categoria_id)
            # Obtener el nombre de la categoría seleccionada para mostrarlo
            categoria_seleccionada = Categoria.query.get(categoria_id)
        else:
            categoria_seleccionada = None
        
        # Ejecutar la consulta
        productos = query.order_by(Producto.nombre.asc()).all()
        
        # Renderizar la plantilla con los datos
        return render_template("catalogo_cliente.html", 
                              categorias=categorias,
                              productos=productos,
                              categoria_seleccionada=categoria_seleccionada,
                              categoria_id=categoria_id)
    except Exception as e:
        print(f"❌ Error en /catalogo: {e}")
        import traceback
        traceback.print_exc()
        return render_template("catalogo_cliente.html", 
                              categorias=[], 
                              productos=[],
                              categoria_seleccionada=None,
                              categoria_id=None)

@app.route("/api/productos/catalogo")
def api_productos_catalogo():
    try:
        q = request.args.get('q', '')
        categoria_id = request.args.get('categoria', type=int)
        
        query = Producto.query.filter(Producto.cantidad > 0)
        
        if q:
            query = query.filter(Producto.nombre.like(f'%{q}%'))
        if categoria_id:
            query = query.filter_by(id_categoria=categoria_id)
        
        productos = query.all()
        
        resultado = []
        for p in productos:
            try:
                # Obtener nombre de categoría de forma segura
                categoria_nombre = None
                if hasattr(p, 'categoria_rel') and p.categoria_rel:
                    categoria_nombre = p.categoria_rel.nombre
                
                resultado.append({
                    "id": p.id,
                    "nombre": p.nombre,
                    "descripcion": p.descripcion,
                    "precio": float(p.precio) if p.precio else 0,
                    "precio_oferta": float(p.precio_oferta) if p.precio_oferta else None,
                    "categoria_id": p.id_categoria,
                    "categoria_nombre": categoria_nombre,
                    "cantidad": p.cantidad,
                    "destacado": p.destacado,
                    "imagen_url": url_for("static", filename=f"img/productos/{p.imagen}") if p.imagen else None,
                })
            except Exception as e:
                print(f"Error procesando producto {p.id}: {e}")
                continue
        
        return jsonify(resultado)
        
    except Exception as e:
        print(f"❌ Error en /api/productos/catalogo: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "detalle": "Error interno del servidor"}), 500



@app.route("/logout-cliente")
def logout_cliente():
    session.clear()
    flash("✅ Sesión cerrada", "success")
    return redirect("/catalogo")

@app.route("/registro-cliente", methods=["GET", "POST"])
def registro_cliente():
    if request.method == "POST":
        try:
            existe = Cliente.query.filter_by(correo=request.form["email"]).first()
            if existe:
                flash("❌ El correo ya está registrado", "danger")
                return redirect(url_for("registro_cliente"))
            cliente = Cliente(
                dni=request.form.get("dni"),
                nombres=request.form["nombres"],
                apellidos=request.form["apellidos"],
                email=request.form["email"],
                telefono=request.form.get("telefono"),
                direccion=request.form.get("direccion"),
                clave=bcrypt.generate_password_hash(request.form["clave"]).decode("utf-8"),
            )
            db.session.add(cliente)
            db.session.commit()
            flash("✅ Registro exitoso", "success")
            return redirect(url_for("login_cliente"))
        except Exception as e:
            db.session.rollback()
            flash(f"❌ Error: {str(e)}", "danger")
    return render_template("registro_cliente.html")

@app.route("/cliente/perfil")
@login_required_cliente
def cliente_perfil():
    cliente = Cliente.query.get(session["cliente_id"])
    if not cliente:
        flash("❌ Cliente no encontrado", "danger")
        return redirect(url_for("logout_cliente"))
    return render_template("cliente_perfil.html", cliente=cliente)

@app.route("/cliente/actualizar-perfil", methods=["POST"])
@login_required_cliente
def cliente_actualizar_perfil():
    try:
        cliente = Cliente.query.get(session["cliente_id"])
        cliente.nombres = request.form.get("nombres")
        cliente.apellidos = request.form.get("apellidos")
        cliente.telefono = request.form.get("telefono")
        cliente.direccion = request.form.get("direccion")
        
        nuevo_email = request.form.get("email")
        if nuevo_email != cliente.correo:
            existe = Cliente.query.filter_by(correo=nuevo_email).first()
            if existe:
                flash("❌ El correo ya está registrado", "danger")
                return redirect(url_for("cliente_perfil"))
            cliente.correo = nuevo_email
            session["cliente_correo"] = nuevo_email
        
        nuevo_dni = request.form.get("dni")
        if nuevo_dni and nuevo_dni != cliente.dni:
            cliente.dni = nuevo_dni
            session["cliente_dni"] = nuevo_dni
        
        db.session.commit()
        
        session["cliente_nombres"] = cliente.nombres
        session["cliente_apellidos"] = cliente.apellidos
        session["cliente_telefono"] = cliente.telefono
        session["cliente_direccion"] = cliente.direccion
        
        flash("✅ Perfil actualizado", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error: {str(e)}", "danger")
    
    return redirect(url_for("cliente_perfil"))

@app.route("/cliente/cambiar-contrasena", methods=["GET", "POST"])
@login_required_cliente
def cliente_cambiar_contrasena():
    if request.method == "POST":
        contrasena_actual = request.form.get("contrasena_actual")
        nueva_contrasena = request.form.get("nueva_contrasena")
        confirmar_contrasena = request.form.get("confirmar_contrasena")

        if not contrasena_actual or not nueva_contrasena or not confirmar_contrasena:
            flash("❌ Todos los campos son obligatorios", "danger")
            return redirect(url_for("cliente_cambiar_contrasena"))

        if nueva_contrasena != confirmar_contrasena:
            flash("❌ Las contraseñas no coinciden", "danger")
            return redirect(url_for("cliente_cambiar_contrasena"))

        if len(nueva_contrasena) < 6:
            flash("❌ La contraseña debe tener al menos 6 caracteres", "danger")
            return redirect(url_for("cliente_cambiar_contrasena"))

        cliente = Cliente.query.get(session["cliente_id"])

        if not bcrypt.check_password_hash(cliente.clave, contrasena_actual):
            flash("❌ Contraseña actual incorrecta", "danger")
            return redirect(url_for("cliente_cambiar_contrasena"))

        try:
            nueva_clave_hash = bcrypt.generate_password_hash(nueva_contrasena).decode("utf-8")
            cliente.clave = nueva_clave_hash
            db.session.commit()
            flash("✅ Contraseña actualizada", "success")
            return redirect("/catalogo")
        except Exception as e:
            db.session.rollback()
            flash(f"❌ Error: {str(e)}", "danger")
    
    return render_template("cliente_cambiar_contrasena.html")

# ===============================
# RECUPERACIÓN DE CONTRASEÑA
# ===============================

@app.route("/recuperar-contrasena", methods=["GET", "POST"])
def recuperar_contrasena():
    if request.method == "POST":
        email = request.form.get("email")
        
        if not email:
            flash("❌ Ingresa tu correo electrónico", "danger")
            return redirect(url_for("recuperar_contrasena"))
        
        cliente = Cliente.query.filter_by(correo=email).first()
        
        if cliente:
            token = generar_token_recuperacion()
            cliente.token_recuperacion = token
            cliente.token_expiracion = datetime.now() + timedelta(hours=1)
            db.session.commit()
            
            enlace = url_for("resetear_contrasena", token=token, _external=True)
            flash(f"✅ Enlace de recuperación: {enlace}", "info")
        else:
            flash("✅ Si el correo está registrado, recibirás un enlace", "success")
        
        return redirect(url_for("login_cliente"))
    
    return render_template("recuperar_contrasena.html")

@app.route("/resetear-contrasena/<token>", methods=["GET", "POST"])
def resetear_contrasena(token):
    cliente = Cliente.query.filter_by(token_recuperacion=token).first()
    
    if not cliente:
        flash("❌ Enlace inválido o ya utilizado", "danger")
        return redirect(url_for("login_cliente"))
    
    if cliente.token_expiracion < datetime.now():
        flash("❌ El enlace ha expirado", "danger")
        return redirect(url_for("recuperar_contrasena"))
    
    if request.method == "POST":
        nueva = request.form.get("nueva")
        confirmar = request.form.get("confirmar")
        
        if not nueva or not confirmar:
            flash("❌ Todos los campos son obligatorios", "danger")
            return render_template("resetear_contrasena.html", token=token)
        
        if nueva != confirmar:
            flash("❌ Las contraseñas no coinciden", "danger")
            return render_template("resetear_contrasena.html", token=token)
        
        if len(nueva) < 6:
            flash("❌ La contraseña debe tener al menos 6 caracteres", "danger")
            return render_template("resetear_contrasena.html", token=token)
        
        try:
            nueva_clave_hash = bcrypt.generate_password_hash(nueva).decode("utf-8")
            cliente.clave = nueva_clave_hash
            cliente.token_recuperacion = None
            cliente.token_expiracion = None
            db.session.commit()
            
            flash("✅ Contraseña actualizada", "success")
            return redirect(url_for("login_cliente"))
        except Exception as e:
            db.session.rollback()
            flash(f"❌ Error: {str(e)}", "danger")
    
    return render_template("resetear_contrasena.html", token=token)

# ===============================
# PEDIDOS
# ===============================

@app.route("/carrito")
def ver_carrito():
    return render_template("carrito.html")

@app.route("/checkout")
@login_required_cliente
def checkout():
    # Obtener el cliente actual
    cliente = Cliente.query.get(session.get("cliente_id"))
    
    # Pasar datos del cliente al template
    return render_template("checkout.html", 
                          cliente=cliente,
                          datetime=datetime)

@app.route("/pago")
@login_required_cliente
def pago():
    # Obtener datos del checkout desde localStorage (vía sesión o query params)
    # Por ahora simplemente renderizamos la plantilla
    return render_template("pago.html", datetime=datetime)

@app.route("/mis-pedidos")
@login_required_cliente
def mis_pedidos():
    pedidos = Pedido.query.filter_by(cliente_id=session["cliente_id"]).order_by(Pedido.fecha_pedido.desc()).all()
    return render_template("mis_pedidos.html", pedidos=pedidos)

@app.route("/api/mis-pedidos")
@login_required_cliente
def api_mis_pedidos():
    pedidos = Pedido.query.filter_by(cliente_id=session["cliente_id"]).order_by(Pedido.fecha_pedido.desc()).all()
    return jsonify([
        {
            "id": p.id,
            "fecha_pedido": p.fecha_pedido.strftime("%d/%m/%Y %H:%M"),
            "estado": p.estado,
            "total": float(p.total),
            "tipo_entrega": p.tipo_entrega,
        }
        for p in pedidos
    ])

@app.route("/api/pedidos/crear", methods=["POST"])
@login_required_cliente
def crear_pedido():
    data = request.get_json()
    
    print("=" * 60)
    print("📦 DATOS RECIBIDOS EN /api/pedidos/crear:")
    print(f"Items: {len(data.get('items', []))} productos")
    print(f"Tipo entrega: {data.get('tipo_entrega')}")
    print(f"Total: {data.get('total')}")
    print(f"Cliente data completo: {data.get('cliente', {})}")
    print(f"Documento: {data.get('cliente', {}).get('documento', 'NO ENCONTRADO')}")
    print(f"Razón Social: {data.get('cliente', {}).get('razon_social', 'NO')}")
    print(f"Dirección Fiscal: {data.get('cliente', {}).get('direccion_fiscal', 'NO')}")
    print("=" * 60)
    
    try:
        # ============================================
        # 1. VALIDAR STOCK
        # ============================================
        for item in data["items"]:
            producto = Producto.query.get(item["id"])
            if not producto:
                return jsonify({"success": False, "error": f'Producto no encontrado: {item["nombre"]}'})
            if producto.cantidad < item["cantidad"]:
                return jsonify({"success": False, "error": f'Stock insuficiente: {item["nombre"]}. Disponible: {producto.cantidad}'})
        
        # ============================================
        # 2. EXTRAER DATOS DEL CHECKOUT
        # ============================================
        cliente_data = data.get("cliente", {})
        
        # Datos personales
        cliente_nombres = cliente_data.get("nombres", "").strip()
        cliente_apellidos = cliente_data.get("apellidos", "").strip()
        cliente_email = cliente_data.get("email", "").strip()
        cliente_telefono = cliente_data.get("telefono", "").strip()
        
        # Documento (DNI o RUC)
        cliente_documento = cliente_data.get("documento", "").strip()
        if not cliente_documento:
            cliente_documento = cliente_data.get("dni", "").strip()
        if not cliente_documento:
            cliente_documento = cliente_data.get("ruc", "").strip()
        
        # Datos de facturación (para RUC)
        cliente_razon_social = cliente_data.get("razon_social", "").strip()
        cliente_direccion_fiscal = cliente_data.get("direccion_fiscal", "").strip()  # ← AGREGAR
        
        # Dirección de entrega
        cliente_direccion = data.get("direccion", "").strip()
        
        # Fallback a sesión si es necesario
        if not cliente_nombres:
            cliente_nombres = session.get("cliente_nombres", "")
        if not cliente_apellidos:
            cliente_apellidos = session.get("cliente_apellidos", "")
        if not cliente_email:
            cliente_email = session.get("cliente_email", "")
        if not cliente_telefono:
            cliente_telefono = session.get("cliente_telefono", "")
        if not cliente_documento:
            cliente_documento = session.get("cliente_dni", "")
        
        print(f"\n📝 DATOS A GUARDAR EN VENTA:")
        print(f"   Nombres: '{cliente_nombres}'")
        print(f"   Apellidos: '{cliente_apellidos}'")
        print(f"   Email: '{cliente_email}'")
        print(f"   Teléfono: '{cliente_telefono}'")
        print(f"   Documento (DNI/RUC): '{cliente_documento}'")
        print(f"   Razón Social: '{cliente_razon_social}'")
        print(f"   Dirección Fiscal: '{cliente_direccion_fiscal}'")
        print(f"   Dirección Entrega: '{cliente_direccion}'")
        
        # ============================================
        # 3. CREAR PEDIDO
        # ============================================
        pedido = Pedido(
            cliente_id=session["cliente_id"],
            total=float(data["total"]),
            tipo_entrega=data["tipo_entrega"],
            direccion_entrega=cliente_direccion if data["tipo_entrega"] == "delivery" else "",
        )
        db.session.add(pedido)
        db.session.flush()
        
        # ============================================
        # 4. CREAR DETALLES Y VENTAS
        # ============================================
        productos_para_correo = []
        
        for item in data["items"]:
            producto = Producto.query.get(item["id"])
            subtotal = float(item["precio"]) * int(item["cantidad"])
            
            # Detalle del pedido
            detalle = DetallePedido(
                pedido_id=pedido.id,
                producto_id=item["id"],
                cantidad=int(item["cantidad"]),
                precio_unitario=float(item["precio"]),
                subtotal=subtotal,
            )
            db.session.add(detalle)
            
            # Actualizar stock
            producto.cantidad -= int(item["cantidad"])
            
            # Crear VENTA (guardar dirección fiscal en cliente_direccion o campo específico)
            venta = Venta(
                producto_id=item["id"],
                cantidad=int(item["cantidad"]),
                vendedor_id=1,
                fecha_venta=datetime.now(),
                tipo_comprobante=data.get("comprobante", {}).get("tipo", "boleta"),
                numero_comprobante=f"ONLINE-{pedido.id}",
                cliente_nombres=cliente_nombres,
                cliente_apellidos=cliente_apellidos,
                cliente_documento=cliente_documento,
                cliente_email=cliente_email,
                cliente_direccion=cliente_direccion,
                cliente_direccion_fiscal=cliente_direccion_fiscal,  # ← NUEVO: dirección fiscal
                cliente_razon_social=cliente_razon_social,          # ← NUEVO: razón social
            )
            db.session.add(venta)
            
            productos_para_correo.append({
                'nombre': producto.nombre,
                'cantidad': int(item["cantidad"]),
                'precio_unitario': float(item["precio"]),
                'total': subtotal
            })
        
        db.session.commit()
        
        print(f"\n✅ PEDIDO #{pedido.id} COMPLETADO")
        print(f"   Cliente: {cliente_nombres} {cliente_apellidos}")
        print(f"   Documento: '{cliente_documento}'")
        if cliente_razon_social:
            print(f"   Razón Social: '{cliente_razon_social}'")
        if cliente_direccion_fiscal:
            print(f"   Dirección Fiscal: '{cliente_direccion_fiscal}'")
        
        # ============================================
        # 5. ENVIAR CORREO
        # ============================================
        try:
            enviar_comprobante_email(
                destinatario=cliente_email,
                cliente_nombre=f"{cliente_nombres} {cliente_apellidos}".strip(),
                tipo_comprobante=data.get("comprobante", {}).get("tipo", "boleta"),
                numero_comprobante=f"ONLINE-{pedido.id}",
                fecha=datetime.now(),
                productos=productos_para_correo,
                total_venta=float(data["total"])
            )
            print(f"📧 Correo enviado a {cliente_email}")
        except Exception as e:
            print(f"⚠️ Error al enviar correo: {e}")
        
        return jsonify({"success": True, "pedido_id": pedido.id})
        
    except Exception as e:
        db.session.rollback()
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)})

@app.route("/pedidos")
@login_required
def ver_pedidos():
    es_admin = session.get("rol") == "administrador"
    
    # ============================================
    # OBTENER PARÁMETROS DE FILTRO
    # ============================================
    search = request.args.get('search', '').strip()
    estado_filter = request.args.get('estado', '').strip()
    fecha_desde = request.args.get('fecha_desde', '').strip()
    fecha_hasta = request.args.get('fecha_hasta', '').strip()
    
    # ============================================
    # CONTADORES CORRECTOS
    # ============================================
    total_pedidos = db.session.execute(text(
        "SELECT COUNT(*) FROM pedidos WHERE estado != 'cancelado'"
    )).scalar() or 0
    
    pedidos_pendientes = db.session.execute(text(
        "SELECT COUNT(*) FROM pedidos WHERE estado = 'pendiente'"
    )).scalar() or 0
    
    pedidos_completados = db.session.execute(text(
        "SELECT COUNT(*) FROM pedidos WHERE estado IN ('entregado', 'recogido')"
    )).scalar() or 0
    
    pedidos_en_proceso = db.session.execute(text(
        "SELECT COUNT(*) FROM pedidos WHERE estado IN ('confirmado', 'preparando', 'enviado', 'listo_tienda')"
    )).scalar() or 0
    
    # ============================================
    # CONSULTA CON FILTROS
    # ============================================
    query = db.session.query(
        Pedido.id,
        Pedido.fecha_pedido,
        Pedido.estado,
        Pedido.total,
        Pedido.tipo_entrega,
        Pedido.direccion_entrega,
        Cliente.nombres.label("cliente_nombres"),
        Cliente.apellidos.label("cliente_apellidos"),
        Cliente.correo.label("cliente_email"),
        Cliente.telefono.label("cliente_telefono"),
    ).join(Cliente, Pedido.cliente_id == Cliente.id)
    
    # Aplicar filtros
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            db.or_(
                Pedido.id.cast(db.String).like(search_term),
                Cliente.nombres.like(search_term),
                Cliente.apellidos.like(search_term),
                Cliente.correo.like(search_term)
            )
        )
    
    if estado_filter:
        query = query.filter(Pedido.estado == estado_filter)
    else:
        # Si no hay filtro de estado, excluir cancelados
        query = query.filter(Pedido.estado != 'cancelado')
    
    if fecha_desde:
        try:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            query = query.filter(func.date(Pedido.fecha_pedido) >= fecha_desde_obj)
        except:
            pass
    
    if fecha_hasta:
        try:
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            query = query.filter(func.date(Pedido.fecha_pedido) <= fecha_hasta_obj)
        except:
            pass
    
    pedidos = query.order_by(Pedido.fecha_pedido.desc()).all()
    
    pedidos_lista = []
    for p in pedidos:
        pedidos_lista.append({
            "id": p.id,
            "fecha_pedido": p.fecha_pedido,
            "estado": p.estado,
            "total": float(p.total) if p.total else 0,
            "tipo_entrega": p.tipo_entrega,
            "direccion_entrega": p.direccion_entrega,
            "cliente_nombres": p.cliente_nombres,
            "cliente_apellidos": p.cliente_apellidos,
            "cliente_nombre_completo": f"{p.cliente_nombres or ''} {p.cliente_apellidos or ''}".strip(),
            "cliente_email": p.cliente_email,
            "cliente_telefono": p.cliente_telefono,
        })
    
    # ============================================
    # OBTENER LISTA DE ESTADOS PARA EL FILTRO
    # ============================================
    estados_disponibles = db.session.execute(
        text("SELECT DISTINCT estado FROM pedidos ORDER BY estado")
    ).fetchall()
    estados_lista = [e[0] for e in estados_disponibles]
    
    return render_template("pedidos.html", 
                          pedidos=pedidos_lista,
                          total_pedidos=total_pedidos,
                          pedidos_pendientes=pedidos_pendientes,
                          pedidos_completados=pedidos_completados,
                          pedidos_en_proceso=pedidos_en_proceso,
                          es_admin=es_admin,
                          search=search,
                          estado_filter=estado_filter,
                          fecha_desde=fecha_desde,
                          fecha_hasta=fecha_hasta,
                          estados=estados_lista,
                          datetime=datetime)

@app.route("/pedidos/detalle/<int:pedido_id>")
@login_required
def detalle_pedido(pedido_id):
    pedido = Pedido.query.get_or_404(pedido_id)
    detalles = db.session.query(DetallePedido, Producto.nombre.label("producto_nombre")).join(Producto).filter(DetallePedido.pedido_id == pedido_id).all()
    cliente = Cliente.query.get(pedido.cliente_id)
    # Buscar venta asociada (opcional, solo si existe)
    venta = Venta.query.filter_by(numero_comprobante=f"ONLINE-{pedido_id}").first()
    es_admin = session.get("rol") == "administrador"
    
    return render_template("pedido_detalle.html", 
                          pedido=pedido, 
                          detalles=detalles, 
                          cliente=cliente,  # ← PASAR EL CLIENTE
                          venta=venta,      # ← PASAR LA VENTA (opcional)
                          es_admin=es_admin)
@app.route("/pedidos/cambiar-estado/<int:pedido_id>", methods=["POST"])
@login_required
def cambiar_estado_pedido(pedido_id):
    # Verificar si es una petición AJAX
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    if session.get("rol") != "administrador":
        if is_ajax:
            return jsonify({"success": False, "error": "No autorizado"}), 403
        flash("❌ Solo administradores pueden cambiar estados", "danger")
        return redirect(url_for("ver_pedidos"))
    
    pedido = Pedido.query.get_or_404(pedido_id)
    nuevo_estado = request.form.get("estado")
    
    # Estados válidos
    estados_validos = [
        "pendiente", 
        "confirmado", 
        "preparando", 
        "enviado", 
        "entregado", 
        "listo_tienda", 
        "recogido", 
        "cancelado"
    ]
    
    # Mensajes descriptivos
    mensajes = {
        "pendiente": "⏳ Pedido marcado como pendiente",
        "confirmado": "✅ Pedido confirmado",
        "preparando": "📦 Pedido en preparación",
        "enviado": "🚚 Pedido enviado a domicilio",
        "entregado": "🎁 Pedido entregado al cliente",
        "listo_tienda": "🏪 Pedido listo para recoger en tienda",
        "recogido": "🙌 Cliente recogió su pedido",
        "cancelado": "❌ Pedido cancelado"
    }
    
    if nuevo_estado in estados_validos:
        # Guardar el cambio
        pedido.estado = nuevo_estado
        db.session.commit()
        
        mensaje = mensajes.get(nuevo_estado, f"✅ Pedido #{pedido_id} actualizado a: {nuevo_estado}")
        
        # Si es AJAX, devolver JSON
        if is_ajax:
            return jsonify({
                "success": True,
                "message": mensaje,
                "estado": nuevo_estado,
                "pedido_id": pedido_id
            })
        
        # Si es normal, mostrar flash
        flash(mensaje, "success")
        
        # Enviar correo al cliente (opcional)
        try:
            cliente = Cliente.query.get(pedido.cliente_id)
            if cliente and cliente.correo:
                # Aquí puedes agregar el envío de correo
                print(f"📧 Enviando correo a {cliente.correo} sobre el pedido #{pedido_id}")
        except Exception as e:
            print(f"Error enviando correo: {e}")
            
    else:
        if is_ajax:
            return jsonify({"success": False, "error": f"Estado '{nuevo_estado}' no es válido"}), 400
        flash(f"❌ Estado '{nuevo_estado}' no es válido", "danger")
    
    return redirect(url_for("ver_pedidos"))

# ===============================
# API PARA CLIENTES
# ===============================

@app.route("/usuarios-sistema")
@login_required
def usuarios_sistema():
    """Panel de gestión de usuarios del sistema con bloqueo/desbloqueo"""
    if session.get("rol") != "administrador":
        flash("❌ Solo administradores pueden gestionar usuarios", "danger")
        return redirect(url_for("dashboard"))
    
    try:
        # ============================================
        # OBTENER TODOS LOS USUARIOS DEL SISTEMA
        # ============================================
        usuarios = db.session.execute(text("""
            SELECT 
                u.id,
                u.correo,
                u.nombres,
                u.apellidos,
                u.rol,
                u.estado,
                b.id AS bloqueo_id,
                b.motivo AS bloqueo_motivo,
                b.fecha_bloqueo AS bloqueo_fecha,
                b.bloqueado_por AS bloqueo_por,
                CONCAT(bloq.nombres, ' ', bloq.apellidos) AS bloqueo_por_nombre
            FROM usuarios_sistema u
            LEFT JOIN bloqueos b ON u.id = b.usuario_sistema_id 
                AND b.tipo_usuario = 'sistema' 
                AND b.estado = 1
            LEFT JOIN usuarios_sistema bloq ON b.bloqueado_por = bloq.id
            ORDER BY u.id ASC
        """)).mappings().all()
        
        # ============================================
        # VERIFICAR BLOQUEOS AUTOMÁTICOS (intentos_login)
        # ============================================
        intentos_bloqueados = db.session.execute(text("""
            SELECT 
                i.email,
                i.intentos,
                i.email_bloqueado,
                u.id AS usuario_id
            FROM intentos_login i
            JOIN usuarios_sistema u ON i.email = u.correo
            WHERE i.email_bloqueado IS NOT NULL AND i.email_bloqueado > NOW()
        """)).mappings().all()
        
        # Crear un diccionario para verificar bloqueos automáticos
        bloqueos_automaticos = {i['usuario_id']: i for i in intentos_bloqueados}
        
        # ============================================
        # PROCESAR DATOS PARA LA VISTA
        # ============================================
        usuarios_lista = []
        for u in usuarios:
            usuario_dict = dict(u)
            
            # Verificar si tiene bloqueo automático
            if u['id'] in bloqueos_automaticos:
                auto = bloqueos_automaticos[u['id']]
                usuario_dict['bloqueo_automatico'] = True
                usuario_dict['bloqueo_automatico_motivo'] = f"Bloqueo automático por {auto['intentos']} intentos fallidos"
                usuario_dict['bloqueo_automatico_fecha'] = auto['email_bloqueado']
                usuario_dict['bloqueo_automatico_id'] = auto['email']
            else:
                usuario_dict['bloqueo_automatico'] = False
            
            # Estado del usuario
            if usuario_dict['bloqueo_id']:
                usuario_dict['estado_texto'] = '🔒 Bloqueado'
                usuario_dict['estado_badge'] = 'danger'
                usuario_dict['bloqueado'] = True
            elif usuario_dict['bloqueo_automatico']:
                usuario_dict['estado_texto'] = '🔒 Bloqueado (Auto)'
                usuario_dict['estado_badge'] = 'warning'
                usuario_dict['bloqueado'] = True
            else:
                usuario_dict['estado_texto'] = '✅ Activo'
                usuario_dict['estado_badge'] = 'success'
                usuario_dict['bloqueado'] = False
            
            usuarios_lista.append(usuario_dict)
        
        return render_template("usuarios_sistema_gestion.html", usuarios=usuarios_lista)
        
    except Exception as e:
        print(f"❌ Error en usuarios_sistema: {e}")
        flash(f"Error al cargar usuarios: {e}", "danger")
        return render_template("usuarios_sistema_gestion.html", usuarios=[])

@app.route("/api/cliente/direccion")
@login_required_cliente
def api_cliente_direccion():
    try:
        cliente_id = session.get("cliente_id")
        if not cliente_id:
            return jsonify({"success": False, "direccion": "", "error": "No session"})

        cliente = Cliente.query.get(cliente_id)
        if not cliente:
            return jsonify({"success": False, "direccion": "", "error": "Cliente no encontrado"})

        direccion = cliente.direccion or ""
        return jsonify({"success": True, "direccion": direccion})
    except Exception as e:
        return jsonify({"success": False, "direccion": "", "error": str(e)})

@app.route("/api/consultar-dni/<dni>")
@login_required_cliente
def api_consultar_dni_cliente(dni):
    if not dni.isdigit() or len(dni) != 8:
        return jsonify({"success": False, "error": "DNI inválido"}), 400
    
    cliente = Cliente.query.filter_by(dni=dni).first()
    if cliente:
        return jsonify({
            "success": True,
            "nombres": cliente.nombres,
            "apellidos": cliente.apellidos,
            "dni": cliente.dni,
        })
    
    venta = Venta.query.filter_by(cliente_documento=dni).first()
    if venta and venta.cliente_nombres:
        return jsonify({
            "success": True,
            "nombres": venta.cliente_nombres,
            "apellidos": venta.cliente_apellidos or "",
            "dni": dni,
        })
    
    return jsonify({"success": False, "error": "DNI no encontrado"}), 404

@app.route("/api/consultar-ruc/<ruc>")
@login_required_cliente
def api_consultar_ruc_cliente(ruc):
    if not ruc.isdigit() or len(ruc) != 11:
        return jsonify({"success": False, "error": "RUC inválido"}), 400
    
    # Primero buscar en tabla de empresas
    empresa = RucEmpresa.query.filter_by(ruc=ruc).first()
    if empresa:
        return jsonify({
            "success": True,
            "razon_social": empresa.razon_social,
            "direccion": empresa.direccion or "",
            "ruc": ruc,
        })
    
    # Luego buscar en ventas anteriores
    venta = Venta.query.filter_by(cliente_documento=ruc).first()
    if venta and venta.cliente_nombres:
        direccion = ""
        if hasattr(venta, 'cliente_direccion_fiscal') and venta.cliente_direccion_fiscal:
            direccion = venta.cliente_direccion_fiscal
        return jsonify({
            "success": True,
            "razon_social": venta.cliente_nombres,
            "direccion": direccion,
            "ruc": ruc,
        })
    
    return jsonify({"success": False, "error": "RUC no encontrado"}), 404

# ===============================
# PÁGINAS ESTÁTICAS
# ===============================

@app.route("/acerca-de")
def acerca_de():
    return render_template("acerca_de.html")

@app.route("/contacto")
def contacto():
    return render_template("contacto.html")

# ===============================
# INICIALIZAR BASE DE DATOS
# ===============================

with app.app_context():
    db.create_all()
    
    try:
        from sqlalchemy import text
        result = db.session.execute(text("SHOW COLUMNS FROM intentos_login LIKE 'email_bloqueado'"))
        if not result.fetchone():
            db.session.execute(text("ALTER TABLE intentos_login ADD COLUMN email_bloqueado DATETIME NULL"))
            db.session.commit()
            print("✅ Columna email_bloqueado agregada")
    except Exception as e:
        print(f"⚠️ Migración: {e}")
        db.session.rollback()

# ===============================
# DASHBOARD
# ===============================

@app.route("/dashboard")
@login_required
def dashboard():
    import pandas as pd
    import plotly
    import plotly.graph_objs as go
    import json
    
    hoy = datetime.now().date()
    inicio_mes = datetime.now().replace(day=1).date()
    hace_30_dias = datetime.now() - timedelta(days=30)
    
    # ========== HORA PERÚ ==========
    ahora_peru = datetime.now() - timedelta(hours=5)
    
    # ========== 1. ESTADÍSTICAS ==========
    ventas_hoy = Venta.query.filter(func.date(Venta.fecha_venta) == hoy).all()
    total_ventas_hoy = sum(v.cantidad * v.producto.precio for v in ventas_hoy) if ventas_hoy else 0
    cantidad_ventas_hoy = len(ventas_hoy) if ventas_hoy else 0
    
    ventas_mes = Venta.query.filter(func.date(Venta.fecha_venta) >= inicio_mes).all()
    total_ventas_mes = sum(v.cantidad * v.producto.precio for v in ventas_mes) if ventas_mes else 0
    cantidad_ventas_mes = len(ventas_mes) if ventas_mes else 0
    
    pedidos_pendientes = Pedido.query.filter(Pedido.estado == 'pendiente').count()
    pedidos_en_proceso = Pedido.query.filter(Pedido.estado.in_(['confirmado', 'preparando', 'enviado'])).count()
    
    total_clientes = Cliente.query.count()
    hace_7_dias = datetime.now() - timedelta(days=7)
    clientes_nuevos = Cliente.query.filter(Cliente.fecha_registro >= hace_7_dias).count()
    
    # Ventas por día
    ventas_por_dia = []
    for i in range(6, -1, -1):
        fecha = datetime.now() - timedelta(days=i)
        fecha_str = fecha.strftime('%d/%m')
        resultado = db.session.execute(
            text("""
                SELECT COALESCE(SUM(v.cantidad * p.precio), 0) as total
                FROM ventas v
                JOIN productos p ON v.producto_id = p.id
                WHERE DATE(v.fecha_venta) = :fecha
            """),
            {"fecha": fecha.date()}
        ).fetchone()
        total_dia = float(resultado[0]) if resultado and resultado[0] else 0
        ventas_por_dia.append({'fecha': fecha_str, 'total': total_dia})
    
    # Top productos - CORREGIDO (SIN IMAGEN)
    top_productos = db.session.query(
        Producto.nombre,
        func.sum(Venta.cantidad).label('total_vendido')
    ).join(Venta).filter(
        func.date(Venta.fecha_venta) >= hace_30_dias.date()
    ).group_by(Producto.id).order_by(func.sum(Venta.cantidad).desc()).limit(5).all()
    
    # Stock
    stock_bajo = Producto.query.filter(Producto.cantidad <= 10, Producto.cantidad > 0).order_by(Producto.cantidad.asc()).limit(10).all()
    stock_critico = Producto.query.filter(Producto.cantidad == 0).order_by(Producto.nombre.asc()).limit(10).all()
    
    # ========== 2. GRÁFICOS CON PLOTLY ==========
    
    # Gráfico 1: Ventas últimos 7 días
    fechas_7d = [datetime.now() - timedelta(days=i) for i in range(6, -1, -1)]
    ventas_7d = []
    for fecha in fechas_7d:
        resultado = db.session.execute(
            text("""
                SELECT COALESCE(SUM(v.cantidad * p.precio), 0) as total
                FROM ventas v
                JOIN productos p ON v.producto_id = p.id
                WHERE DATE(v.fecha_venta) = :fecha
            """),
            {"fecha": fecha.date()}
        ).fetchone()
        ventas_7d.append(float(resultado[0]) if resultado else 0)
    
    fig_ventas = go.Figure()
    fig_ventas.add_trace(go.Bar(
        x=[fecha.strftime('%d/%m') for fecha in fechas_7d],
        y=ventas_7d,
        name='Ventas (S/)',
        marker_color='#2563eb',
        text=[f'S/. {v:.2f}' for v in ventas_7d],
        textposition='outside'
    ))
    fig_ventas.update_layout(
        title='📈 Ventas Últimos 7 Días',
        xaxis_title='Fecha',
        yaxis_title='Total S/.',
        template='plotly_white',
        height=350,
        showlegend=False
    )
    
    # Gráfico 2: Top productos
    fig_top = go.Figure()
    if top_productos:
        nombres = [p[0] for p in top_productos]   
        vendidos = [float(p[1]) for p in top_productos] 
        fig_top.add_trace(go.Bar(
            x=nombres,
            y=vendidos,
            name='Unidades',
            marker_color='#10b981',
            text=vendidos,
            textposition='outside'
        ))
    fig_top.update_layout(
        title='🏆 Top 5 Productos Más Vendidos',
        xaxis_title='Producto',
        yaxis_title='Unidades Vendidas',
        template='plotly_white',
        height=350,
        showlegend=False
    )
    
    # Gráfico 3: Ventas por categoría
    ventas_categoria = db.session.execute(
        text("""
            SELECT c.nombre as categoria,
                   COALESCE(SUM(v.cantidad * p.precio), 0) as total_ventas
            FROM ventas v
            JOIN productos p ON v.producto_id = p.id
            LEFT JOIN categorias c ON p.id_categoria = c.id_categoria
            WHERE v.fecha_venta >= :fecha_inicio
            GROUP BY c.nombre
            ORDER BY total_ventas DESC
        """),
        {"fecha_inicio": hace_30_dias.date()}
    ).fetchall()
    
    fig_cat = go.Figure()
    if ventas_categoria:
        categorias = [row[0] or 'Sin categoría' for row in ventas_categoria]
        totales = [float(row[1]) for row in ventas_categoria]
        fig_cat.add_trace(go.Pie(
            labels=categorias,
            values=totales,
            hole=0.4,
            marker=dict(colors=['#2563eb', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899'])
        ))
    fig_cat.update_layout(
        title='📊 Ventas por Categoría',
        template='plotly_white',
        height=350,
        showlegend=True
    )
    
    # Gráfico 4: Estado de pedidos
    estados_pedidos = db.session.execute(
        text("""
            SELECT estado, COUNT(*) as cantidad
            FROM pedidos
            GROUP BY estado
        """)
    ).fetchall()
    
    fig_estados = go.Figure()
    if estados_pedidos:
        estados = [row[0] for row in estados_pedidos]
        cantidades = [row[1] for row in estados_pedidos]
        colores = {'pendiente': '#f59e0b', 'confirmado': '#3b82f6', 
                   'preparando': '#8b5cf6', 'enviado': '#06b6d4',
                   'entregado': '#10b981', 'cancelado': '#ef4444'}
        colors = [colores.get(e, '#6b7280') for e in estados]
        fig_estados.add_trace(go.Bar(
            x=estados,
            y=cantidades,
            marker_color=colors,
            text=cantidades,
            textposition='outside'
        ))
    fig_estados.update_layout(
        title='📋 Estado de Pedidos',
        xaxis_title='Estado',
        yaxis_title='Cantidad',
        template='plotly_white',
        height=350,
        showlegend=False
    )
    
    # ========== 3. CONVERTIR GRÁFICOS A JSON ==========
    graph_ventas = json.dumps(fig_ventas, cls=plotly.utils.PlotlyJSONEncoder)
    graph_top = json.dumps(fig_top, cls=plotly.utils.PlotlyJSONEncoder)
    graph_cat = json.dumps(fig_cat, cls=plotly.utils.PlotlyJSONEncoder)
    graph_estados = json.dumps(fig_estados, cls=plotly.utils.PlotlyJSONEncoder)
    
    # ========== 4. RENDERIZAR TEMPLATE ==========
    return render_template("dashboard.html",
                          total_ventas_hoy=total_ventas_hoy,
                          cantidad_ventas_hoy=cantidad_ventas_hoy,
                          total_ventas_mes=total_ventas_mes,
                          cantidad_ventas_mes=cantidad_ventas_mes,
                          pedidos_pendientes=pedidos_pendientes,
                          pedidos_en_proceso=pedidos_en_proceso,
                          total_clientes=total_clientes,
                          clientes_nuevos=clientes_nuevos,
                          ventas_por_dia=ventas_por_dia,
                          top_productos=top_productos,
                          stock_bajo=stock_bajo,
                          stock_critico=stock_critico,
                          graph_ventas=graph_ventas,
                          graph_top=graph_top,
                          graph_cat=graph_cat,
                          graph_estados=graph_estados,
                          datetime=datetime,
                          timedelta=timedelta,
                          ahora_peru=ahora_peru) 

@app.route("/procesar_pago", methods=["POST"])
@login_required_cliente
def procesar_pago():
    try:
        data = request.get_json()
        
        email_cliente = data.get("email")
        nombres = data.get("nombres")
        apellidos = data.get("apellidos")
        total = data.get("total")
        tipo_comprobante = data.get("tipo_comprobante")
        productos = data.get("productos", [])
        

        html_comprobante = generar_comprobante_pedido(nombres, apellidos, productos, total, tipo_comprobante)
        

        asunto = f"✅ Comprobante de {tipo_comprobante.upper()} - Librería Salesiana"
        exito, msg = enviar_comprobante_email(email_cliente, asunto, html_comprobante)
        
        if exito:
            return jsonify({"success": True, "message": "Correo enviado correctamente"})
        else:
            return jsonify({"success": False, "message": f"Error al enviar: {msg}"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

def generar_comprobante_pedido(nombres, apellidos, productos, total, tipo_comprobante):
    cliente_nombre = f"{nombres} {apellidos}".strip()
    productos_html = ""
    for item in productos:
        productos_html += f"""
        <tr>
            <td>{item.get('nombre', 'Producto')}</td>
            <td style="text-align: center">{item.get('cantidad', 1)}</td>
            <td style="text-align: right">S/. {item.get('precio', 0):.2f}</td>
            <td style="text-align: right">S/. {item.get('precio', 0) * item.get('cantidad', 1):.2f}</td>
        </tr>
        """
    
    if tipo_comprobante == "factura":
        titulo = "FACTURA ELECTRÓNICA"
        ruc_html = f"<p><strong>RUC:</strong> {productos[0].get('ruc', '—') if productos else '—'}</p>"
    else:
        titulo = "BOLETA DE VENTA ELECTRÓNICA"
        ruc_html = ""
    
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Comprobante de Venta</title></head>
<body style="font-family: Arial, sans-serif;">
<div style="max-width: 600px; margin: auto; background: #f8f9fa; padding: 20px; border-radius: 10px;">
    <div style="background: #007bff; color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0;">
        <h2>📚 LIBRERÍA SALESIANA DON BOSCO</h2>
        <p>{titulo}</p>
    </div>
    <div style="padding: 20px; background: white;">
        <p><strong>Fecha:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
        <p><strong>Cliente:</strong> {cliente_nombre}</p>
        {ruc_html}
        <hr>
        <h4>Detalle de compra:</h4>
        <table style="width: 100%; border-collapse: collapse;">
            <thead>
                <tr style="background: #e9ecef;">
                    <th style="padding: 8px; text-align: left;">Producto</th>
                    <th style="padding: 8px; text-align: center;">Cant.</th>
                    <th style="padding: 8px; text-align: right;">Precio</th>
                    <th style="padding: 8px; text-align: right;">Subtotal</th>
                </tr>
            </thead>
            <tbody>
                {productos_html}
            </tbody>
            <tfoot>
                <tr>
                    <td colspan="3" style="text-align: right; padding: 10px;"><strong>TOTAL:</strong></td>
                    <td style="text-align: right; padding: 10px;"><strong>S/. {total:.2f}</strong></td>
                </tr>
            </tfoot>
        </table>
        <hr>
        <p style="text-align: center;">✨ ¡Gracias por su compra! Que Dios lo bendiga. ✨</p>
    </div>
</div>
</body>
</html>"""

@app.route("/mis-pedidos/detalle/<int:pedido_id>")
@login_required_cliente
def cliente_detalle_pedido(pedido_id):
    pedido = Pedido.query.get_or_404(pedido_id)
    

    if pedido.cliente_id != session.get("cliente_id"):
        flash("❌ No tienes permiso para ver este pedido", "danger")
        return redirect(url_for("mis_pedidos"))
    

    detalles = db.session.query(DetallePedido, Producto.nombre.label("producto_nombre")).join(Producto).filter(DetallePedido.pedido_id == pedido_id).all()
    

    cliente = Cliente.query.get(pedido.cliente_id)
    

    venta = None
    

    venta = Venta.query.filter_by(numero_comprobante=f"ONLINE-{pedido_id}").first()
    

    if not venta:
        venta = Venta.query.filter(Venta.numero_comprobante.like(f'%{pedido_id}%')).first()
    

    if not venta and cliente and cliente.dni:
        venta = Venta.query.filter_by(cliente_documento=cliente.dni).order_by(Venta.fecha_venta.desc()).first()
    

    if not venta and cliente and cliente.correo:
        venta = Venta.query.filter_by(cliente_email=cliente.correo).order_by(Venta.fecha_venta.desc()).first()
    

    print("=" * 50)
    print(f"🔍 Pedido #{pedido_id} - Cliente: {cliente.nombres if cliente else 'N/A'}")
    print(f"   Venta encontrada: {venta.id if venta else 'NO'}")
    if venta:
        print(f"   Número comprobante: {venta.numero_comprobante}")
        print(f"   Tipo: {venta.tipo_comprobante}")
        print(f"   Razón Social: {venta.cliente_razon_social}")
        print(f"   Dirección Fiscal: {venta.cliente_direccion_fiscal}")
    print("=" * 50)
    
    return render_template("cliente_pedido_detalle.html", 
                          pedido=pedido, 
                          detalles=detalles, 
                          cliente=cliente, 
                          venta=venta)



@app.route("/api/comercial/pedidos", methods=["GET"])
@login_required
def api_comercial_pedidos():
    """Obtener todos los pedidos (microservicio comercial)"""
    try:
        pedidos = db.session.execute(text("""
            SELECT * FROM comercial_pedidos 
            ORDER BY fecha_pedido DESC
        """)).mappings().all()
        
        return jsonify([dict(p) for p in pedidos])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/comercial/pedidos/<int:id>", methods=["GET"])
@login_required
def api_comercial_pedido(id):
    """Obtener pedido específico con detalles"""
    try:
        pedido = db.session.execute(text("""
            SELECT * FROM comercial_pedidos WHERE id = :id
        """), {"id": id}).mappings().first()
        
        if not pedido:
            return jsonify({"error": "Pedido no encontrado"}), 404
        
        detalles = db.session.execute(text("""
            SELECT * FROM comercial_detalle_pedido WHERE pedido_id = :id
        """), {"id": id}).mappings().all()
        
        pedido_dict = dict(pedido)
        pedido_dict["detalles"] = [dict(d) for d in detalles]
        
        return jsonify(pedido_dict)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/comercial/pedidos/<int:id>/estado", methods=["PUT"])
@login_required
def api_comercial_actualizar_estado(id):
    """Actualizar estado de un pedido"""
    if session.get("rol") != "administrador":
        return jsonify({"error": "No autorizado"}), 403
    
    try:
        data = request.get_json()
        estado = data.get("estado")
        
        if not estado:
            return jsonify({"error": "Estado requerido"}), 400
        
        result = db.session.execute(text("""
            UPDATE comercial_pedidos 
            SET estado = :estado 
            WHERE id = :id
        """), {"estado": estado, "id": id})
        
        db.session.commit()
        
        if result.rowcount == 0:
            return jsonify({"error": "Pedido no encontrado"}), 404
        
        return jsonify({"success": True, "message": "Estado actualizado"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/api/comercial/ventas", methods=["GET"])
@login_required
def api_comercial_ventas():
    """Obtener todas las ventas"""
    try:
        ventas = db.session.execute(text("""
            SELECT * FROM comercial_ventas 
            ORDER BY fecha_venta DESC
        """)).mappings().all()
        
        return jsonify([dict(v) for v in ventas])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =============================================
# MICROSERVICIO INVENTARIO - APIs
# =============================================

@app.route("/api/inventario/productos", methods=["GET"])
@login_required
def api_inventario_productos():
    """Obtener todos los productos (microservicio inventario)"""
    try:
        productos = db.session.execute(text("""
            SELECT * FROM inventario_productos 
            ORDER BY nombre
        """)).mappings().all()
        
        return jsonify([dict(p) for p in productos])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/inventario/productos/<int:id>", methods=["GET"])
@login_required
def api_inventario_producto(id):
    """Obtener producto específico"""
    try:
        producto = db.session.execute(text("""
            SELECT * FROM inventario_productos WHERE id = :id
        """), {"id": id}).mappings().first()
        
        if not producto:
            return jsonify({"error": "Producto no encontrado"}), 404
        
        return jsonify(dict(producto))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/inventario/stock/<int:id>", methods=["PUT"])
@login_required
def api_inventario_actualizar_stock(id):
    """Actualizar stock de un producto"""
    if session.get("rol") not in ["administrador"]:
        return jsonify({"error": "No autorizado"}), 403
    
    try:
        data = request.get_json()
        cantidad = data.get("cantidad")
        
        if cantidad is None:
            return jsonify({"error": "Cantidad requerida"}), 400
        
        result = db.session.execute(text("""
            UPDATE inventario_productos 
            SET cantidad = :cantidad 
            WHERE id = :id
        """), {"cantidad": cantidad, "id": id})
        
        db.session.commit()
        
        if result.rowcount == 0:
            return jsonify({"error": "Producto no encontrado"}), 404
        
        return jsonify({"success": True, "message": "Stock actualizado"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/api/inventario/stock/bajo/<int:minimo>", methods=["GET"])
@login_required
def api_inventario_bajo_stock(minimo):
    """Obtener productos con stock bajo"""
    try:
        productos = db.session.execute(text("""
            SELECT * FROM inventario_productos 
            WHERE cantidad < :minimo 
            ORDER BY cantidad
        """), {"minimo": minimo}).mappings().all()
        
        return jsonify([dict(p) for p in productos])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/inventario/verificar-stock/<int:id>/<int:cantidad>", methods=["GET"])
@login_required
def api_inventario_verificar_stock(id, cantidad):
    """Verificar si hay stock disponible"""
    try:
        producto = db.session.execute(text("""
            SELECT cantidad FROM inventario_productos WHERE id = :id
        """), {"id": id}).mappings().first()
        
        if not producto:
            return jsonify({"error": "Producto no encontrado"}), 404
        
        disponible = producto["cantidad"] >= cantidad
        
        return jsonify({
            "producto_id": id,
            "disponible": disponible,
            "stock_actual": producto["cantidad"],
            "cantidad_solicitada": cantidad
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/api/health", methods=["GET"])
def api_health():
    """Verificar estado de los microservicios"""
    try:

        db.session.execute(text("SELECT 1"))
        

        comercial_existe = db.session.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables 
            WHERE table_schema = 'librospe_db' 
            AND table_name = 'comercial_pedidos'
        """)).scalar()
        
        inventario_existe = db.session.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables 
            WHERE table_schema = 'librospe_db' 
            AND table_name = 'inventario_productos'
        """)).scalar()
        
        return jsonify({
            "status": "OK",
            "services": {
                "comercial": "active" if comercial_existe else "not_configured",
                "inventario": "active" if inventario_existe else "not_configured"
            },
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "ERROR",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500



@app.route("/microservicios/dashboard")
@login_required
def microservicios_dashboard():
    """Dashboard para monitorear microservicios"""
    if session.get("rol") != "administrador":
        flash("❌ Solo administradores pueden ver este panel", "danger")
        return redirect(url_for("dashboard"))

    total_pedidos = db.session.execute(text(
        "SELECT COUNT(*) FROM comercial_pedidos"
    )).scalar() or 0
    
    pedidos_pendientes = db.session.execute(text(
        "SELECT COUNT(*) FROM comercial_pedidos WHERE estado = 'pendiente'"
    )).scalar() or 0
    
    pedidos_confirmados = db.session.execute(text(
        "SELECT COUNT(*) FROM comercial_pedidos WHERE estado = 'confirmado'"
    )).scalar() or 0
    
  
    total_productos = db.session.execute(text(
        "SELECT COUNT(*) FROM inventario_productos"
    )).scalar() or 0
    
    productos_bajo_stock = db.session.execute(text(
        "SELECT COUNT(*) FROM inventario_productos WHERE cantidad < 10"
    )).scalar() or 0
    
    productos_agotados = db.session.execute(text(
        "SELECT COUNT(*) FROM inventario_productos WHERE cantidad = 0"
    )).scalar() or 0
    
    return render_template("microservicios_dashboard.html",
                          total_pedidos=total_pedidos,
                          pedidos_pendientes=pedidos_pendientes,
                          pedidos_confirmados=pedidos_confirmados,
                          total_productos=total_productos,
                          productos_bajo_stock=productos_bajo_stock,
                          productos_agotados=productos_agotados)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
application = app

