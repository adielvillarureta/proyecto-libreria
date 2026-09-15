# app/routes/bloqueos.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app import db
from app.models import Bloqueo, IntentosLogin
from app.utils import login_required, limpiar_bloqueos_expirados
from sqlalchemy import text
from datetime import datetime

bloqueos_bp = Blueprint('bloqueos', __name__)

@bloqueos_bp.route('/bloqueos')
@login_required
def ver_bloqueos():
    if session.get("rol") != "administrador":
        flash("❌ Solo administradores pueden ver bloqueos", "danger")
        return redirect(url_for("main.dashboard"))

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
            bloqueos_lista.append({
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
            })
        for b in bloqueos_temporales:
            bloqueos_lista.append({
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
            })

        return render_template("bloqueos.html", bloqueos=bloqueos_lista)
    except Exception as e:
        print(f"❌ Error en bloqueos: {e}")
        flash(f"Error al cargar bloqueos: {e}", "danger")
        return render_template("bloqueos.html", bloqueos=[])

@bloqueos_bp.route('/bloqueos-sistema')
@login_required
def ver_bloqueos_sistema():
    if session.get("rol") != "administrador":
        flash("❌ Solo administradores pueden ver bloqueos", "danger")
        return redirect(url_for("main.dashboard"))

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
        for b in bloqueos_sistema:
            bloqueos_lista.append({
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
            })
        for i in intentos_sistema:
            bloqueos_lista.append({
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
            })

        return render_template("bloqueos_sistema.html", bloqueos=bloqueos_lista)
    except Exception as e:
        print(f"❌ Error en bloqueos_sistema: {e}")
        flash(f"Error al cargar bloqueos: {e}", "danger")
        return render_template("bloqueos_sistema.html", bloqueos=[])

@bloqueos_bp.route('/desbloquear-intento-login', methods=['POST'])
@login_required
def desbloquear_intento_login():
    if session.get("rol") != "administrador":
        flash("❌ No autorizado", "danger")
        return redirect(url_for("bloqueos.ver_bloqueos"))

    email = request.form.get("email")
    if not email:
        flash("❌ Email no proporcionado", "danger")
        return redirect(url_for("bloqueos.ver_bloqueos"))

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
    return redirect(url_for("bloqueos.ver_bloqueos"))

@bloqueos_bp.route('/bloqueos/desbloquear/<int:bloqueo_id>', methods=['POST'])
@login_required
def desbloquear_usuario_admin(bloqueo_id):
    if session.get("rol") != "administrador":
        return jsonify({"success": False, "error": "No autorizado"}), 403

    try:
        bloqueo = db.session.execute(text("SELECT * FROM bloqueos WHERE id = :id AND estado = 1"), {"id": bloqueo_id}).mappings().first()
        if not bloqueo:
            return jsonify({"success": False, "error": "Bloqueo no encontrado"}), 404

        db.session.execute(text("CALL desbloquear_usuario(:bloqueo_id, :admin_id)"),
                           {"bloqueo_id": bloqueo_id, "admin_id": session["usuario_id"]})
        db.session.commit()
        return jsonify({"success": True, "message": "Usuario desbloqueado exitosamente"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@bloqueos_bp.route('/bloqueos/desbloquear', methods=['POST'])
@login_required
def desbloquear_usuario_form():
    if session.get("rol") != "administrador":
        flash("❌ No autorizado", "danger")
        return redirect(url_for("bloqueos.ver_bloqueos"))

    bloqueo_id = request.form.get("bloqueo_id")
    if not bloqueo_id:
        flash("❌ ID de bloqueo no proporcionado", "danger")
        return redirect(url_for("bloqueos.ver_bloqueos"))

    try:
        db.session.execute(text("CALL desbloquear_usuario(:bloqueo_id, :admin_id)"),
                           {"bloqueo_id": bloqueo_id, "admin_id": session["usuario_id"]})
        db.session.commit()
        flash("✅ Usuario desbloqueado exitosamente", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al desbloquear: {str(e)}", "danger")
    return redirect(url_for("bloqueos.ver_bloqueos"))

@bloqueos_bp.route('/api/bloqueos')
@login_required
def api_bloqueos():
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