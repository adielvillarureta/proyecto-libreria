# app/routes/clientes.py
import secrets
import requests
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app
from urllib.parse import urlencode
from app import db, bcrypt
from app.models import Cliente, IntentosLogin, Pedido
from app.utils import (
    login_required_cliente, obtener_ip_cliente, registrar_intento_fallido,
    verificar_bloqueo_ip, verificar_bloqueo_email, limpiar_bloqueos_expirados,
    limpiar_intentos_exitosos, generar_token_recuperacion
)
from sqlalchemy import text
from datetime import datetime, timedelta

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
                return redirect(url_for("clientes.login_cliente"))
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
                if intentos_restantes > 0 and intentos_restantes != 999:
                    if intentos_restantes <= 1:
                        flash(f"⚠️ ¡ATENCIÓN! Contraseña incorrecta. Te queda {intentos_restantes} intento para bloqueo TEMPORAL.", "danger")
                        flash(f"💡 Si fallas 2 veces más (total {intentos_totales + 2} de 5), tu cuenta será BLOQUEADA PERMANENTEMENTE.", "warning")
                    else:
                        flash(f"❌ Contraseña incorrecta. Te quedan {intentos_restantes} intentos para bloqueo TEMPORAL.", "danger")
                        flash(f"ℹ️ Intentos totales: {intentos_totales} de 5. Si llegas a 5, tu cuenta será BLOQUEADA PERMANENTEMENTE.", "info")
                else:
                    if intentos_totales >= 4:
                        flash("⚠️ ¡ÚLTIMO INTENTO! Contraseña incorrecta. Si fallas una vez más (5 de 5), tu cuenta será BLOQUEADA PERMANENTEMENTE.", "danger")
                    else:
                        flash("❌ Contraseña incorrecta. Próximo intento (3 de 3) bloqueará la cuenta TEMPORALMENTE por 10 minutos.", "warning")
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


@clientes_bp.route('/registro-cliente', methods=['GET', 'POST'])
def registro_cliente():
    if request.method == "POST":
        # 1. Validar que las contraseñas coincidan
        clave = request.form.get("clave")
        confirmar = request.form.get("confirmar_clave")
        if clave != confirmar:
            flash("❌ Las contraseñas no coinciden", "danger")
            return redirect(url_for("clientes.registro_cliente"))

        try:
            # 2. Validar que el correo no esté registrado
            existe = Cliente.query.filter_by(correo=request.form["email"]).first()
            if existe:
                flash("❌ El correo ya está registrado", "danger")
                return redirect(url_for("clientes.registro_cliente"))

            # 2b. Validar que el DNI no esté registrado
            dni_ingresado = (request.form.get("dni") or "").strip()
            if dni_ingresado:
                existe_dni = Cliente.query.filter_by(dni=dni_ingresado).first()
                if existe_dni:
                    flash(f"❌ El DNI {dni_ingresado} ya está registrado con otra cuenta. Verifica tu número de documento.", "danger")
                    return redirect(url_for("clientes.registro_cliente"))

            # 3. Crear el nuevo cliente
            cliente = Cliente(
                dni=dni_ingresado or None,
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
            return redirect(url_for("clientes.login_cliente"))
        except Exception as e:
            db.session.rollback()
            flash(f"❌ Error al registrar: {str(e)}", "danger")
            return render_template("registro_cliente.html")

    # ✅ CORREGIDO: Petición GET simplemente muestra el formulario (sin redirigir)
    return render_template("registro_cliente.html")


@clientes_bp.route('/logout-cliente')
def logout_cliente():
    session.clear()
    flash("✅ Sesión cerrada", "success")
    return redirect("/catalogo")


@clientes_bp.route('/cliente/perfil')
@login_required_cliente
def cliente_perfil():
    cliente = Cliente.query.get(session["cliente_id"])
    if not cliente:
        flash("❌ Cliente no encontrado", "danger")
        return redirect(url_for("clientes.logout_cliente"))

    pedidos = Pedido.query.filter_by(cliente_id=cliente.id).order_by(Pedido.fecha_pedido.desc()).all()
    total_pedidos = len(pedidos)
    completados = sum(1 for p in pedidos if p.estado in ('entregado', 'recogido'))
    en_proceso = sum(1 for p in pedidos if p.estado in ('confirmado', 'preparando', 'enviado', 'listo_tienda'))
    pendientes = sum(1 for p in pedidos if p.estado == 'pendiente')
    total_gastado = sum(p.total or 0 for p in pedidos)

    return render_template(
        "cliente_perfil.html",
        cliente=cliente,
        pedidos=pedidos[:3],
        total_pedidos=total_pedidos,
        completados=completados,
        en_proceso=en_proceso,
        pendientes=pendientes,
        total_gastado=total_gastado,
    )


@clientes_bp.route('/cliente/actualizar-perfil', methods=['POST'])
@login_required_cliente
def cliente_actualizar_perfil():
    cliente = Cliente.query.get(session["cliente_id"])
    if not cliente:
        flash("❌ Sesión inválida. Inicia sesión de nuevo.", "danger")
        return redirect(url_for("clientes.login_cliente"))

    try:
        cliente.nombres = request.form.get("nombres")
        cliente.apellidos = request.form.get("apellidos")
        cliente.telefono = request.form.get("telefono")
        cliente.direccion = request.form.get("direccion")
        cliente.dni = request.form.get("dni")

        nuevo_correo = request.form.get("correo")
        if nuevo_correo and nuevo_correo != cliente.correo:
            existe = Cliente.query.filter_by(correo=nuevo_correo).first()
            if existe:
                flash("❌ El correo ya está registrado por otro usuario", "danger")
                return redirect(url_for("clientes.cliente_perfil"))
            cliente.correo = nuevo_correo
            session["cliente_correo"] = nuevo_correo

        db.session.commit()

        session["cliente_nombres"] = cliente.nombres
        session["cliente_apellidos"] = cliente.apellidos
        session["cliente_telefono"] = cliente.telefono
        session["cliente_direccion"] = cliente.direccion
        session["cliente_dni"] = cliente.dni

        flash("✅ Perfil actualizado correctamente", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al actualizar: {str(e)}", "danger")

    return redirect(url_for("clientes.cliente_perfil"))


@clientes_bp.route('/cliente/cambiar-contrasena', methods=['GET', 'POST'])
@login_required_cliente
def cliente_cambiar_contrasena():
    if request.method == "POST":
        contrasena_actual = request.form.get("contrasena_actual")
        nueva_contrasena = request.form.get("nueva_contrasena")
        confirmar_contrasena = request.form.get("confirmar_contrasena")

        if not contrasena_actual or not nueva_contrasena or not confirmar_contrasena:
            flash("❌ Todos los campos son obligatorios", "danger")
            return redirect(url_for("clientes.cliente_cambiar_contrasena"))

        if nueva_contrasena != confirmar_contrasena:
            flash("❌ Las contraseñas no coinciden", "danger")
            return redirect(url_for("clientes.cliente_cambiar_contrasena"))

        if len(nueva_contrasena) < 6:
            flash("❌ La contraseña debe tener al menos 6 caracteres", "danger")
            return redirect(url_for("clientes.cliente_cambiar_contrasena"))

        cliente = Cliente.query.get(session["cliente_id"])

        if not bcrypt.check_password_hash(cliente.clave, contrasena_actual):
            flash("❌ Contraseña actual incorrecta", "danger")
            return redirect(url_for("clientes.cliente_cambiar_contrasena"))

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
            return redirect(url_for("clientes.recuperar_contrasena"))

        cliente = Cliente.query.filter_by(correo=email).first()

        if cliente:
            token = generar_token_recuperacion()
            cliente.token_recuperacion = token
            cliente.token_expiracion = datetime.now() + timedelta(hours=1)
            db.session.commit()

            base_url = current_app.config.get("BASE_URL", "")
            if base_url:
                enlace = base_url + url_for("clientes.resetear_contrasena", token=token)
            else:
                enlace = url_for("clientes.resetear_contrasena", token=token, _external=True)
            flash(f"✅ Enlace de recuperación: {enlace}", "info")
        else:
            flash("✅ Si el correo está registrado, recibirás un enlace", "success")

        return redirect(url_for("clientes.login_cliente"))

    return render_template("recuperar_contrasena.html")


@clientes_bp.route('/resetear-contrasena/<token>', methods=['GET', 'POST'])
def resetear_contrasena(token):
    cliente = Cliente.query.filter_by(token_recuperacion=token).first()

    if not cliente:
        flash("❌ Enlace inválido o ya utilizado", "danger")
        return redirect(url_for("clientes.login_cliente"))

    if cliente.token_expiracion < datetime.now():
        flash("❌ El enlace ha expirado", "danger")
        return redirect(url_for("clientes.recuperar_contrasena"))

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
            return redirect(url_for("clientes.login_cliente"))
        except Exception as e:
            db.session.rollback()
            flash(f"❌ Error: {str(e)}", "danger")

    return render_template("resetear_contrasena.html", token=token)


def _oauth_redirect_uri(endpoint, override_key):
    """Devuelve la URI de callback de OAuth: prioriza la configurada en .env (p. ej. HTTPS/ngrok),
    y si no existe usa la URL desde la que el usuario entró."""
    base_url = current_app.config.get("BASE_URL", "")
    override = current_app.config.get(override_key, "")
    if override:
        return override
    if base_url:
        return base_url + url_for(endpoint)
    return request.url_root.rstrip("/") + url_for(endpoint)


@clientes_bp.route('/auth/google')
def auth_google():
    client_id = current_app.config.get("GOOGLE_CLIENT_ID", "")
    if not client_id:
        flash("🚧 El inicio de sesión con Google estará disponible próximamente. Mientras tanto, registra tu cuenta con el formulario.", "warning")
        return redirect(url_for("clientes.login_cliente"))

    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    redirect_uri = _oauth_redirect_uri("clientes.auth_google_callback", "GOOGLE_REDIRECT_URI")

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    })
    return redirect(auth_url)


@clientes_bp.route('/auth/google/callback')
def auth_google_callback():
    error = request.args.get("error")
    if error:
        flash(f"❌ Google: {error}. Intenta de nuevo o usa otro método.", "danger")
        return redirect(url_for("clientes.login_cliente"))

    code = request.args.get("code")
    state = request.args.get("state")
    if not code or state != session.get("oauth_state"):
        flash("❌ La autenticación con Google falló (estado no válido).", "danger")
        return redirect(url_for("clientes.login_cliente"))

    client_id = current_app.config.get("GOOGLE_CLIENT_ID", "")
    client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = _oauth_redirect_uri("clientes.auth_google_callback", "GOOGLE_REDIRECT_URI")

    try:
        resp = requests.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }, timeout=15)
        token_data = resp.json()
    except requests.RequestException:
        flash("❌ No se pudo conectar con Google. Revisa tu conexión e inténtalo de nuevo.", "danger")
        return redirect(url_for("clientes.login_cliente"))

    access_token = token_data.get("access_token")
    if not access_token:
        flash(f"❌ Google no devolvió un token válido: {token_data.get('error_description') or 'error desconocido'}", "danger")
        return redirect(url_for("clientes.login_cliente"))

    try:
        info = requests.get("https://www.googleapis.com/oauth2/v3/userinfo",
                            headers={"Authorization": f"Bearer {access_token}"}, timeout=15).json()
    except requests.RequestException:
        flash("❌ No se pudo obtener tu perfil de Google.", "danger")
        return redirect(url_for("clientes.login_cliente"))

    email = (info.get("email") or "").lower()
    nombre_completo = info.get("name") or ""
    nombres = info.get("given_name") or (nombre_completo.split(" ")[0] if nombre_completo else "Usuario")
    apellidos = info.get("family_name") or (" ".join(nombre_completo.split(" ")[1:]) if nombre_completo else "Google")
    return _registrar_o_ingresar("Google", email, nombres, apellidos)


@clientes_bp.route('/auth/facebook')
def auth_facebook():
    app_id = current_app.config.get("FACEBOOK_APP_ID", "")
    if not app_id:
        flash("🚧 El inicio de sesión con Facebook estará disponible próximamente. Mientras tanto, registra tu cuenta con el formulario.", "warning")
        return redirect(url_for("clientes.login_cliente"))

    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    redirect_uri = _oauth_redirect_uri("clientes.auth_facebook_callback", "FACEBOOK_REDIRECT_URI")

    auth_url = "https://www.facebook.com/v19.0/dialog/oauth?" + urlencode({
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": "email,public_profile",
    })
    return redirect(auth_url)


@clientes_bp.route('/auth/facebook/callback')
def auth_facebook_callback():
    error = request.args.get("error")
    if error:
        flash(f"❌ Facebook: {error}. Intenta de nuevo o usa otro método.", "danger")
        return redirect(url_for("clientes.login_cliente"))

    code = request.args.get("code")
    state = request.args.get("state")
    if not code or state != session.get("oauth_state"):
        flash("❌ La autenticación con Facebook falló (estado no válido).", "danger")
        return redirect(url_for("clientes.login_cliente"))

    app_id = current_app.config.get("FACEBOOK_APP_ID", "")
    app_secret = current_app.config.get("FACEBOOK_APP_SECRET", "")
    redirect_uri = _oauth_redirect_uri("clientes.auth_facebook_callback", "FACEBOOK_REDIRECT_URI")

    try:
        token_data = requests.get("https://graph.facebook.com/v19.0/oauth/access_token", params={
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "client_secret": app_secret,
            "code": code,
        }, timeout=15).json()
    except requests.RequestException:
        flash("❌ No se pudo conectar con Facebook. Revisa tu conexión e inténtalo de nuevo.", "danger")
        return redirect(url_for("clientes.login_cliente"))

    access_token = token_data.get("access_token")
    if not access_token:
        flash(f"❌ Facebook no devolvió un token válido: {token_data.get('error', {}).get('message', 'error desconocido')}", "danger")
        return redirect(url_for("clientes.login_cliente"))

    try:
        info = requests.get("https://graph.facebook.com/me", params={
            "fields": "id,name,email,first_name,last_name",
            "access_token": access_token,
        }, timeout=15).json()
    except requests.RequestException:
        flash("❌ No se pudo obtener tu perfil de Facebook.", "danger")
        return redirect(url_for("clientes.login_cliente"))

    email = (info.get("email") or "").lower()
    nombre_completo = info.get("name") or ""
    nombres = info.get("first_name") or (nombre_completo.split(" ")[0] if nombre_completo else "Usuario")
    apellidos = info.get("last_name") or (" ".join(nombre_completo.split(" ")[1:]) if nombre_completo else "Facebook")
    return _registrar_o_ingresar("Facebook", email, nombres, apellidos)


def _registrar_o_ingresar(proveedor, email, nombres, apellidos):
    """Encuentra el cliente por correo o lo crea, y luego inicia sesión."""
    cliente = None
    if email:
        cliente = Cliente.query.filter_by(correo=email).first()

    if not cliente:
        if not email:
            flash(f"❌ Tu cuenta de {proveedor} no tiene un correo público asociado. Crea tu cuenta manualmente.", "danger")
            return redirect(url_for("clientes.registro_cliente"))
        cliente = Cliente(
            nombres=nombres or "Usuario",
            apellidos=apellidos or proveedor,
            correo=email,
            clave=bcrypt.generate_password_hash(secrets.token_urlsafe(24)).decode("utf-8"),
        )
        db.session.add(cliente)
        db.session.commit()
        flash(f"✅ Cuenta creada correctamente con {proveedor}. ¡Bienvenido!", "success")

    session["cliente_id"] = cliente.id
    session["cliente_nombres"] = cliente.nombres
    session["cliente_apellidos"] = cliente.apellidos
    session["cliente_correo"] = cliente.correo
    session["cliente_telefono"] = cliente.telefono
    session["cliente_direccion"] = cliente.direccion
    session["cliente_dni"] = cliente.dni
    flash(f"✅ ¡Bienvenido {cliente.nombres}!", "success")
    return redirect("/catalogo")