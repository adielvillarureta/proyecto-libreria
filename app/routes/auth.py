# app/routes/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app import db, bcrypt
from app.models import UsuarioSistema, IntentosLogin
from app.utils import (
    login_required, admin_required, obtener_ip_cliente,
    registrar_intento_fallido, verificar_bloqueo_ip, verificar_bloqueo_email,
    limpiar_bloqueos_expirados, limpiar_intentos_exitosos
)
from sqlalchemy import text
from datetime import datetime

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
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
                        return redirect(url_for("auth.login"))
                    return render_template("login.html")

                bloqueo = db.session.execute(text("""
                    SELECT id, motivo, fecha_bloqueo
                    FROM bloqueos
                    WHERE usuario_sistema_id = :usuario_id
                    AND tipo_usuario = 'sistema'
                    AND estado = 1
                """), {"usuario_id": usuario.id}).mappings().first()

                if bloqueo:
                    flash("⛔ CUENTA BLOQUEADA", "danger")
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
                    flash("⛔ CUENTA BLOQUEADA TEMPORALMENTE", "danger")
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
                    return redirect(url_for("productos.listar_productos"))
                else:
                    resultado = registrar_intento_fallido(correo, ip_cliente, es_cliente=False)
                    if resultado.get("bloqueado"):
                        flash(f"⛔ {resultado['mensaje']}", "danger")
                        if resultado["tipo"] == "ip":
                            flash("⚠️ A partir de ahora, NINGÚN usuario podrá iniciar sesión desde esta IP durante 10 minutos.", "warning")
                            return redirect(url_for("auth.login"))
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
        flash("❌ Error interno del servidor", "danger")
        return render_template("login.html")


@auth_bp.route('/logout')
@login_required
def logout():
    session.clear()
    flash("✅ Sesión cerrada", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route('/usuarios/nuevo', methods=['GET', 'POST'])
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
            return redirect(url_for("productos.listar_proveedores"))
        except Exception:
            db.session.rollback()
            flash("❌ Error: El correo ya existe", "danger")
            return redirect(url_for("auth.nuevo_usuario"))
    return render_template("usuarios_sistema_form.html")


@auth_bp.route('/usuario/bloquear/<int:usuario_id>', methods=['POST'])
@login_required
def bloquear_usuario_sistema(usuario_id):
    if session.get("rol") != "administrador":
        flash("❌ No autorizado", "danger")
        return redirect(url_for("auth.usuarios_sistema"))

    motivo = request.form.get("motivo", "Bloqueo manual por administrador")
    try:
        usuario = UsuarioSistema.query.get(usuario_id)
        if not usuario:
            flash("❌ Usuario no encontrado", "danger")
            return redirect(url_for("auth.usuarios_sistema"))

        existe = db.session.execute(text("""
            SELECT id FROM bloqueos
            WHERE usuario_sistema_id = :usuario_id
            AND tipo_usuario = 'sistema'
            AND estado = 1
        """), {"usuario_id": usuario_id}).fetchone()

        if existe:
            flash("⚠️ El usuario ya está bloqueado", "warning")
            return redirect(url_for("auth.usuarios_sistema"))

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
    return redirect(url_for("auth.usuarios_sistema"))


@auth_bp.route('/usuario/desbloquear/<int:usuario_id>', methods=['POST'])
@login_required
def desbloquear_usuario_sistema(usuario_id):
    if session.get("rol") != "administrador":
        flash("❌ No autorizado", "danger")
        return redirect(url_for("auth.usuarios_sistema"))

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
    return redirect(url_for("auth.usuarios_sistema"))


@auth_bp.route('/cambiar_clave', methods=['GET', 'POST'])
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
        return redirect(url_for("productos.listar_productos"))

    return render_template("cambiar_clave.html")


@auth_bp.route('/usuarios-sistema')
@login_required
def usuarios_sistema():
    if session.get("rol") != "administrador":
        flash("❌ Solo administradores pueden gestionar usuarios", "danger")
        return redirect(url_for("main.dashboard"))

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