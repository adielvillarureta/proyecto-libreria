# app/routes/pagos.py
# Cobro con Culqi (token y webhook), PagoEfectivo con QR/CIP, Yape propio,
# validación manual de comprobantes y ajustes de pago del panel.
import os
import random
import hashlib
import hmac
from flask import Blueprint, request, jsonify, session, redirect, url_for, render_template, flash, current_app

from app import db, culqi, mercadopago, ajustes_pago
from app.models import Pedido, Pago
from app.utils import login_required_cliente, login_required, requerir_permisos_escritura, allowed_file
from app.routes.pedidos import finalizar_pedido_pagado
from datetime import datetime
import json

pagos_bp = Blueprint('pagos', __name__)

CARPETA_COMPROBANTES = 'img/pagos'


def _carpeta_comprobantes():
    ruta = os.path.join(current_app.config["UPLOAD_FOLDER"], CARPETA_COMPROBANTES)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def _datos_de(pago):
    try:
        return json.loads(pago.datos or "{}")
    except (ValueError, TypeError):
        return {}


def _liberar_stock(pedido):
    """Devuelve al inventario lo reservado por un pedido que no se pagó."""
    for detalle in pedido.detalles or []:
        producto = detalle.producto
        if producto is not None:
            producto.cantidad = (producto.cantidad or 0) + (detalle.cantidad or 0)


def confirmar_pago(pago, cargo_id=None, orden_id=None, metodo=None, respuesta=None):
    """Marca el pago como cobrado y cierra el pedido. Idempotente.

    Nunca se llama directamente desde una ruta: el estado se confirma contra
    la API de Culqi o tras un cargo exitoso.
    """
    if pago.estado == "pagado":
        return pago.pedido

    pedido = pago.pedido
    if pedido is None:
        return None

    pago.estado = "pagado"
    pago.fecha_pago = datetime.now()
    if cargo_id:
        pago.cargo_id = cargo_id
    if orden_id:
        pago.orden_id = orden_id
    if metodo:
        pago.metodo = metodo
    if respuesta is not None:
        pago.respuesta = json.dumps(respuesta, ensure_ascii=False)
    db.session.commit()

    datos = _datos_de(pago)
    finalizar_pedido_pagado(
        pedido,
        datos.get("cliente", {}),
        datos.get("comprobante", "boleta"),
    )

    if pedido.estado in ("pendiente", "pendiente_pago"):
        pedido.estado = "confirmado"
        db.session.commit()

    print(f"Pago confirmado: pedido #{pedido.id}, pago #{pago.id}, cargo {cargo_id}")
    return pedido


def _registrar_fallo(pago, codigo=None, mensaje=None, respuesta=None, liberar=True):
    pedido = pago.pedido
    pago.estado = "fallido"
    pago.codigo_error = (codigo or "")[:120] or None
    pago.mensaje_error = (mensaje or "")[:255] or None
    if respuesta is not None:
        pago.respuesta = json.dumps(respuesta, ensure_ascii=False)

    if liberar and pedido is not None and pedido.estado == "pendiente_pago":
        _liberar_stock(pedido)
        pedido.estado = "cancelado"

    db.session.commit()


def expirar_pagos_pendientes():
    """Libera el stock de los pedidos que el cliente abandonó.

    Cada proveedor tiene su ventana: Culqi y Mercado Pago caducan a la media
    hora, PagoEfectivo a las 24 horas y los pagos manuales (Yape, transferencia)
    una semana, porque ahí la conciliación es humana.

    Se llama al abrir el panel de pedidos, así que no hace falta cron.
    """
    from datetime import timedelta

    ventanas = {
        "culqi": timedelta(minutes=30),
        "mercadopago": timedelta(minutes=30),
        "pago_efectivo": timedelta(hours=24),
        "yape": timedelta(days=7),
    }

    expirados = 0
    ahora = datetime.now()

    for proveedor, ventana in ventanas.items():
        limite = ahora - ventana
        pagos = (Pago.query
                 .filter(Pago.proveedor == proveedor,
                         Pago.estado == "pendiente",
                         Pago.fecha_creacion < limite)
                 .all())

        for pago in pagos:
            pedido = pago.pedido
            pago.estado = "expirado"
            pago.codigo_error = "expirado"
            pago.mensaje_error = f"El pago venció tras {ventana}"

            if pedido is not None and pedido.estado == "pendiente_pago":
                _liberar_stock(pedido)
                pedido.estado = "cancelado"
                expirados += 1

        if pagos:
            db.session.commit()
            print(f"Pagos vencidos de {proveedor}: {len(pagos)}")

    return expirados


# ---------------- ÍNDICE DE MÉTODOS DE PAGO ----------------
CATALOGO_METODOS = [
    {
        "clave": "culqi",
        "nombre": "Tarjeta de crédito o débito",
        "detalle": "Visa, Mastercard y American Express, en cuotas si tu banco lo permite",
        "icono": "fa-credit-card",
        "red": "Culqi",
        "chips": [
            {"texto": "Visa", "icono": "fab fa-cc-visa"},
            {"texto": "Mastercard", "icono": "fab fa-cc-mastercard"},
            {"texto": "Amex", "icono": "fab fa-cc-amex"},
            {"texto": "Cuotas", "icono": "fas fa-calendar-days"},
        ],
    },
    {
        "clave": "pago_efectivo",
        "nombre": "PagoEfectivo",
        "detalle": "Paga en cualquier agente, banca móvil o bodega y te confirmamos al instante",
        "icono": "fa-store",
        "red": "Culqi",
        "chips": [
            {"texto": "Código QR", "icono": "fas fa-qrcode"},
            {"texto": "Código CIP", "icono": "fas fa-key"},
            {"texto": "Agentes y bodegas", "icono": "fas fa-location-dot"},
        ],
    },
    {
        "clave": "yape",
        "nombre": "Yape o Plin",
        "detalle": "Escanea nuestro QR, paga el monto exacto y sube tu comprobante",
        "icono": "fa-mobile-screen",
        "red": "Transferencia",
        "requiere_validacion": True,
        "chips": [
            {"texto": "Yape", "icono": "fas fa-mobile-screen"},
            {"texto": "Plin", "icono": "fas fa-mobile-screen"},
            {"texto": "Comprobante", "icono": "fas fa-camera"},
        ],
    },
    {
        "clave": "mercadopago",
        "nombre": "Mercado Pago",
        "detalle": "Tarjeta, Yape, Plin y billetera Mercado Pago en un solo paso",
        "icono": "fa-hand-holding-dollar",
        "red": "Mercado Pago",
        "chips": [
            {"texto": "Tarjeta", "icono": "fab fa-cc-visa"},
            {"texto": "Yape", "icono": "fas fa-mobile-screen"},
            {"texto": "Billetera MP", "icono": "fas fa-wallet"},
        ],
    },
    {
        "clave": "contraentrega",
        "nombre": "Pago contraentrega",
        "detalle": "Pagas en efectivo al recibir tu pedido",
        "icono": "fa-hand-holding-usd",
        "red": "Efectivo",
        "chips": [
            {"texto": "Efectivo", "icono": "fas fa-money-bill-wave"},
            {"texto": "Solo envíos a domicilio", "icono": "fas fa-truck"},
        ],
    },
    {
        "clave": "transferencia",
        "nombre": "Transferencia bancaria",
        "detalle": "BCP, BBVA, Interbank y demás bancos del sistema",
        "icono": "fa-building-columns",
        "red": "Transferencia",
        "requiere_validacion": True,
        "chips": [
            {"texto": "BCP", "icono": "fas fa-building-columns"},
            {"texto": "Interbank", "icono": "fas fa-building-columns"},
            {"texto": "CCI", "icono": "fas fa-hashtag"},
        ],
    },
]


@pagos_bp.route('/pasarela-pagos')
@login_required_cliente
def pasarela_pagos():
    """Índice con todos los métodos de pago disponibles.

    Va entre el checkout y la pantalla de pago: el cliente elige aquí y /pago
    ya arranca con el método escogido.
    """
    disponibles = ajustes_pago.metodos_disponibles()
    metodos = [dict(m) for m in CATALOGO_METODOS if disponibles.get(m["clave"])]

    cargo = ajustes_pago.obtener_numero("contraentrega_cargo", 0)
    yape_configurado = bool(ajustes_pago.obtener("yape_qr") or ajustes_pago.obtener("yape_numero"))

    for m in metodos:
        if m["clave"] == "contraentrega":
            m["detalle"] = f'{m["detalle"]} · cargo adicional S/. {cargo:.2f}'
        if m["clave"] == "yape":
            # Sin QR ni número el método igual aparece, pero avisado.
            m["sin_configurar"] = not yape_configurado
            if not yape_configurado:
                m["detalle"] = "Paga por Yape o Plin y sube tu comprobante. Aún no publicamos nuestro QR."

    # El carrito vive en localStorage: el vacío se comprueba en el navegador.
    return render_template("pasarela_pagos.html", metodos=metodos, datetime=datetime)


# ---------------- CONFIG PÚBLICA ----------------
@pagos_bp.route('/api/pagos/config')
def config_pasarela():
    """Solo expone la llave pública: la secreta nunca sale del servidor."""
    return jsonify({
        "habilitado": culqi.esta_configurado() and ajustes_pago.obtener_bool("culqi_activo"),
        "public_key": culqi.llave_publica() if culqi.esta_configurado() else "",
        "mercadopago": mercadopago.esta_configurado() and ajustes_pago.obtener_bool("mercadopago_activo"),
        "metodos": ajustes_pago.metodos_disponibles(),
    })


# ---------------- EXPIRAR ABANDONADOS ----------------
@pagos_bp.route('/api/pagos/expirar', methods=['POST'])
@login_required
@requerir_permisos_escritura
def expirar():
    """Botón manual por si quieres soltar el stock reservado sin esperar."""
    expirados = expirar_pagos_pendientes()
    return jsonify({"success": True, "expirados": expirados})


# ---------------- COBRO CON TOKEN ----------------
@pagos_bp.route('/api/pagos/culqi/cobrar', methods=['POST'])
@login_required_cliente
def cobrar_con_token():
    """Cobra el token que generó el checkout de Culqi (tarjeta o Yape).

    El token es de un solo uso y no contiene datos de tarjeta: la tarjeta se
    tokenizó en el navegador.
    """
    data = request.get_json(silent=True) or {}
    pedido_id = data.get("pedido_id")
    token_id = str(data.get("token_id") or "").strip()
    installments = str(data.get("installments") or "1")

    if not pedido_id or not token_id:
        return jsonify({"success": False, "error": "Faltan datos del cobro"}), 400

    pago = Pago.query.filter_by(pedido_id=pedido_id, proveedor="culqi").order_by(Pago.id.desc()).first()
    if not pago:
        return jsonify({"success": False, "error": "El pedido no tiene una orden de pago abierta"}), 404
    if pago.pedido is None or pago.pedido.cliente_id != session.get("cliente_id"):
        return jsonify({"success": False, "error": "No tienes permiso sobre este pedido"}), 403
    if pago.estado == "pagado":
        return jsonify({"success": True, "pedido_id": pedido_id, "ya_pagado": True})
    if pago.estado != "pendiente":
        return jsonify({"success": False, "error": "Esta orden de pago ya no está disponible"}), 409

    try:
        cargo = culqi.cobrar(
            token_id=token_id,
            monto=pago.monto,
            order_id=pago.orden_id,
            descripcion=f"Pedido #{pago.pedido_id}",
            installments=installments,
            metadata={"pedido_id": pago.pedido_id},
        )
    except culqi.CulqiError as exc:
        print(f"Culqi rechazó el cargo del pedido {pago.pedido_id}: {exc.mensaje}")
        return jsonify({
            "success": False,
            "error": exc.mensaje,
            "codigo": exc.codigo,
        }), 502

    if cargo.get("status") == "paid" and cargo.get("outcome") == "paid":
        metodo = "tarjeta"
        if (cargo.get("source") or {}).get("card_brand") == "yape":
            metodo = "yape"
        confirmar_pago(
            pago,
            cargo_id=cargo.get("id"),
            metodo=metodo,
            respuesta=cargo,
        )
        return jsonify({"success": True, "pedido_id": pago.pedido_id, "cargo_id": cargo.get("id")})

    # Quedó "pending": Culqi puede terminar de autorizar después (3DS, etc.).
    pago.respuesta = json.dumps(cargo, ensure_ascii=False)
    db.session.commit()

    return jsonify({
        "success": False,
        "pending": True,
        "cargo_id": cargo.get("id"),
        "error": (cargo.get("user_message") or cargo.get("message")
                  or "El pago quedó en revisión. Te avisaremos por correo."),
    }), 202


# ---------------- WEBHOOK ----------------
@pagos_bp.route('/webhooks/culqi', methods=['POST'])
def webhook_culqi():
    """Notificaciones de Culqi.

    El cuerpo del evento no se confía: se re-consulta el objeto contra la API
    de Culqi con la llave secreta y solo se confirma si ahí figura pagado.
    """
    evento = request.get_json(silent=True) or {}
    objeto = evento.get("data") or {}
    tipo = str(evento.get("event") or evento.get("type") or "").lower()
    id_objeto = objeto.get("id") or ""
    print(f"Webhook Culqi: tipo={tipo or '?'} id={id_objeto or '?'}")

    if not id_objeto:
        return jsonify({"ok": True, "ignorado": "evento sin objeto"}), 200

    try:
        if id_objeto.startswith("ord_"):
            verificacion = culqi.consultar_orden(id_objeto)
            if verificacion.get("state") != "paid":
                print(f"Orden {id_objeto} aún no pagada (state={verificacion.get('state')})")
                return jsonify({"ok": True, "ignorado": "orden no pagada"}), 200
            pago = Pago.query.filter_by(orden_id=id_objeto).order_by(Pago.id.desc()).first()
            metodo = "pago_efectivo" if verificacion.get("payment_code") else "billetera"

        elif id_objeto.startswith("chr_"):
            verificacion = culqi.consultar_cargo(id_objeto)
            if verificacion.get("status") != "paid" or verificacion.get("outcome") != "paid":
                return jsonify({"ok": True, "ignorado": "cargo no pagado"}), 200
            orden_id = verificacion.get("order_id")
            pago = Pago.query.filter_by(orden_id=orden_id).order_by(Pago.id.desc()).first() if orden_id else None
            metodo = "tarjeta"

        else:
            return jsonify({"ok": True, "ignorado": "tipo de objeto desconocido"}), 200

    except culqi.CulqiError as exc:
        print(f"Error verificando webhook: {exc.mensaje}")
        return jsonify({"ok": False, "error": exc.mensaje}), 502

    if not pago:
        print(f"Webhook Culqi: no hay pago local para {id_objeto}")
        return jsonify({"ok": True, "ignorado": "sin pago local"}), 200

    confirmar_pago(pago, orden_id=pago.orden_id, metodo=metodo, respuesta=verificacion)
    return jsonify({"ok": True}), 200


# ---------------- ESTADO Y CANCELACIÓN ----------------
@pagos_bp.route('/api/pagos/<int:pedido_id>/estado')
@login_required_cliente
def estado_pago(pedido_id):
    """La pantalla de retorno pregunta aquí si el webhook ya llegó."""
    pedido = Pedido.query.get(pedido_id)
    if not pedido:
        return jsonify({"success": False, "error": "Pedido no encontrado"}), 404
    if pedido.cliente_id != session.get("cliente_id"):
        return jsonify({"success": False, "error": "No tienes permiso"}), 403

    pago = pedido.pagos.order_by(Pago.id.desc()).first()

    if pago and pago.estado == "pendiente" and pago.orden_id:
        # PagoEfectivo y billeteras llegan tarde: re-consultamos la orden.
        try:
            orden = culqi.consultar_orden(pago.orden_id)
            if orden.get("state") == "paid":
                confirmar_pago(pago, orden_id=pago.orden_id, respuesta=orden)
                pedido = Pedido.query.get(pedido_id)
        except culqi.CulqiError as exc:
            print(f"No se pudo re-consultar la orden {pago.orden_id}: {exc.mensaje}")

    return jsonify({
        "success": True,
        "pedido_id": pedido_id,
        "estado_pedido": pedido.estado,
        "estado_pago": pago.estado if pago else None,
        "metodo": pago.metodo if pago else None,
        "total": pedido.total,
    })


@pagos_bp.route('/api/pagos/culqi/cancelar', methods=['POST'])
@login_required_cliente
def cancelar_pago():
    """El cliente abandonó el checkout: libera el stock reservado."""
    data = request.get_json(silent=True) or {}
    pedido_id = data.get("pedido_id")

    pago = Pago.query.filter_by(pedido_id=pedido_id, proveedor="culqi").order_by(Pago.id.desc()).first()
    if not pago or pago.estado != "pendiente":
        return jsonify({"success": False, "error": "No hay un pago pendiente"}), 404
    if pago.pedido.cliente_id != session.get("cliente_id"):
        return jsonify({"success": False, "error": "No tienes permiso"}), 403

    _registrar_fallo(pago, codigo="abandonado", mensaje="El cliente no completó el pago")
    return jsonify({"success": True})


@pagos_bp.route('/pago/retorno')
def pago_retorno():
    return redirect(url_for("pedidos.mis_pedidos"))


# ---------------- PAGOEFECTIVO: QR Y CÓDIGO CIP ----------------
def _pedido_del_cliente(pedido_id):
    try:
        pedido_id = int(pedido_id)
    except (TypeError, ValueError):
        return None, (jsonify({"success": False, "error": "Pedido no encontrado"}), 404)

    pedido = Pedido.query.get(pedido_id)
    if pedido is None:
        return None, (jsonify({"success": False, "error": "Pedido no encontrado"}), 404)
    if pedido.cliente_id != session.get("cliente_id"):
        return None, (jsonify({"success": False, "error": "No tienes permiso"}), 403)
    return pedido, None


@pagos_bp.route('/pago/efectivo/<int:pedido_id>')
@login_required_cliente
def pago_efectivo(pedido_id):
    """El cliente paga en agentes, banca móvil o bodegas con QR o código CIP."""
    pedido, error = _pedido_del_cliente(pedido_id)
    if error:
        return error

    pago = pedido.pagos.order_by(Pago.id.desc()).first()
    if pago is None:
        flash("Ese pedido no tiene una orden de pago", "warning")
        return redirect(url_for("pedidos.mis_pedidos"))

    datos = _datos_de(pago)
    orden = {}
    if pago.respuesta:
        try:
            orden = json.loads(pago.respuesta)
        except (ValueError, TypeError):
            orden = {}

    acciones = orden.get("actions") or {}
    return render_template(
        "pago_efectivo.html",
        pedido=pedido,
        pago=pago,
        total=pago.monto_soles,
        qr_url=(acciones.get("QUERY_QR") or {}).get("qr_code"),
        cip=(acciones.get("CODE") or {}).get("cip_code"),
        nombre_cliente=f"{datos.get('cliente', {}).get('nombres', '')} {datos.get('cliente', {}).get('apellidos', '')}".strip(),
    )


# ---------------- YAPE / PLIN CON NUESTRO QR ----------------
# El comprobante es la única prueba válida: sin él, el pedido no se puede
# confirmar. Estas medidas frenan a los que suben archivos en automático.
FIRMAS_IMAGEN = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
}
MAX_COMPROBANTE_MB = 5
CAPTCHA_MINUTOS = 10
SUBIDAS_POR_HORA = 6


def _nuevo_captcha():
    """Aritmética simple: frena bots ingenuos sin depender de reCAPTCHA.

    No es una defensa fuerte contra un atacante con Ajax; para eso hay que
    poner hCaptcha con llaves. Sirve para el ruido de siempre.
    """
    a = random.randint(2, 9)
    b = random.randint(2, 9)
    if random.random() < 0.5:
        pregunta, respuesta = f"{a} + {b}", a + b
    else:
        pregunta, respuesta = f"{a} × {b}", a * b

    session["captcha_yape"] = {
        "hash": hashlib.sha256(str(respuesta).encode()).hexdigest(),
        "exp": datetime.now().timestamp() + CAPTCHA_MINUTOS * 60,
    }
    return pregunta


def _captcha_correcto(respuesta):
    datos = session.get("captcha_yape")
    if not datos:
        return False
    if datetime.now().timestamp() > datos.get("exp", 0):
        session.pop("captcha_yape", None)
        return False
    # Un solo uso, aunque acierte.
    session.pop("captcha_yape", None)
    esperado = datos.get("hash", "")
    recibido = hashlib.sha256(str(respuesta or "").strip().encode()).hexdigest()
    return hmac.compare_digest(esperado, recibido)


def _control_subidas():
    """Máximo de subidas por hora, contadas por sesión."""
    ahora = datetime.now().timestamp()
    historial = [t for t in session.get("subidas_yape", []) if ahora - t < 3600]
    if len(historial) >= SUBIDAS_POR_HORA:
        session["subidas_yape"] = historial
        return False
    historial.append(ahora)
    session["subidas_yape"] = historial
    return True


def _es_imagen_real(contenido):
    for firma, extension in FIRMAS_IMAGEN.items():
        if contenido.startswith(firma):
            return extension
    return None
@pagos_bp.route('/pago/yape/<int:pedido_id>')
@login_required_cliente
def pago_yape(pedido_id):
    """El cliente escanea el QR de la librería y sube su comprobante."""
    pedido, error = _pedido_del_cliente(pedido_id)
    if error:
        return error

    pago = pedido.pagos.order_by(Pago.id.desc()).first()
    if pago is None:
        flash("Ese pedido no tiene un pago pendiente", "warning")
        return redirect(url_for("pedidos.mis_pedidos"))

    return render_template(
        "pago_yape.html",
        pedido=pedido,
        pago=pago,
        total=pago.monto_soles,
        yape_titular=ajustes_pago.obtener("yape_titular"),
        yape_numero=ajustes_pago.obtener("yape_numero"),
        yape_qr=ajustes_pago.obtener("yape_qr"),
        yape_instruccion=ajustes_pago.obtener("yape_instruccion"),
    )


@pagos_bp.route('/api/pagos/yape/captcha', methods=['GET'])
@login_required_cliente
def captcha_yape():
    """Entrega el reto del CAPTCHA para poder subir un comprobante."""
    return jsonify({"pregunta": _nuevo_captcha(), "expira_en": CAPTCHA_MINUTOS * 60})


@pagos_bp.route('/api/pagos/yape/comprobante', methods=['POST'])
@login_required_cliente
def subir_comprobante():
    """Guarda la foto o captura del Yape/Plin para que el personal la revise.

    El comprobante es obligatorio: sin él el pedido no se puede confirmar.
    """
    # Viene como multipart/form-data, así que get_json() no aplica.
    pedido_id = request.form.get("pedido_id") or (request.get_json(silent=True) or {}).get("pedido_id")

    pedido, error = _pedido_del_cliente(pedido_id)
    if error:
        return error

    pago = pedido.pagos.order_by(Pago.id.desc()).first()
    if pago is None or pago.estado != "pendiente":
        return jsonify({"success": False, "error": "No hay un pago pendiente para este pedido"}), 409

    if not _captcha_correcto(request.form.get("captcha")):
        return jsonify({
            "success": False,
            "error": "La verificación de seguridad no coincide. Vuelve a intentarlo.",
            "nuevo_captcha": True,
        }), 400

    if not _control_subidas():
        return jsonify({
            "success": False,
            "error": "Demasiados envíos seguidos. Espera un rato antes de reintentar.",
        }), 429

    archivo = request.files.get("comprobante")
    if archivo is None or not archivo.filename:
        return jsonify({"success": False, "error": "Adjunta una foto o captura del pago"}), 400
    if not allowed_file(archivo.filename):
        return jsonify({"success": False, "error": "Solo se aceptan imágenes PNG, JPG o GIF"}), 400

    contenido = archivo.read()
    if len(contenido) > MAX_COMPROBANTE_MB * 1024 * 1024:
        return jsonify({
            "success": False,
            "error": f"La imagen supera los {MAX_COMPROBANTE_MB} MB. Tómale una captura más liviana.",
        }), 413

    # El nombre del archivo no dice nada: miramos los primeros bytes.
    extension = _es_imagen_real(contenido)
    if extension is None:
        return jsonify({"success": False, "error": "Ese archivo no es una imagen válida"}), 400

    nombre = f"pedido{pedido.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{extension}"
    ruta = os.path.join(_carpeta_comprobantes(), nombre)
    with open(ruta, "wb") as destino:
        destino.write(contenido)

    pago.comprobante = f"{CARPETA_COMPROBANTES}/{nombre}"
    pago.mensaje_error = None
    db.session.commit()
    print(f"Comprobante recibido del pedido #{pedido.id} ({len(contenido) // 1024} KB)")

    return jsonify({"success": True, "nombre": nombre})


@pagos_bp.route('/api/pagos/yape/comprobante/<int:pago_id>')
@login_required
def ver_comprobante(pago_id):
    """El personal ve el comprobante que subió el cliente."""
    pago = Pago.query.get(pago_id)
    if pago is None or not pago.comprobante:
        return jsonify({"success": False, "error": "No hay comprobante"}), 404

    ruta = os.path.join(current_app.config["UPLOAD_FOLDER"], pago.comprobante)
    if not os.path.isfile(ruta):
        return jsonify({"success": False, "error": "El archivo ya no está en el servidor"}), 404

    return current_app.send_static_file(f"img/pagos/{os.path.basename(ruta)}")


# ---------------- VALIDACIÓN MANUAL ----------------
@pagos_bp.route('/api/pagos/<int:pago_id>/validar', methods=['POST'])
@login_required
@requerir_permisos_escritura
def validar_pago(pago_id):
    """Confirma a mano un pago por Yape/Plin o transferencia.

    El comprobante del cliente es lo único que habilita la confirmación. Si no
    hay imagen, no hay pago validado: hay que pedirla antes.
    """
    data = request.get_json(silent=True) or {}
    pago = Pago.query.get(pago_id)
    if pago is None:
        return jsonify({"success": False, "error": "Pago no encontrado"}), 404
    if pago.estado != "pendiente":
        return jsonify({"success": False, "error": "Este pago ya fue procesado"}), 409

    if data.get("accion") == "rechazar":
        _registrar_fallo(pago, codigo="rechazado", mensaje=str(data.get("motivo") or "Rechazado por el personal")[:255])
        return jsonify({"success": True, "estado": "rechazado"})

    if not pago.comprobante:
        return jsonify({
            "success": False,
            "error": "El cliente todavía no subió su comprobante. Sin comprobante no se puede confirmar.",
        }), 400

    pedido = confirmar_pago(pago, metodo=pago.metodo or "yape")
    return jsonify({"success": True, "estado": "pagado", "pedido_id": pedido.id if pedido else None})


# ---------------- MERCADO PAGO ----------------
@pagos_bp.route('/webhooks/mercadopago', methods=['POST'])
def webhook_mercadopago():
    """Mercado Pago avisa los pagos aprobados.

    La firma del header se valida siempre; el estado real se re-consulta en
    la API, nunca se toma del cuerpo.
    """
    if not mercadopago.firma_valida():
        print("Webhook Mercado Pago rechazado: firma inválida o sin MP_WEBHOOK_SECRET")
        return jsonify({"ok": False, "error": "firma inválida"}), 401

    datos = request.get_json(silent=True) or {}
    if datos.get("type") not in (None, "payment"):
        return jsonify({"ok": True, "ignorado": datos.get("type")}), 200

    payment_id = (datos.get("data") or {}).get("id")
    if not payment_id:
        return jsonify({"ok": True, "ignorado": "sin id de pago"}), 200

    try:
        pago_mp = mercadopago.consultar_pago(payment_id)
    except mercadopago.MpError as exc:
        print(f"No se pudo consultar el pago {payment_id}: {exc.mensaje}")
        return jsonify({"ok": False, "error": exc.mensaje}), 502

    referencia = (pago_mp.get("external_reference") or "").replace("PEDIDO-", "").strip()
    if not referencia.isdigit():
        return jsonify({"ok": True, "ignorado": "referencia inválida"}), 200

    pago = Pago.query.filter_by(
        pedido_id=int(referencia),
        proveedor="mercadopago",
    ).order_by(Pago.id.desc()).first()

    if pago is None:
        return jsonify({"ok": True, "ignorado": "sin pago local"}), 200

    if pago_mp.get("status") != "approved":
        pago.respuesta = json.dumps(pago_mp, ensure_ascii=False)
        db.session.commit()
        return jsonify({"ok": True, "estado": pago_mp.get("status")}), 200

    metodo = (pago_mp.get("payment_method_id") or "").split("-")[0]
    confirmar_pago(
        pago,
        cargo_id=str(pago_mp.get("id")),
        metodo=f"mercadopago:{metodo}" if metodo else "mercadopago",
        respuesta=pago_mp,
    )
    return jsonify({"ok": True}), 200


@pagos_bp.route('/pago/mp-retorno/<int:pedido_id>')
@login_required_cliente
def pago_mp_retorno(pedido_id):
    """Mercado Pago devuelve aquí al cliente tras aprobar o rechazar."""
    pedido, error = _pedido_del_cliente(pedido_id)
    if error:
        return error

    pago = pedido.pagos.filter_by(proveedor="mercadopago").order_by(Pago.id.desc()).first()
    if pago and pago.estado == "pendiente":
        # Aprovechamos la vuelta para preguntar por el pago approved.
        datos = request.args
        payment_id = (datos.get("payment_id") or datos.get("collection_id") or "").strip()
        if payment_id.isdigit():
            try:
                pago_mp = mercadopago.consultar_pago(payment_id)
                if pago_mp.get("status") == "approved":
                    confirmar_pago(
                        pago,
                        cargo_id=str(pago_mp.get("id")),
                        metodo="mercadopago",
                        respuesta=pago_mp,
                    )
                    pedido = Pedido.query.get(pedido_id)
            except mercadopago.MpError as exc:
                print(f"No se pudo consultar el pago {payment_id}: {exc.mensaje}")

    return render_template("pago_mp_retorno.html", pedido=pedido, pago=pago)


# ---------------- AJUSTES DE PAGO (PANEL) ----------------
@pagos_bp.route('/ajustes-pagos', methods=['GET', 'POST'])
@login_required
@requerir_permisos_escritura
def ajustes_pagos():
    if request.method == 'POST':
        for clave in request.form:
            if clave == 'csrf_token':
                continue
            tipo = ajustes_pago.DEFAULTS.get(clave, {}).get("tipo", "texto")
            ajustes_pago.guardar(clave, request.form.get(clave), tipo)

        qr = request.files.get('yape_qr_archivo')
        if qr and qr.filename:
            if allowed_file(qr.filename):
                extension = qr.filename.rsplit(".", 1)[1].lower()
                nombre = f"yape_{datetime.now().strftime('%Y%m%d%H%M%S')}.{extension}"
                os.makedirs(os.path.join(current_app.config["UPLOAD_FOLDER"], CARPETA_COMPROBANTES), exist_ok=True)
                qr.save(os.path.join(current_app.config["UPLOAD_FOLDER"], CARPETA_COMPROBANTES, nombre))
                ajustes_pago.guardar("yape_qr", f"{CARPETA_COMPROBANTES}/{nombre}", "imagen")
            else:
                flash("El QR debe ser PNG, JPG o GIF", "warning")

        db.session.commit()
        flash("Ajustes de pago guardados", "success")
        return redirect(url_for("pagos.ajustes_pagos"))

    valores = {}
    for clave in ajustes_pago.DEFAULTS:
        valores[clave] = {
            "valor": ajustes_pago.obtener(clave),
            "tipo": ajustes_pago.DEFAULTS[clave]["tipo"],
            "descripcion": ajustes_pago.DEFAULTS[clave]["descripcion"],
        }
    return render_template("ajustes_pagos.html", valores=valores)