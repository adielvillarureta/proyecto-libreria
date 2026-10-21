# app/routes/pedidos.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app import db
from app import culqi
from app import mercadopago
from app.config import Config
from app.models import Pedido, DetallePedido, Producto, Cliente, Venta, Pago, Categoria, UsuarioSistema
from app.utils import login_required, login_required_cliente, enviar_comprobante_email, tabla_existe, no_configurado, generar_enlace_whatsapp_comprobante
from datetime import datetime
from sqlalchemy import func, text
import json

pedidos_bp = Blueprint('pedidos', __name__)


# ---------------- CATÁLOGO Y CARRITO (CLIENTES) ----------------
@pedidos_bp.route('/catalogo', methods=['GET'])
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


@pedidos_bp.route('/carrito')
def ver_carrito():
    return render_template("carrito.html")


@pedidos_bp.route('/checkout')
@login_required_cliente
def checkout():
    cliente = Cliente.query.get(session.get("cliente_id"))
    return render_template("checkout.html", cliente=cliente, datetime=datetime)


@pedidos_bp.route('/pago')
@login_required_cliente
def pago():
    from app import ajustes_pago
    metodos = ajustes_pago.metodos_disponibles()

    # El cliente llega desde el índice con el método ya escogido.
    elegido = str(request.args.get("metodo") or "").strip().lower()
    if elegido not in metodos:
        elegido = ""

    return render_template(
        "pago.html",
        datetime=datetime,
        metodos=metodos,
        metodo_elegido=elegido,
        datos_pago={
            "yape_titular": ajustes_pago.obtener("yape_titular"),
            "yape_numero": ajustes_pago.obtener("yape_numero"),
            "yape_qr": ajustes_pago.obtener("yape_qr"),
            "yape_instruccion": ajustes_pago.obtener("yape_instruccion"),
            "transferencia_banco": ajustes_pago.obtener("transferencia_banco"),
            "transferencia_titular": ajustes_pago.obtener("transferencia_titular"),
            "transferencia_cuenta": ajustes_pago.obtener("transferencia_cuenta"),
            "transferencia_cci": ajustes_pago.obtener("transferencia_cci"),
            "contraentrega_cargo": ajustes_pago.obtener_numero("contraentrega_cargo", 3.0),
        },
    )


# ---------------- MIS PEDIDOS (CLIENTE) ----------------
@pedidos_bp.route('/mis-pedidos')
@login_required_cliente
def mis_pedidos():
    pedidos = Pedido.query.filter_by(cliente_id=session["cliente_id"]).order_by(Pedido.fecha_pedido.desc()).all()
    return render_template("mis_pedidos.html", pedidos=pedidos)


@pedidos_bp.route('/mis-pedidos/detalle/<int:pedido_id>')
@login_required_cliente
def cliente_detalle_pedido(pedido_id):
    pedido = Pedido.query.get_or_404(pedido_id)

    if pedido.cliente_id != session.get("cliente_id"):
        flash("❌ No tienes permiso para ver este pedido", "danger")
        return redirect(url_for("pedidos.mis_pedidos"))

    detalles = db.session.query(DetallePedido, Producto.nombre.label("producto_nombre"))\
        .join(Producto).filter(DetallePedido.pedido_id == pedido_id).all()
    cliente = Cliente.query.get(pedido.cliente_id)

    venta = Venta.query.filter_by(numero_comprobante=f"ONLINE-{pedido_id}").first()
    if not venta:
        venta = Venta.query.filter(Venta.numero_comprobante.like(f'%{pedido_id}%')).first()
    if not venta and cliente and cliente.dni:
        venta = Venta.query.filter_by(cliente_documento=cliente.dni).order_by(Venta.fecha_venta.desc()).first()
    if not venta and cliente and cliente.correo:
        venta = Venta.query.filter_by(cliente_email=cliente.correo).order_by(Venta.fecha_venta.desc()).first()

    return render_template("cliente_pedido_detalle.html",
                           pedido=pedido,
                           detalles=detalles,
                           cliente=cliente,
                           venta=venta)


@pedidos_bp.route('/api/mis-pedidos')
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


# ---------------- CREAR PEDIDO ----------------
def finalizar_pedido_pagado(pedido, info, comprobante_tipo):
    """Cierra el pedido una vez confirmado el pago: genera las ventas, envía el
    comprobante por correo y arma el enlace de WhatsApp.

    El stock se descuenta al crear el pedido (reserva), no aquí. Esta función
    es idempotente: si el pedido ya no está en `pendiente_pago` o `pendiente`
    no vuelve a generar ventas.
    """
    if pedido.estado not in ("pendiente", "pendiente_pago"):
        return None

    if comprobante_tipo == "factura" and not info.get("razon_social"):
        comprobante_tipo = "boleta"

    vendedor = db.session.query(UsuarioSistema.id).order_by(UsuarioSistema.id).first()
    if not vendedor:
        return None

    numero = f"ONLINE-{pedido.id}"
    productos_para_correo = []

    for detalle in pedido.detalles or []:
        producto = detalle.producto
        venta = Venta(
            producto_id=producto.id,
            cantidad=detalle.cantidad,
            vendedor_id=vendedor[0],
            fecha_venta=datetime.now(),
            tipo_comprobante=comprobante_tipo,
            numero_comprobante=numero,
            cliente_nombres=info.get("nombres", ""),
            cliente_apellidos=info.get("apellidos", ""),
            cliente_documento=info.get("documento", ""),
            cliente_email=info.get("email", ""),
            cliente_direccion=info.get("direccion", ""),
            cliente_direccion_fiscal=info.get("direccion_fiscal", ""),
            cliente_razon_social=info.get("razon_social", ""),
        )
        db.session.add(venta)
        productos_para_correo.append({
            "nombre": producto.nombre,
            "cantidad": detalle.cantidad,
            "precio_unitario": detalle.precio_unitario,
            "total": detalle.subtotal,
        })

    db.session.commit()

    try:
        enviar_comprobante_email(
            destinatario=info.get("email", ""),
            cliente_nombre=f"{info.get('nombres', '')} {info.get('apellidos', '')}".strip(),
            tipo_comprobante=comprobante_tipo,
            numero_comprobante=numero,
            fecha=datetime.now(),
            productos=productos_para_correo,
            total_venta=round(pedido.total or 0, 2),
        )
        print(f"Correo enviado a {info.get('email', '')}")
    except Exception as e:
        print(f"Error al enviar correo: {e}")

    whatsapp_url = None
    try:
        whatsapp_url = generar_enlace_whatsapp_comprobante(
            telefono=info.get("telefono", ""),
            cliente_nombre=f"{info.get('nombres', '')} {info.get('apellidos', '')}".strip(),
            tipo_comprobante=comprobante_tipo,
            numero_comprobante=numero,
            total=round(pedido.total or 0, 2),
            fecha=datetime.now(),
            productos=productos_para_correo,
        )
    except Exception as e:
        print(f"Error generando enlace WhatsApp: {e}")

    return whatsapp_url


def _abrir_pago_culqi(pedido, info, tipo_comp, total_cliente):
    """Crea la orden en Culqi y deja el pedido esperando el cobro.

    La orden es lo que habilita PagoEfectivo, billeteras (Yape/Plin) y
    Cuotéalo en el checkout; sin ella Culqi solo ofrece tarjeta.
    """
    monto = int(round(total_cliente * 100))

    try:
        orden = culqi.crear_orden(
            monto=monto,
            order_number=f"PEDIDO-{pedido.id}",
            descripcion=f"Pedido #{pedido.id} - Libreria Salesiana",
            cliente=info,
            expiracion_segundos=1800,
            metadata={"pedido_id": pedido.id},
        )
    except culqi.CulqiError as exc:
        db.session.rollback()
        print(f"Error creando orden Culqi: {exc.mensaje}")
        return jsonify({"success": False, "error": exc.mensaje}), 502

    pago = Pago(
        pedido_id=pedido.id,
        proveedor="culqi",
        orden_id=orden.get("id"),
        codigo_pago=orden.get("payment_code"),
        monto=monto,
        estado="pendiente",
        respuesta=json.dumps(orden, ensure_ascii=False),
        datos=json.dumps({"cliente": info, "comprobante": tipo_comp}, ensure_ascii=False),
    )
    db.session.add(pago)
    db.session.commit()

    return jsonify({
        "success": True,
        "pedido_id": pedido.id,
        "culqi_order_id": orden.get("id"),
        "payment_code": orden.get("payment_code"),
        "amount": monto,
        "public_key": culqi.llave_publica(),
    })


def _abrir_pago_efectivo(pedido, info, tipo_comp, total_cliente):
    """Orden de Culqi para PagoEfectivo: el cliente paga con QR o código CIP
    en agentes, banca móvil o bodegas. El webhook confirma el cobro."""
    monto = int(round(total_cliente * 100))

    try:
        orden = culqi.crear_orden(
            monto=monto,
            order_number=f"PEDIDO-{pedido.id}",
            descripcion=f"Pedido #{pedido.id} - Libreria Salesiana",
            cliente=info,
            expiracion_segundos=86400,
            metadata={"pedido_id": pedido.id},
        )
    except culqi.CulqiError as exc:
        db.session.rollback()
        print(f"Error creando orden PagoEfectivo: {exc.mensaje}")
        return jsonify({"success": False, "error": exc.mensaje}), 502

    pago = Pago(
        pedido_id=pedido.id,
        proveedor="culqi",
        orden_id=orden.get("id"),
        codigo_pago=orden.get("payment_code"),
        monto=monto,
        estado="pendiente",
        respuesta=json.dumps(orden, ensure_ascii=False),
        datos=json.dumps({"cliente": info, "comprobante": tipo_comp}, ensure_ascii=False),
    )
    db.session.add(pago)
    db.session.commit()

    return jsonify({
        "success": True,
        "pedido_id": pedido.id,
        "redirect": url_for("pagos.pago_efectivo", pedido_id=pedido.id),
    })


def _abrir_pago_yape(pedido, info, tipo_comp, total_cliente):
    """Pago por el QR de Yape/Plin de la librería.

    No hay cobro automático: el cliente paga a mano y sube su comprobante.
    El personal lo valida desde el panel y ahí se confirma el pedido.
    """
    monto = int(round(total_cliente * 100))

    pago = Pago(
        pedido_id=pedido.id,
        proveedor="yape",
        monto=monto,
        estado="pendiente",
        metodo="yape",
        datos=json.dumps({"cliente": info, "comprobante": tipo_comp}, ensure_ascii=False),
    )
    db.session.add(pago)
    db.session.commit()

    return jsonify({
        "success": True,
        "pedido_id": pedido.id,
        "redirect": url_for("pagos.pago_yape", pedido_id=pedido.id),
    })


def _abrir_pago_mercadopago(pedido, info, tipo_comp, total_cliente):
    """Preferencia de Mercado Pago y redirección a su checkout."""
    from app import mercadopago

    monto = int(round(total_cliente * 100))

    pago = Pago(
        pedido_id=pedido.id,
        proveedor="mercadopago",
        monto=monto,
        estado="pendiente",
        datos=json.dumps({"cliente": info, "comprobante": tipo_comp}, ensure_ascii=False),
    )
    db.session.add(pago)
    db.session.commit()

    base = Config.BASE_URL.rstrip("/") or request.url_root.rstrip("/")

    try:
        preferencia = mercadopago.crear_preferencia(
            monto=monto,
            referencia=f"PEDIDO-{pedido.id}",
            descripcion=f"Pedido #{pedido.id} - Libreria Salesiana",
            payer={"email": info.get("email", "")},
            url_ok=f"{base}/pago/mp-retorno/{pedido.id}",
            url_fail=f"{base}/pago/mp-retorno/{pedido.id}",
            url_pending=f"{base}/webhooks/mercadopago",
        )
    except mercadopago.MpError as exc:
        db.session.rollback()
        print(f"Error creando preferencia Mercado Pago: {exc.mensaje}")
        return jsonify({"success": False, "error": exc.mensaje}), 502

    pago.respuesta = json.dumps(preferencia, ensure_ascii=False)
    db.session.commit()

    return jsonify({
        "success": True,
        "pedido_id": pedido.id,
        "redirect": preferencia.get("url"),
    })


@pedidos_bp.route('/api/pedidos/crear', methods=['POST'])
@login_required_cliente
def crear_pedido():
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []

    print("=" * 60)
    print("DATOS RECIBIDOS EN /api/pedidos/crear:")
    print(f"Items: {len(items)} productos")
    print(f"Tipo entrega: {data.get('tipo_entrega')}")
    print(f"Total: {data.get('total')}")
    print("=" * 60)

    if not isinstance(items, list) or not items:
        return jsonify({"success": False, "error": "Carrito vacío"}), 400
    try:
        total_cliente = float(data.get("total", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Total inválido"}), 400
    if total_cliente <= 0:
        return jsonify({"success": False, "error": "Total inválido"}), 400
    tipo_entrega = str(data.get("tipo_entrega") or "recojo").strip().lower()
    if tipo_entrega not in ("recojo", "delivery"):
        tipo_entrega = "recojo"

    def _get_producto(pid):
        try:
            p = db.session.get(Producto, pid)
            if p is not None:
                return p
        except Exception:
            pass
        return Producto.query.get(pid)

    try:
        # Validar stock y resolver precios desde la BD (no confiar en el cliente)
        lineas = []
        for item in items:
            try:
                pid = int(item.get("id"))
                cant = int(item.get("cantidad", 0))
            except (TypeError, ValueError, AttributeError):
                return jsonify({"success": False, "error": "Ítem inválido en el carrito"}), 400
            if cant <= 0:
                return jsonify({"success": False, "error": "Cantidad inválida"}), 400
            producto = _get_producto(pid)
            if not producto:
                return jsonify({"success": False, "error": f'Producto no encontrado: {item.get("nombre", pid)}'}), 404
            if (producto.cantidad or 0) < cant:
                return jsonify({"success": False, "error": f'Stock insuficiente: {producto.nombre}. Disponible: {producto.cantidad}'}), 409
            # Nunca cobramos de más: si el precio de oferta viniera mal
            # guardado (mayor que el normal), se cobra el menor de los dos.
            precio_normal = float(producto.precio or 0)
            precio_oferta = float(producto.precio_oferta) if producto.precio_oferta else None
            precio_server = precio_oferta if (precio_oferta and precio_oferta > 0
                                              and precio_oferta < precio_normal) else precio_normal
            lineas.append({"producto": producto, "cantidad": cant, "precio": precio_server,
                           "subtotal": round(precio_server * cant, 2)})

        cliente_data = data.get("cliente", {}) or {}
        _s = lambda v: str(v or "").strip()

        cliente_nombres = _s(cliente_data.get("nombres"))
        cliente_apellidos = _s(cliente_data.get("apellidos"))
        cliente_email = _s(cliente_data.get("email"))
        cliente_telefono = _s(cliente_data.get("telefono"))

        cliente_documento = _s(cliente_data.get("documento"))
        if not cliente_documento:
            cliente_documento = _s(cliente_data.get("dni"))
        if not cliente_documento:
            cliente_documento = _s(cliente_data.get("ruc"))

        cliente_razon_social = _s(cliente_data.get("razon_social"))
        cliente_direccion_fiscal = _s(cliente_data.get("direccion_fiscal"))
        cliente_direccion = _s(data.get("direccion")) or _s(cliente_data.get("direccion"))

        # Fallback a sesión
        if not cliente_nombres:
            cliente_nombres = session.get("cliente_nombres", "")
        if not cliente_apellidos:
            cliente_apellidos = session.get("cliente_apellidos", "")
        if not cliente_email:
            cliente_email = session.get("cliente_correo", "")
        if not cliente_telefono:
            cliente_telefono = session.get("cliente_telefono", "")
        if not cliente_documento:
            cliente_documento = session.get("cliente_dni", "")
        if not cliente_nombres or not cliente_email:
            return jsonify({"success": False, "error": "Faltan datos del cliente"}), 400
        tipo_comp = str((data.get("comprobante", {}) or {}).get("tipo", "boleta") or "boleta").strip().lower()
        if tipo_comp not in ("boleta", "factura"):
            tipo_comp = "boleta"
        if tipo_comp == "factura" and not cliente_razon_social:
            return jsonify({"success": False, "error": "Factura requiere razón social"}), 400

        # Cada modo deja el pedido en un estado distinto:
        #   culqi           -> pendiente_pago, cierra el webhook o el token
        #   pago_efectivo   -> pendiente_pago, cierra el webhook (QR / CIP)
        #   yape            -> pendiente_pago, lo valida el personal
        #   manual          -> pendiente, se cierra de una (contraentrega,
        #                      transferencia)
        modo = str(data.get("modo") or "manual").strip().lower()
        if modo not in ("culqi", "pago_efectivo", "yape", "mercadopago", "manual"):
            modo = "manual"
        if modo in ("culqi", "pago_efectivo") and not culqi.esta_configurado():
            return jsonify({"success": False, "error": "La pasarela de pagos no está configurada"}), 503
        if modo == "mercadopago" and not mercadopago.esta_configurado():
            return jsonify({"success": False, "error": "Mercado Pago no está configurado"}), 503

        if not db.session.query(UsuarioSistema.id).order_by(UsuarioSistema.id).first():
            return jsonify({"success": False, "error": "Sin vendedor configurado"}), 500

        info = {
            "nombres": cliente_nombres,
            "apellidos": cliente_apellidos,
            "documento": cliente_documento,
            "email": cliente_email,
            "telefono": cliente_telefono,
            "direccion": cliente_direccion,
            "direccion_fiscal": cliente_direccion_fiscal,
            "razon_social": cliente_razon_social,
        }

        pedido = Pedido(
            cliente_id=session["cliente_id"],
            total=round(total_cliente, 2),
            tipo_entrega=tipo_entrega,
            direccion_entrega=cliente_direccion if tipo_entrega == "delivery" else "",
            nota=_s(data.get("nota")),
            estado="pendiente_pago" if modo != "manual" else "pendiente",
        )
        db.session.add(pedido)
        db.session.flush()

        for linea in lineas:
            db.session.add(DetallePedido(
                pedido_id=pedido.id,
                producto_id=linea["producto"].id,
                cantidad=linea["cantidad"],
                precio_unitario=linea["precio"],
                subtotal=linea["subtotal"],
            ))
            # Reserva de stock: se descuenta ya y se devuelve si el pago falla.
            linea["producto"].cantidad = (linea["producto"].cantidad or 0) - linea["cantidad"]

        db.session.commit()

        if modo == "culqi":
            return _abrir_pago_culqi(pedido, info, tipo_comp, total_cliente)
        if modo == "pago_efectivo":
            return _abrir_pago_efectivo(pedido, info, tipo_comp, total_cliente)
        if modo == "yape":
            return _abrir_pago_yape(pedido, info, tipo_comp, total_cliente)
        if modo == "mercadopago":
            return _abrir_pago_mercadopago(pedido, info, tipo_comp, total_cliente)

        whatsapp_url = finalizar_pedido_pagado(pedido, info, tipo_comp)
        return jsonify({"success": True, "pedido_id": pedido.id, "whatsapp_url": whatsapp_url})

    except Exception as e:
        db.session.rollback()
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------- PEDIDOS (ADMIN) ----------------
@pedidos_bp.route('/pedidos')
@login_required
def ver_pedidos():
    es_admin = session.get("rol") == "administrador"

    # Al abrir el panel soltamos el stock de los pagos que el cliente abandonó.
    try:
        from app.routes.pagos import expirar_pagos_pendientes
        expirar_pagos_pendientes()
    except Exception as e:
        print(f"No se pudieron expirar los pagos pendientes: {e}")

    search = request.args.get('search', '').strip()
    estado_filter = request.args.get('estado', '').strip()
    fecha_desde = request.args.get('fecha_desde', '').strip()
    fecha_hasta = request.args.get('fecha_hasta', '').strip()

    total_pedidos = db.session.execute(text("SELECT COUNT(*) FROM pedidos WHERE estado != 'cancelado'")).scalar() or 0
    pedidos_pendientes = db.session.execute(text("SELECT COUNT(*) FROM pedidos WHERE estado IN ('pendiente', 'pendiente_pago')")).scalar() or 0
    pedidos_completados = db.session.execute(text("SELECT COUNT(*) FROM pedidos WHERE estado IN ('entregado', 'recogido')")).scalar() or 0
    pedidos_en_proceso = db.session.execute(text("SELECT COUNT(*) FROM pedidos WHERE estado IN ('confirmado', 'preparando', 'enviado', 'listo_tienda')")).scalar() or 0

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

    estados_disponibles = db.session.execute(text("SELECT DISTINCT estado FROM pedidos ORDER BY estado")).fetchall()
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


@pedidos_bp.route('/pedidos/detalle/<int:pedido_id>')
@login_required
def detalle_pedido(pedido_id):
    pedido = Pedido.query.get_or_404(pedido_id)
    detalles = db.session.query(DetallePedido, Producto.nombre.label("producto_nombre"))\
        .join(Producto).filter(DetallePedido.pedido_id == pedido_id).all()
    cliente = Cliente.query.get(pedido.cliente_id)
    venta = Venta.query.filter_by(numero_comprobante=f"ONLINE-{pedido_id}").first()
    es_admin = session.get("rol") == "administrador"
    pagos = pedido.pagos.order_by(Pago.id.desc()).all()

    return render_template("pedido_detalle.html",
                           pedido=pedido,
                           detalles=detalles,
                           cliente=cliente,
                           venta=venta,
                           pagos=pagos,
                           es_admin=es_admin)


@pedidos_bp.route('/pedidos/cambiar-estado/<int:pedido_id>', methods=['POST'])
@login_required
def cambiar_estado_pedido(pedido_id):
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if session.get("rol") != "administrador":
        if is_ajax:
            return jsonify({"success": False, "error": "No autorizado"}), 403
        flash("❌ Solo administradores pueden cambiar estados", "danger")
        return redirect(url_for("pedidos.ver_pedidos"))

    pedido = Pedido.query.get_or_404(pedido_id)
    nuevo_estado = request.form.get("estado")
    estados_validos = [
        "pendiente", "pendiente_pago", "confirmado", "preparando", "enviado",
        "entregado", "listo_tienda", "recogido", "cancelado"
    ]

    mensajes = {
        "pendiente": "⏳ Pedido marcado como pendiente",
        "pendiente_pago": "💳 Pedido esperando pago",
        "confirmado": "✅ Pedido confirmado",
        "preparando": "📦 Pedido en preparación",
        "enviado": "🚚 Pedido enviado a domicilio",
        "entregado": "🎁 Pedido entregado al cliente",
        "listo_tienda": "🏪 Pedido listo para recoger en tienda",
        "recogido": "🙌 Cliente recogió su pedido",
        "cancelado": "❌ Pedido cancelado"
    }

    if nuevo_estado in estados_validos:
        estado_anterior = pedido.estado
        pedido.estado = nuevo_estado
        db.session.commit()

        # Si el admin confirma un pedido que esperaba pago, el pago queda
        # saldado... pero solo si el cliente subió su comprobante. El
        # comprobante es la única prueba válida.
        if estado_anterior == "pendiente_pago" and nuevo_estado in ("confirmado", "entregado", "recogido"):
            pago = pedido.pagos.order_by(Pago.id.desc()).first()

            if pago is not None and pago.estado == "pendiente":
                if not pago.comprobante:
                    db.session.rollback()
                    pedido.estado = estado_anterior
                    db.session.commit()
                    aviso = ("El cliente todavía no subió su comprobante. "
                             "Pídele la captura del Yape antes de confirmar.")
                    if is_ajax:
                        return jsonify({"success": False, "error": aviso}), 400
                    flash(f"⚠️ {aviso}", "danger")
                    return redirect(url_for("pedidos.detalle_pedido", pedido_id=pedido_id))

                pago.estado = "pagado"
                pago.fecha_pago = datetime.now()
                pago.mensaje_error = None
                db.session.commit()
                print(f"Pago #{pago.id} saldado con comprobante {pago.comprobante} al confirmar el pedido #{pedido_id}")

        mensaje = mensajes.get(nuevo_estado, f"✅ Pedido #{pedido_id} actualizado a: {nuevo_estado}")

        if is_ajax:
            return jsonify({
                "success": True,
                "message": mensaje,
                "estado": nuevo_estado,
                "pedido_id": pedido_id
            })

        flash(mensaje, "success")
    else:
        if is_ajax:
            return jsonify({"success": False, "error": f"Estado '{nuevo_estado}' no es válido"}), 400
        flash(f"❌ Estado '{nuevo_estado}' no es válido", "danger")

    return redirect(url_for("pedidos.ver_pedidos"))


# ---------------- API MICROSERVICIO COMERCIAL ----------------
@pedidos_bp.route('/api/comercial/pedidos', methods=['GET'])
@login_required
def api_comercial_pedidos():
    if not tabla_existe("comercial_pedidos"):
        return no_configurado()
    try:
        pedidos = db.session.execute(text("SELECT * FROM comercial_pedidos ORDER BY fecha_pedido DESC")).mappings().all()
        return jsonify([dict(p) for p in pedidos])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pedidos_bp.route('/api/comercial/pedidos/<int:id>', methods=['GET'])
@login_required
def api_comercial_pedido(id):
    if not tabla_existe("comercial_pedidos") or not tabla_existe("comercial_detalle_pedido"):
        return no_configurado()
    try:
        pedido = db.session.execute(text("SELECT * FROM comercial_pedidos WHERE id = :id"), {"id": id}).mappings().first()
        if not pedido:
            return jsonify({"error": "Pedido no encontrado"}), 404

        detalles = db.session.execute(text("SELECT * FROM comercial_detalle_pedido WHERE pedido_id = :id"), {"id": id}).mappings().all()
        pedido_dict = dict(pedido)
        pedido_dict["detalles"] = [dict(d) for d in detalles]
        return jsonify(pedido_dict)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pedidos_bp.route('/api/comercial/pedidos/<int:id>/estado', methods=['PUT'])
@login_required
def api_comercial_actualizar_estado(id):
    if session.get("rol") != "administrador":
        return jsonify({"error": "No autorizado"}), 403

    if not tabla_existe("comercial_pedidos"):
        return no_configurado()

    try:
        data = request.get_json()
        estado = data.get("estado")
        if not estado:
            return jsonify({"error": "Estado requerido"}), 400

        result = db.session.execute(
            text("UPDATE comercial_pedidos SET estado = :estado WHERE id = :id"),
            {"estado": estado, "id": id}
        )
        db.session.commit()

        if result.rowcount == 0:
            return jsonify({"error": "Pedido no encontrado"}), 404

        return jsonify({"success": True, "message": "Estado actualizado"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@pedidos_bp.route('/api/comercial/ventas', methods=['GET'])
@login_required
def api_comercial_ventas():
    if not tabla_existe("comercial_ventas"):
        return no_configurado()
    try:
        ventas = db.session.execute(text("SELECT * FROM comercial_ventas ORDER BY fecha_venta DESC")).mappings().all()
        return jsonify([dict(v) for v in ventas])
    except Exception as e:
        return jsonify({"error": str(e)}), 500