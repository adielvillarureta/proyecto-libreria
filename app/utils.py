# utils.py
# app/utils.py
import os
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
from datetime import datetime, timedelta
from flask import session, request, flash, redirect, url_for, jsonify
from sqlalchemy import text

# --- IMPORTACIONES CORREGIDAS ---
from app import db
from app.models import (Cliente, UsuarioSistema, IntentosLogin, Bloqueo,
                        Producto, Venta, RucEmpresa)
from app.config import Config
# --------------------------------
def obtener_ip_cliente():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr

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
    from app.config import ALLOWED_EXTENSIONS
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def generar_token_recuperacion():
    return secrets.token_urlsafe(32)

# ---- Funciones de bloqueo ----
def registrar_intento_fallido(email, ip, es_cliente=False):
    ahora = datetime.now()
    if es_cliente:
        email_existe = Cliente.query.filter_by(correo=email).first() is not None
    else:
        email_existe = UsuarioSistema.query.filter_by(correo=email).first() is not None

    ip_bloqueada = IntentosLogin.query.filter(
        IntentosLogin.ip == ip,
        IntentosLogin.ips_bloqueadas > ahora
    ).first()
    if ip_bloqueada:
        return {"bloqueado": True, "tipo": "ip", "mensaje": "IP bloqueada por 10 minutos"}

    if not email_existe:
        registro = IntentosLogin.query.filter_by(email=email).first()
        if not registro:
            registro = IntentosLogin(email=email, ip=ip, intentos=1, ultimo_intento=ahora,
                                     usuarios_distintos=0, intentos_totales=1)
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
            IntentosLogin.query.filter(IntentosLogin.ip == ip).update(
                {IntentosLogin.ips_bloqueadas: ahora + timedelta(minutes=10)})
            db.session.commit()
            return {"bloqueado": True, "tipo": "ip", "mensaje": "IP bloqueada por 10 minutos (múltiples intentos con emails inexistentes)"}
        return {"bloqueado": False, "intentos_restantes": 999, "email_no_existe": True}

    registro = IntentosLogin.query.filter_by(email=email).first()
    if not registro:
        registro = IntentosLogin(email=email, ip=ip, intentos=1, ultimo_intento=ahora,
                                 usuarios_distintos=1, intentos_totales=1)
        db.session.add(registro)
        db.session.commit()
        return {"bloqueado": False, "intentos_restantes": 2, "intentos_totales": 1}

    emails_desde_ip = db.session.execute(
        text("SELECT COUNT(DISTINCT email) FROM intentos_login WHERE ip = :ip AND email != :email"),
        {"ip": ip, "email": email}).scalar()
    if emails_desde_ip > 0:
        existe_email_ip = db.session.execute(
            text("SELECT COUNT(*) FROM intentos_login WHERE ip = :ip AND email = :email"),
            {"ip": ip, "email": email}).scalar()
        registro.usuarios_distintos = emails_desde_ip + 1 if existe_email_ip == 0 else emails_desde_ip
    else:
        registro.usuarios_distintos = 1

    registro.intentos += 1
    registro.intentos_totales += 1
    registro.ultimo_intento = ahora
    registro.ip = ip

    if registro.usuarios_distintos >= 2 and not registro.ips_bloqueadas:
        registro.ips_bloqueadas = ahora + timedelta(minutes=10)
        db.session.commit()
        return {"bloqueado": True, "tipo": "ip", "mensaje": "IP bloqueada por 10 minutos (múltiples usuarios desde la misma IP)"}

    if es_cliente:
        bloqueo_permanente = db.session.execute(
            text("SELECT id FROM bloqueos WHERE cliente_id = (SELECT id FROM clientes WHERE correo = :email) "
                 "AND tipo_usuario = 'cliente' AND estado = 1 AND permanente = 1"),
            {"email": email}).fetchone()
    else:
        bloqueo_permanente = db.session.execute(
            text("SELECT id FROM bloqueos WHERE usuario_sistema_id = (SELECT id FROM usuarios_sistema WHERE correo = :email) "
                 "AND tipo_usuario = 'sistema' AND estado = 1 AND permanente = 1"),
            {"email": email}).fetchone()
    if bloqueo_permanente:
        db.session.commit()
        return {"bloqueado": True, "tipo": "permanente", "mensaje": "CUENTA BLOQUEADA PERMANENTEMENTE. Contacta al administrador."}

    if registro.intentos >= 3 and not registro.email_bloqueado:
        registro.email_bloqueado = ahora + timedelta(minutes=10)
        if es_cliente:
            cliente = Cliente.query.filter_by(correo=email).first()
            if cliente:
                existe_bloqueo = db.session.execute(
                    text("SELECT id FROM bloqueos WHERE cliente_id = :cliente_id AND tipo_usuario = 'cliente' AND estado = 1 AND permanente = 0"),
                    {"cliente_id": cliente.id}).fetchone()
                if not existe_bloqueo:
                    db.session.execute(
                        text("INSERT INTO bloqueos (tipo_usuario, cliente_id, motivo, fecha_bloqueo, bloqueado_por, estado, permanente, minutos_bloqueo) "
                             "VALUES ('cliente', :cliente_id, :motivo, NOW(), 1, 1, 0, 10)"),
                        {"cliente_id": cliente.id, "motivo": "Bloqueo temporal por 3 intentos fallidos de login"})
        else:
            usuario = UsuarioSistema.query.filter_by(correo=email).first()
            if usuario:
                existe_bloqueo = db.session.execute(
                    text("SELECT id FROM bloqueos WHERE usuario_sistema_id = :usuario_id AND tipo_usuario = 'sistema' AND estado = 1 AND permanente = 0"),
                    {"usuario_id": usuario.id}).fetchone()
                if not existe_bloqueo:
                    db.session.execute(
                        text("INSERT INTO bloqueos (tipo_usuario, usuario_sistema_id, motivo, fecha_bloqueo, bloqueado_por, estado, permanente, minutos_bloqueo) "
                             "VALUES ('sistema', :usuario_id, :motivo, NOW(), 1, 1, 0, 10)"),
                        {"usuario_id": usuario.id, "motivo": "Bloqueo temporal por 3 intentos fallidos de login"})
        db.session.commit()
        return {"bloqueado": True, "tipo": "email", "mensaje": "Correo bloqueado temporalmente por 10 minutos. 3 intentos fallidos."}

    if registro.intentos_totales >= 5:
        registro.email_bloqueado = None
        registro.intentos = 0
        db.session.commit()
        if es_cliente:
            cliente = Cliente.query.filter_by(correo=email).first()
            if cliente:
                existe_permanente = db.session.execute(
                    text("SELECT id FROM bloqueos WHERE cliente_id = :cliente_id AND tipo_usuario = 'cliente' AND estado = 1 AND permanente = 1"),
                    {"cliente_id": cliente.id}).fetchone()
                if not existe_permanente:
                    db.session.execute(
                        text("INSERT INTO bloqueos (tipo_usuario, cliente_id, motivo, fecha_bloqueo, bloqueado_por, estado, permanente) "
                             "VALUES ('cliente', :cliente_id, :motivo, NOW(), 1, 1, 1)"),
                        {"cliente_id": cliente.id, "motivo": "BLOQUEO PERMANENTE por 5 intentos fallidos de login"})
        else:
            usuario = UsuarioSistema.query.filter_by(correo=email).first()
            if usuario:
                existe_permanente = db.session.execute(
                    text("SELECT id FROM bloqueos WHERE usuario_sistema_id = :usuario_id AND tipo_usuario = 'sistema' AND estado = 1 AND permanente = 1"),
                    {"usuario_id": usuario.id}).fetchone()
                if not existe_permanente:
                    db.session.execute(
                        text("INSERT INTO bloqueos (tipo_usuario, usuario_sistema_id, motivo, fecha_bloqueo, bloqueado_por, estado, permanente) "
                             "VALUES ('sistema', :usuario_id, :motivo, NOW(), 1, 1, 1)"),
                        {"usuario_id": usuario.id, "motivo": "BLOQUEO PERMANENTE por 5 intentos fallidos de login"})
        db.session.commit()
        return {"bloqueado": True, "tipo": "permanente", "mensaje": "CUENTA BLOQUEADA PERMANENTEMENTE por 5 intentos fallidos. Contacta al administrador."}

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
    ahora = datetime.now()
    bloqueado = IntentosLogin.query.filter(
        IntentosLogin.ip == ip,
        IntentosLogin.ips_bloqueadas > ahora
    ).first()
    return bloqueado is not None

def verificar_bloqueo_email(email):
    ahora = datetime.now()
    registro = IntentosLogin.query.filter_by(email=email).first()
    if registro and registro.email_bloqueado and registro.email_bloqueado > ahora:
        return True
    cliente = Cliente.query.filter_by(correo=email).first()
    if cliente:
        bloqueo = db.session.execute(
            text("SELECT id FROM bloqueos WHERE cliente_id = :cliente_id AND tipo_usuario = 'cliente' AND estado = 1 AND permanente = 1"),
            {"cliente_id": cliente.id}).fetchone()
        if bloqueo:
            return True
    usuario = UsuarioSistema.query.filter_by(correo=email).first()
    if usuario:
        bloqueo = db.session.execute(
            text("SELECT id FROM bloqueos WHERE usuario_sistema_id = :usuario_id AND tipo_usuario = 'sistema' AND estado = 1 AND permanente = 1"),
            {"usuario_id": usuario.id}).fetchone()
        if bloqueo:
            return True
    return False

def limpiar_intentos_exitosos(email, ip):
    try:
        registro = IntentosLogin.query.filter_by(email=email).first()
        if registro:
            registro.intentos = 0
            registro.intentos_totales = 0
            registro.email_bloqueado = None
            registro.ultimo_intento = datetime.now()
            db.session.commit()
        cliente = Cliente.query.filter_by(correo=email).first()
        if cliente:
            db.session.execute(
                text("UPDATE bloqueos SET estado = 0, fecha_desbloqueo = NOW() WHERE cliente_id = :cliente_id AND tipo_usuario = 'cliente' AND permanente = 0 AND estado = 1"),
                {"cliente_id": cliente.id})
            db.session.commit()
        usuario = UsuarioSistema.query.filter_by(correo=email).first()
        if usuario:
            db.session.execute(
                text("UPDATE bloqueos SET estado = 0, fecha_desbloqueo = NOW() WHERE usuario_sistema_id = :usuario_id AND tipo_usuario = 'sistema' AND permanente = 0 AND estado = 1"),
                {"usuario_id": usuario.id})
            db.session.commit()
        ahora = datetime.now()
        emails_bloqueados = IntentosLogin.query.filter(
            IntentosLogin.ip == ip,
            IntentosLogin.email_bloqueado > ahora
        ).count()
        if emails_bloqueados == 0:
            IntentosLogin.query.filter_by(ip=ip).update({IntentosLogin.ips_bloqueadas: None})
            db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"Error limpiando intentos: {e}")
        return False

def limpiar_bloqueos_expirados():
    ahora = datetime.now()
    IntentosLogin.query.filter(
        IntentosLogin.email_bloqueado < ahora,
        IntentosLogin.email_bloqueado.isnot(None)
    ).update({IntentosLogin.email_bloqueado: None, IntentosLogin.intentos: 0})
    IntentosLogin.query.filter(
        IntentosLogin.ips_bloqueadas < ahora,
        IntentosLogin.ips_bloqueadas.isnot(None)
    ).update({IntentosLogin.ips_bloqueadas: None})
    db.session.execute(
        text("UPDATE bloqueos SET estado = 0, fecha_desbloqueo = NOW() WHERE permanente = 0 AND estado = 1 AND fecha_bloqueo < DATE_SUB(NOW(), INTERVAL minutos_bloqueo MINUTE)")
    )
    db.session.commit()

# ---- Funciones de correo ----
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
<p><strong>📅 Fecha:</strong> {venta.fecha_venta.strftime('%d/%m/%Y %H:%M')}</p>
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
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = destinatario
        msg['Subject'] = f"{tipo_comprobante.upper()} ELECTRÓNICA N° {numero_comprobante}"
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"><style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; }}
            .header {{ background: linear-gradient(135deg, #1e3a8a, #3b82f6); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ padding: 30px; background: #f8f9fa; }}
            .producto {{ border-bottom: 1px solid #dee2e6; padding: 12px 0; }}
            .total {{ font-size: 20px; font-weight: bold; color: #28a745; text-align: right; padding-top: 15px; margin-top: 15px; border-top: 2px solid #28a745; }}
            .footer {{ background: #e9ecef; padding: 15px; text-align: center; font-size: 12px; color: #6c757d; border-radius: 0 0 10px 10px; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th {{ background: #1e3a8a; color: white; padding: 10px; }}
            td {{ padding: 8px; }}
        </style></head>
        <body>
            <div class="header"><h2>📚 LIBRERÍA SALESIANA DON BOSCO</h2><h3>{tipo_comprobante.upper()} DE VENTA ELECTRÓNICA</h3><p><strong>N° {numero_comprobante}</strong></p></div>
            <div class="content">
                <p><strong>📅 Fecha:</strong> {fecha.strftime('%d/%m/%Y %H:%M:%S')}</p>
                <p><strong>👤 Cliente:</strong> {cliente_nombre or 'Consumidor Final'}</p>
                <table>
                    <thead><tr><th>Producto</th><th>Cantidad</th><th>Precio Unit.</th><th>Total</th></tr></thead>
                    <tbody>"""
        for p in productos:
            html += f"""<tr class="producto"><td>{p['nombre']}</td><td style="text-align:center;">{p['cantidad']}</td><td style="text-align:right;">S/. {p['precio_unitario']:.2f}</td><td style="text-align:right;">S/. {p['total']:.2f}</td></tr>"""
        html += f"""
                    </tbody>
                </table>
                <div class="total"><p><strong>TOTAL: S/. {total_venta:.2f}</strong></p></div>
                <p style="text-align:center;margin-top:25px;"><strong>✨ ¡Gracias por su compra! ✨</strong><br><small>Este es un comprobante de venta electrónico válido</small></p>
            </div>
            <div class="footer"><p>Librería Salesiana Don Bosco | Todos los derechos reservados</p><p>📧 ventas@librospe.alwaysdata.net | 📞 (01) 123-4567</p></div>
        </body>
        </html>
        """
        msg.attach(MIMEText(html, 'html'))
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Error enviando correo: {e}")
        return False