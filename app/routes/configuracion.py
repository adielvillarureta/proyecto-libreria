# app/routes/configuracion.py
"""Configuración técnica: base de datos, correo y llaves de las pasarelas.

Es la pantalla más delicada del sistema: guarda contraseñas y llaves
privadas. Por eso pide la contraseña del administrador antes de dejar
escribir nada, solo el rol administrador entra, y cada cambio queda
registrado con usuario e IP.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app

from app import db, bcrypt, config_sistema
from app.models import UsuarioSistema, CambioConfiguracion
from app.utils import login_required, admin_required, obtener_ip_cliente

configuracion_bp = Blueprint('configuracion', __name__)


@configuracion_bp.route('/configuracion', methods=['GET'])
@login_required
@admin_required
def ver_configuracion():
    return render_template(
        "configuracion.html",
        claves=config_sistema.listar_para_panel(),
        grupos=config_sistema.GRUPOS,
        cambios=CambioConfiguracion.query.order_by(CambioConfiguracion.fecha.desc()).limit(20).all(),
    )


@configuracion_bp.route('/configuracion', methods=['POST'])
@login_required
@admin_required
def guardar_configuracion():
    # 1) Confirmar contraseña. Sin esto, cualquiera que entre al panel con
    #    una sesión abierta podría cambiar la clave de la base de datos.
    clave_actual = (request.form.get("clave_admin") or "").strip()
    usuario_id = session.get("usuario_id")

    usuario = db.session.get(UsuarioSistema, usuario_id)
    if usuario is None or not usuario.clave:
        flash("No pudimos verificar tu contraseña. Vuelve a iniciar sesión.", "danger")
        return redirect(url_for("configuracion.ver_configuracion"))

    if not bcrypt.check_password_hash(usuario.clave, clave_actual):
        flash("Contraseña incorrecta. No se guardó nada.", "danger")
        return redirect(url_for("configuracion.ver_configuracion"))

    # 2) Guardar solo los campos con contenido. Dejarlo vacío significa
    #    "dejar como está", no "borrar".
    ip = obtener_ip_cliente()
    cambios = []

    for clave in config_sistema.CATALOGO:
        if clave not in request.form:
            continue
        valor = (request.form.get(clave) or "").strip()
        if not valor:
            continue  # sin cambios
        if valor == "********":  # el valor enmascarado que se le mostró
            continue
        config_sistema.escribir(clave, valor, usuario_id=usuario_id, ip=ip)
        cambios.append(clave)

    if not cambios:
        flash("No cambiaste nada.", "info")
        return redirect(url_for("configuracion.ver_configuracion"))

    db.session.commit()

    # Casi todo se puede refrescar sin reiniciar, porque los módulos leen de
    # current_app.config en cada llamada. La clave de sesión y la conexión a
    # la base sí necesitan reinicio.
    for clave in cambios:
        if clave not in config_sistema.requiere_reinicio([clave]):
            current_app.config[clave] = config_sistema.leer(clave)

    reinicio = config_sistema.requiere_reinicio(cambios)

    from app.config_sistema import CATALOGO
    detalle = ", ".join(CATALOGO[c][0] for c in cambios)
    if reinicio:
        flash(
            f"Guardado: {detalle}. "
            f"Reinicia el servidor para que {'esas' if len(reinicio) > 1 else 'esa'} "
            f"cambio surta efecto: {', '.join(reinicio)}.",
            "warning",
        )
    else:
        flash(f"Guardado y aplicado en caliente: {detalle}", "success")

    print(f"Configuración cambiada por {usuario.correo} ({ip}): {detalle}")
    return redirect(url_for("configuracion.ver_configuracion"))