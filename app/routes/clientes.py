# app/routes/clientes.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app import db, bcrypt
from app.models import Cliente
from app.utils import (
    login_required_cliente, obtener_ip_cliente, registrar_intento_fallido,
    verificar_bloqueo_ip, verificar_bloqueo_email, limpiar_bloqueos_expirados,
    limpiar_intentos_exitosos, generar_token_recuperacion
)
from datetime import datetime, timedelta
import requests

clientes_bp = Blueprint('clientes', __name__)

@clientes_bp.route('/login-cliente', methods=['GET', 'POST'])
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

@clientes_bp.route('/registro-cliente', methods=['GET', 'POST'])
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
                correo=request.form["email"],
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

@clientes_bp.route('/logout-cliente')
def logout_cliente():
    session.clear()
    flash("✅ Sesión cerrada", "success")
    return redirect(url_for('clientes.login_cliente'))  # o a '/catalogo'

@clientes_bp.route('/cliente/perfil')
@login_required_cliente
def cliente_perfil():
    cliente = Cliente.query.get(session["cliente_id"])
    if not cliente:
        flash("❌ Cliente no encontrado", "danger")
        return redirect(url_for("logout_cliente"))
    return render_template("cliente_perfil.html", cliente=cliente)

@clientes_bp.route('/cliente/actualizar-perfil', methods=['POST'])
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

@clientes_bp.route('/cliente/cambiar-contrasena', methods=['GET', 'POST'])
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

@clientes_bp.route('/recuperar-contrasena', methods=['GET', 'POST'])
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

@clientes_bp.route('/resetear-contrasena/<token>', methods=['GET', 'POST'])
def resetear_contrasena(token):
    # ...
    pass