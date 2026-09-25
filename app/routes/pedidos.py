# app/routes/pedidos.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app import db
from app.models import Pedido, DetallePedido, Producto, Cliente, Venta, Categoria, UsuarioSistema
from app.utils import login_required, login_required_cliente, enviar_comprobante_email
from datetime import datetime
from sqlalchemy import func, text

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
    return render_template("pago.html", datetime=datetime)


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
            precio_server = float(producto.precio_oferta or producto.precio or 0)
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

        vendedor = db.session.query(UsuarioSistema.id).order_by(UsuarioSistema.id).first()
        if not vendedor:
            return jsonify({"success": False, "error": "Sin vendedor configurado"}), 500

        pedido = Pedido(
            cliente_id=session["cliente_id"],
            total=round(total_cliente, 2),
            tipo_entrega=tipo_entrega,
            direccion_entrega=cliente_direccion if tipo_entrega == "delivery" else "",
        )
        db.session.add(pedido)
        db.session.flush()

        productos_para_correo = []

        for linea in lineas:
            producto = linea["producto"]
            cant = linea["cantidad"]
            precio = linea["precio"]
            subtotal = linea["subtotal"]

            detalle = DetallePedido(
                pedido_id=pedido.id,
                producto_id=producto.id,
                cantidad=cant,
                precio_unitario=precio,
                subtotal=subtotal,
            )
            db.session.add(detalle)

            producto.cantidad = (producto.cantidad or 0) - cant

            venta = Venta(
                producto_id=producto.id,
                cantidad=cant,
                vendedor_id=vendedor[0],
                fecha_venta=datetime.now(),
                tipo_comprobante=tipo_comp,
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
                'cantidad': cant,
                'precio_unitario': precio,
                'total': subtotal
            })

        db.session.commit()

        # Enviar correo
        try:
            enviar_comprobante_email(
                destinatario=cliente_email,
                cliente_nombre=f"{cliente_nombres} {cliente_apellidos}".strip(),
                tipo_comprobante=tipo_comp,
                numero_comprobante=f"ONLINE-{pedido.id}",
                fecha=datetime.now(),
                productos=productos_para_correo,
                total_venta=round(total_cliente, 2)
            )
            print(f"Correo enviado a {cliente_email}")
        except Exception as e:
            print(f"Error al enviar correo: {e}")

        return jsonify({"success": True, "pedido_id": pedido.id})

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

    search = request.args.get('search', '').strip()
    estado_filter = request.args.get('estado', '').strip()
    fecha_desde = request.args.get('fecha_desde', '').strip()
    fecha_hasta = request.args.get('fecha_hasta', '').strip()

    total_pedidos = db.session.execute(text("SELECT COUNT(*) FROM pedidos WHERE estado != 'cancelado'")).scalar() or 0
    pedidos_pendientes = db.session.execute(text("SELECT COUNT(*) FROM pedidos WHERE estado = 'pendiente'")).scalar() or 0
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

    return render_template("pedido_detalle.html",
                           pedido=pedido,
                           detalles=detalles,
                           cliente=cliente,
                           venta=venta,
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
        "pendiente", "confirmado", "preparando", "enviado",
        "entregado", "listo_tienda", "recogido", "cancelado"
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
    else:
        if is_ajax:
            return jsonify({"success": False, "error": f"Estado '{nuevo_estado}' no es válido"}), 400
        flash(f"❌ Estado '{nuevo_estado}' no es válido", "danger")

    return redirect(url_for("pedidos.ver_pedidos"))


# ---------------- API MICROSERVICIO COMERCIAL ----------------
@pedidos_bp.route('/api/comercial/pedidos', methods=['GET'])
@login_required
def api_comercial_pedidos():
    try:
        pedidos = db.session.execute(text("SELECT * FROM comercial_pedidos ORDER BY fecha_pedido DESC")).mappings().all()
        return jsonify([dict(p) for p in pedidos])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@pedidos_bp.route('/api/comercial/pedidos/<int:id>', methods=['GET'])
@login_required
def api_comercial_pedido(id):
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
    try:
        ventas = db.session.execute(text("SELECT * FROM comercial_ventas ORDER BY fecha_venta DESC")).mappings().all()
        return jsonify([dict(v) for v in ventas])
    except Exception as e:
        return jsonify({"error": str(e)}), 500