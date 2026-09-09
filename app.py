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
load_dotenv(verbose=True)


db_host = os.getenv('DB_HOST')
db_user = os.getenv('DB_USER')
db_password = os.getenv('DB_PASSWORD')
db_name = os.getenv('DB_NAME')
secret_key = os.getenv('SECRET_KEY')

API_PERU_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6ImkyNTExOTExQGNvbnRpbmVudGFsLmVkdS5wZSJ9.fNVvZJpJitDHY9c3Hrr2T7iLhfZ-NhyJ90Ynh5Delys"
print(f"🔑 API_PERU_TOKEN cargado: {bool(API_PERU_TOKEN)}")

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




@app.route("/")
def inicio():
    return render_template("index.html")



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
        

        registro_intentos = IntentosLogin.query.filter_by(email=email).first()
        if registro_intentos and registro_intentos.email_bloqueado and registro_intentos.email_bloqueado > datetime.now():
            minutos_restantes = (registro_intentos.email_bloqueado - datetime.now()).seconds // 60
            flash("⛔ CUENTA BLOQUEADA TEMPORALMENTE", "danger")
            flash(f"⏳ Has agotado tus 3 intentos. Espera {minutos_restantes} minutos para volver a intentar.", "warning")
            template_data["bloqueo_temporal"] = True
            template_data["minutos_restantes"] = minutos_restantes
            return render_template("login_cliente.html", **template_data)

        if bcrypt.check_password_hash(cliente.clave, clave):

            limpiar_intentos_exitosos(email, ip_cliente)

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
   
            resultado = registrar_intento_fallido(email, ip_cliente, es_cliente=True)
            
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

                    if intentos_totales >= 4:
                        flash(f"⚠️ ¡ÚLTIMO INTENTO! Contraseña incorrecta. Si fallas una vez más (5 de 5), tu cuenta será BLOQUEADA PERMANENTEMENTE.", "danger")
                    else:
                        flash(f"❌ Contraseña incorrecta. Próximo intento (3 de 3) bloqueará la cuenta TEMPORALMENTE por 10 minutos.", "warning")
                        flash(f"ℹ️ Intentos totales: {intentos_totales} de 5. Con 5 fallos, bloqueo PERMANENTE.", "info")
            
            return render_template("login_cliente.html", **template_data)

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

        usuario = UsuarioSistema.query.get(usuario_id)
        if not usuario:
            flash("❌ Usuario no encontrado", "danger")
            return redirect(url_for("usuarios_sistema"))
        

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

        bloqueo = db.session.execute(text("""
            SELECT id FROM bloqueos 
            WHERE usuario_sistema_id = :usuario_id 
            AND tipo_usuario = 'sistema' 
            AND estado = 1
        """), {"usuario_id": usuario_id}).fetchone()
        
        if bloqueo:

            db.session.execute(text("""
                UPDATE bloqueos 
                SET estado = 0, 
                    fecha_desbloqueo = NOW(),
                    desbloqueado_por = :admin_id
                WHERE id = :bloqueo_id
            """), {"bloqueo_id": bloqueo[0], "admin_id": session["usuario_id"]})
            flash("✅ Usuario desbloqueado exitosamente", "success")
        else:

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
            cliente_email = request.form.get("cliente_email", "")
            cliente_nombres = request.form.get("cliente_nombres", "")
            enviar_email = request.form.get("enviar_email", "0")
            
            print(f"\n📋 VENTA: Producto ID={producto_id}, Cantidad={cantidad}, Email={cliente_email}")
            

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
            

            nueva_venta = Venta(
                producto_id=producto_id,
                cantidad=cantidad,
                fecha_venta=fecha_venta,
                vendedor_id=vendedor_id,
                tipo_comprobante=tipo_comprobante,
                numero_comprobante=numero_comprobante,

            )
            db.session.add(nueva_venta)
            producto.cantidad -= cantidad
            db.session.commit()
            
            print(f"✅ Venta #{nueva_venta.id} registrada - Total: S/. {total_venta:.2f}")          
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

@app.route("/bloqueos")
@login_required
def ver_bloqueos():
    if session.get("rol") != "administrador":
        flash("❌ Solo administradores pueden ver bloqueos", "danger")
        return redirect(url_for("dashboard")) 
    try:

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

        bloqueos_lista = []
        
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
       
        bloqueo = db.session.execute(text("""
            SELECT * FROM bloqueos WHERE id = :id AND estado = 1
        """), {"id": bloqueo_id}).mappings().first()
        
        if not bloqueo:
            return jsonify({"success": False, "error": "Bloqueo no encontrado"}), 404
        
        
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

        limpiar_bloqueos_expirados()
        
       
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
        
        resultado = []
        emails_vistos = set()
        for b in bloqueos_bd:
            email = b['cliente_correo']
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
        
        for i in intentos_bloqueados:
            email = i['email']
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
        
        if session.get("rol") == "vendedor":
            vendedor_id = session.get("usuario_id")
            vendedor_filtro = vendedor_id
        else:
            vendedor_filtro = request.args.get('vendedor_id', type=int)
        
   
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


@app.route("/catalogo", methods=["GET"])
def catalogo_cliente():
    try:

        categoria_id = request.args.get('categoria', type=int)
        

        categorias = Categoria.query.filter_by(activo=True).all()
        
   
        query = Producto.query.filter(Producto.cantidad > 0)
        

        if categoria_id:
            query = query.filter(Producto.id_categoria == categoria_id)

            categoria_seleccionada = Categoria.query.get(categoria_id)
        else:
            categoria_seleccionada = None
        

        productos = query.order_by(Producto.nombre.asc()).all()
        
 
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







@app.route("/carrito")
def ver_carrito():
    return render_template("carrito.html")

@app.route("/checkout")
@login_required_cliente
def checkout():
    cliente = Cliente.query.get(session.get("cliente_id"))
    return render_template("checkout.html", 
                          cliente=cliente,
                          datetime=datetime)

@app.route("/pago")
@login_required_cliente
def pago():
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

        for item in data["items"]:
            producto = Producto.query.get(item["id"])
            if not producto:
                return jsonify({"success": False, "error": f'Producto no encontrado: {item["nombre"]}'})
            if producto.cantidad < item["cantidad"]:
                return jsonify({"success": False, "error": f'Stock insuficiente: {item["nombre"]}. Disponible: {producto.cantidad}'})
        

        cliente_data = data.get("cliente", {})
        

        cliente_nombres = cliente_data.get("nombres", "").strip()
        cliente_apellidos = cliente_data.get("apellidos", "").strip()
        cliente_email = cliente_data.get("email", "").strip()
        cliente_telefono = cliente_data.get("telefono", "").strip()
        

        cliente_documento = cliente_data.get("documento", "").strip()
        if not cliente_documento:
            cliente_documento = cliente_data.get("dni", "").strip()
        if not cliente_documento:
            cliente_documento = cliente_data.get("ruc", "").strip()
        
        # Datos de facturación (para RUC)
        cliente_razon_social = cliente_data.get("razon_social", "").strip()
        cliente_direccion_fiscal = cliente_data.get("direccion_fiscal", "").strip()  # ← AGREGAR

        cliente_direccion = data.get("direccion", "").strip()

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
        


        pedido = Pedido(
            cliente_id=session["cliente_id"],
            total=float(data["total"]),
            tipo_entrega=data["tipo_entrega"],
            direccion_entrega=cliente_direccion if data["tipo_entrega"] == "delivery" else "",
        )
        db.session.add(pedido)
        db.session.flush()
        

        productos_para_correo = []
        
        for item in data["items"]:
            producto = Producto.query.get(item["id"])
            subtotal = float(item["precio"]) * int(item["cantidad"])

            detalle = DetallePedido(
                pedido_id=pedido.id,
                producto_id=item["id"],
                cantidad=int(item["cantidad"]),
                precio_unitario=float(item["precio"]),
                subtotal=subtotal,
            )
            db.session.add(detalle)

            producto.cantidad -= int(item["cantidad"])

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
                cliente_direccion_fiscal=cliente_direccion_fiscal,  
                cliente_razon_social=cliente_razon_social,          
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

    search = request.args.get('search', '').strip()
    estado_filter = request.args.get('estado', '').strip()
    fecha_desde = request.args.get('fecha_desde', '').strip()
    fecha_hasta = request.args.get('fecha_hasta', '').strip()
    

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

    venta = Venta.query.filter_by(numero_comprobante=f"ONLINE-{pedido_id}").first()
    es_admin = session.get("rol") == "administrador"
    
    return render_template("pedido_detalle.html", 
                          pedido=pedido, 
                          detalles=detalles, 
                          cliente=cliente,  
                          venta=venta,      
                          es_admin=es_admin)
@app.route("/pedidos/cambiar-estado/<int:pedido_id>", methods=["POST"])
@login_required
def cambiar_estado_pedido(pedido_id):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    if session.get("rol") != "administrador":
        if is_ajax:
            return jsonify({"success": False, "error": "No autorizado"}), 403
        flash("❌ Solo administradores pueden cambiar estados", "danger")
        return redirect(url_for("ver_pedidos"))
    
    pedido = Pedido.query.get_or_404(pedido_id)
    nuevo_estado = request.form.get("estado")
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
        pedido.estado = nuevo_estado
        db.session.commit()
        
        mensaje = mensajes.get(nuevo_estado, f"✅ Pedido #{pedido_id} actualizado a: {nuevo_estado}")
        
        if is_ajax:
            return jsonify({
                "success": True,
                "message": mensaje,
                "estado": nuevo_estado,
                "pedido_id": pedido_id
            })
     
        flash(mensaje, "success")
        
     
        try:
            cliente = Cliente.query.get(pedido.cliente_id)
            if cliente and cliente.correo:
                print(f"📧 Enviando correo a {cliente.correo} sobre el pedido #{pedido_id}")
        except Exception as e:
            print(f"Error enviando correo: {e}")
            
    else:
        if is_ajax:
            return jsonify({"success": False, "error": f"Estado '{nuevo_estado}' no es válido"}), 400
        flash(f"❌ Estado '{nuevo_estado}' no es válido", "danger")
    
    return redirect(url_for("ver_pedidos"))


@app.route("/usuarios-sistema")
@login_required
def usuarios_sistema():
    """Panel de gestión de usuarios del sistema con bloqueo/desbloqueo"""
    if session.get("rol") != "administrador":
        flash("❌ Solo administradores pueden gestionar usuarios", "danger")
        return redirect(url_for("dashboard"))
    
    try:
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
        

        bloqueos_automaticos = {i['usuario_id']: i for i in intentos_bloqueados}
        usuarios_lista = []
        for u in usuarios:
            usuario_dict = dict(u)
            if u['id'] in bloqueos_automaticos:
                auto = bloqueos_automaticos[u['id']]
                usuario_dict['bloqueo_automatico'] = True
                usuario_dict['bloqueo_automatico_motivo'] = f"Bloqueo automático por {auto['intentos']} intentos fallidos"
                usuario_dict['bloqueo_automatico_fecha'] = auto['email_bloqueado']
                usuario_dict['bloqueo_automatico_id'] = auto['email']
            else:
                usuario_dict['bloqueo_automatico'] = False
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
import requests

@app.route("/api/consultar-dni/<dni>")
@login_required_cliente
def api_consultar_dni_cliente(dni):
    """Consulta DNI usando ApisPerú (URL correcta)"""
    if not dni.isdigit() or len(dni) != 8:
        return jsonify({"success": False, "error": "DNI inválido"}), 400
 
    cliente = Cliente.query.filter_by(dni=dni).first()
    if cliente:
        return jsonify({
            "success": True,
            "nombres": cliente.nombres,
            "apellidos": cliente.apellidos,
            "dni": cliente.dni,
            "origen": "base_datos"
        })

    try:
        
        url = f"https://dniruc.apisperu.com/api/v1/dni/{dni}"
        
        headers = {
            "Authorization": f"Bearer {API_PERU_TOKEN}",
            "Accept": "application/json"
        }
        
        print(f"🔍 Consultando DNI {dni} en ApisPerú...")
        print(f"📡 URL: {url}")
        
        response = requests.get(url, headers=headers, timeout=10)
        print(f"📡 Respuesta: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"📝 Datos recibidos: {data}")
            
          
            if data.get("nombres"):
                nombres = data.get("nombres", "")
                apellido_paterno = data.get("apellidoPaterno", "")
                apellido_materno = data.get("apellidoMaterno", "")
                
                return jsonify({
                    "success": True,
                    "nombres": nombres,
                    "apellidos": f"{apellido_paterno} {apellido_materno}".strip(),
                    "dni": dni,
                    "origen": "apis_peru"
                })
            elif data.get("Nombre"):
              
                return jsonify({
                    "success": True,
                    "nombres": data.get("Nombre", ""),
                    "apellidos": f"{data.get('ApellidoPaterno', '')} {data.get('ApellidoMaterno', '')}".strip(),
                    "dni": dni,
                    "origen": "apis_peru"
                })
            else:

                return jsonify({
                    "success": True,
                    "nombres": request.args.get("nombres", ""),
                    "apellidos": request.args.get("apellidos", ""),
                    "dni": dni,
                    "origen": "usuario",
                    "mensaje": "DNI válido pero sin nombres completos"
                })
        elif response.status_code == 404:
            return jsonify({
                "success": False,
                "error": "DNI no encontrado en RENIEC"
            }), 404
        else:
            return jsonify({
                "success": False,
                "error": f"Error al consultar DNI: {response.status_code}"
            }), 500
            
    except requests.exceptions.Timeout:
        print("❌ Timeout al consultar ApisPerú")
        return jsonify({"success": False, "error": "Tiempo de espera agotado"}), 500
    except requests.exceptions.RequestException as e:
        print(f"❌ Error de conexión: {e}")
        return jsonify({"success": False, "error": f"Error de conexión: {str(e)}"}), 500
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        return jsonify({"success": False, "error": f"Error inesperado: {str(e)}"}), 500

@app.route("/debug-token")
def debug_token():
    return jsonify({
        "token_existe": bool(API_PERU_TOKEN),
        "token_preview": API_PERU_TOKEN[:20] + "..." if API_PERU_TOKEN else None,
        "db_host": db_host
    })

@app.route("/api/consultar-ruc/<ruc>")
@login_required_cliente
def api_consultar_ruc_cliente(ruc):
    """Consulta RUC usando ApisPerú (URL correcta)"""
    if not ruc.isdigit() or len(ruc) != 11:
        return jsonify({"success": False, "error": "RUC inválido"}), 400
    

    empresa = RucEmpresa.query.filter_by(ruc=ruc).first()
    if empresa:
        return jsonify({
            "success": True,
            "razon_social": empresa.razon_social,
            "direccion": empresa.direccion or "",
            "ruc": ruc,
            "origen": "base_datos"
        })

    try:
   
        url = f"https://dniruc.apisperu.com/api/v1/ruc/{ruc}"
        
        headers = {
            "Authorization": f"Bearer {API_PERU_TOKEN}",
            "Accept": "application/json"
        }
        
        print(f"🔍 Consultando RUC {ruc} en ApisPerú...")
        response = requests.get(url, headers=headers, timeout=10)
        print(f"📡 Respuesta: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get("razonSocial"):
                razon_social = data.get("razonSocial", "")
                direccion = data.get("direccion", "")

                nueva_empresa = RucEmpresa(
                    ruc=ruc,
                    razon_social=razon_social,
                    direccion=direccion
                )
                db.session.add(nueva_empresa)
                db.session.commit()
                
                return jsonify({
                    "success": True,
                    "razon_social": razon_social,
                    "direccion": direccion,
                    "ruc": ruc,
                    "origen": "apis_peru"
                })
            elif data.get("RazonSocial"):

                return jsonify({
                    "success": True,
                    "razon_social": data.get("RazonSocial", ""),
                    "direccion": data.get("Direccion", ""),
                    "ruc": ruc,
                    "origen": "apis_peru"
                })
            else:
                return jsonify({
                    "success": False,
                    "error": "RUC no encontrado en SUNAT"
                }), 404
        elif response.status_code == 404:
            return jsonify({
                "success": False,
                "error": "RUC no encontrado en SUNAT"
            }), 404
        else:
            return jsonify({
                "success": False,
                "error": f"Error al consultar RUC: {response.status_code}"
            }), 500
            
    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "Tiempo de espera agotado"}), 500
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "error": f"Error de conexión: {str(e)}"}), 500

@app.route("/acerca-de")
def acerca_de():
    return render_template("acerca_de.html")

@app.route("/contacto")
def contacto():
    return render_template("contacto.html")



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
    

    top_productos = db.session.query(
        Producto.nombre,
        func.sum(Venta.cantidad).label('total_vendido')
    ).join(Venta).filter(
        func.date(Venta.fecha_venta) >= hace_30_dias.date()
    ).group_by(Producto.id).order_by(func.sum(Venta.cantidad).desc()).limit(5).all()
    

    stock_bajo = Producto.query.filter(Producto.cantidad <= 10, Producto.cantidad > 0).order_by(Producto.cantidad.asc()).limit(10).all()
    stock_critico = Producto.query.filter(Producto.cantidad == 0).order_by(Producto.nombre.asc()).limit(10).all()

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
    

    graph_ventas = json.dumps(fig_ventas, cls=plotly.utils.PlotlyJSONEncoder)
    graph_top = json.dumps(fig_top, cls=plotly.utils.PlotlyJSONEncoder)
    graph_cat = json.dumps(fig_cat, cls=plotly.utils.PlotlyJSONEncoder)
    graph_estados = json.dumps(fig_estados, cls=plotly.utils.PlotlyJSONEncoder)
    

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

with app.app_context():
    try:
        # Verificar si las columnas existen
        from sqlalchemy import text
        
        columnas = ['cliente_nombres', 'cliente_apellidos', 'cliente_documento', 
                   'cliente_email', 'cliente_direccion', 'cliente_direccion_fiscal', 
                   'cliente_razon_social']
        
        for col in columnas:
            result = db.session.execute(text(f"""
                SELECT COUNT(*) FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = 'librospe_db' 
                AND TABLE_NAME = 'ventas' 
                AND COLUMN_NAME = '{col}'
            """))
            existe = result.scalar()
            
            if existe == 0:
                tipo = 'VARCHAR(100)' if col in ['cliente_nombres', 'cliente_apellidos', 'cliente_email'] else \
                       'VARCHAR(20)' if col == 'cliente_documento' else \
                       'VARCHAR(200)' if col == 'cliente_razon_social' else 'TEXT'
                
                db.session.execute(text(f"""
                    ALTER TABLE ventas ADD COLUMN {col} {tipo} NULL
                """))
                print(f"✅ Columna {col} agregada")
        
        db.session.commit()
        print("✅ Todas las columnas agregadas correctamente")
        
    except Exception as e:
        print(f"⚠️ Error al agregar columnas: {e}")
        db.session.rollback()
        
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
application = app

