# app/routes/api.py
from flask import Blueprint, request, jsonify, url_for, session, flash, redirect, render_template
from app import db
from app.models import Producto, Venta, Cliente, RucEmpresa, Categoria, Pedido
from app.utils import login_required, login_required_cliente
from app.config import Config
from sqlalchemy import func, text, or_
from datetime import datetime, timedelta
import requests

api_bp = Blueprint('api', __name__)


# ---------------- STOCK DE PRODUCTOS ----------------
@api_bp.route('/api/productos/<int:producto_id>/stock')
def api_producto_stock(producto_id):
    producto = Producto.query.get(producto_id)
    if not producto:
        return jsonify({"error": "Producto no encontrado"}), 404
    return jsonify({
        "id": producto.id,
        "stock": producto.cantidad,
        "nombre": producto.nombre
    })


@api_bp.route('/api/productos', methods=["GET"])
@login_required
def api_listar_productos():
    productos = Producto.query.filter(Producto.cantidad > 0).all()
    return jsonify([
        {
            "id": p.id,
            "nombre": p.nombre,
            "descripcion": p.descripcion,
            "precio": float(p.precio) if p.precio else 0,
            "imagen_url": url_for("static", filename=f"img/productos/{p.imagen}") if p.imagen else None,
        }
        for p in productos
    ])


@api_bp.route('/api/buscar_producto')
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


@api_bp.route('/api/productos/top')
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


@api_bp.route('/api/ventas/rapida', methods=["POST"])
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


@api_bp.route('/api/productos/catalogo')
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


# ---------------- CLIENTE ----------------
@api_bp.route('/api/cliente/direccion')
@login_required_cliente
def api_cliente_direccion():
    try:
        cliente_id = session.get("cliente_id")
        if not cliente_id:
            return jsonify({"success": False, "direccion": "", "error": "No session"})

        cliente = Cliente.query.get(cliente_id)
        if not cliente:
            return jsonify({"success": False, "direccion": "", "error": "Cliente no encontrado"})

        return jsonify({"success": True, "direccion": cliente.direccion or ""})
    except Exception as e:
        return jsonify({"success": False, "direccion": "", "error": str(e)})


# ---------------- DNI / RUC ----------------
def _consultar_apis_peru(ruta, timeout=10):
    """Consulta el API de ApisPerú (RENIEC/SUNAT). Reintenta una vez ante errores 5xx."""
    url = f"https://dniruc.apisperu.com/api/v1/{ruta}"
    headers = {
        "Authorization": f"Bearer {Config.API_PERU_TOKEN}",
        "Accept": "application/json"
    }
    respuesta = requests.get(url, headers=headers, timeout=timeout)
    if respuesta.status_code >= 500:
        print("⚠️ ApiPerú respondió " + str(respuesta.status_code) + ", reintentando...")
        respuesta = requests.get(url, headers=headers, timeout=timeout)
    return respuesta


@api_bp.route('/api/consultar-dni/<dni>')
@login_required_cliente
def api_consultar_dni_cliente(dni):
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
        print(f"🔍 Consultando DNI {dni} en ApisPerú...")
        response = _consultar_apis_peru(f"dni/{dni}")
        print(f"📡 Respuesta: {response.status_code}")

        if response.status_code == 401:
            return jsonify({
                "success": False,
                "error": "El token de API Perú es inválido o venció. Actualízalo en https://apisperu.com (variable API_PERU_TOKEN del .env)."
            }), 401

        if response.status_code == 404:
            return jsonify({"success": False, "error": "DNI no encontrado en RENIEC"}), 404

        if response.status_code != 200:
            return jsonify({"success": False, "error": f"RENIEC no está disponible ahora ({response.status_code}). Inténtalo en unos segundos."}), 502

        data = response.json()

        # ApisPerú responde 200 pero con success=False cuando no encuentra el documento
        if data.get("success") is False:
            return jsonify({"success": False, "error": "DNI no encontrado en RENIEC"}), 404

        if data.get("nombres"):
            nombres = data.get("nombres", "")
            apellidos = f"{data.get('apellidoPaterno', '')} {data.get('apellidoMaterno', '')}".strip()
        elif data.get("Nombre"):
            nombres = data.get("Nombre", "")
            apellidos = f"{data.get('ApellidoPaterno', '')} {data.get('ApellidoMaterno', '')}".strip()
        else:
            return jsonify({"success": False, "error": "DNI no encontrado en RENIEC"}), 404

        return jsonify({
            "success": True,
            "nombres": nombres,
            "apellidos": apellidos,
            "dni": dni,
            "origen": "apis_peru"
        })

    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "Tiempo de espera agotado. Inténtalo de nuevo."}), 503
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "error": f"Error de conexión con RENIEC: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"success": False, "error": f"Error inesperado: {str(e)}"}), 500


@api_bp.route('/api/consultar-ruc/<ruc>')
@login_required_cliente
def api_consultar_ruc_cliente(ruc):
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
        print(f"🔍 Consultando RUC {ruc} en ApisPerú...")
        response = _consultar_apis_peru(f"ruc/{ruc}")
        print(f"📡 Respuesta: {response.status_code}")

        if response.status_code == 401:
            return jsonify({
                "success": False,
                "error": "El token de API Perú es inválido o venció. Actualízalo en https://apisperu.com (variable API_PERU_TOKEN del .env)."
            }), 401

        if response.status_code == 404:
            return jsonify({"success": False, "error": "RUC no encontrado en SUNAT"}), 404

        if response.status_code != 200:
            return jsonify({"success": False, "error": f"SUNAT no está disponible ahora ({response.status_code}). Inténtalo en unos segundos."}), 502

        data = response.json()

        if data.get("success") is False:
            return jsonify({"success": False, "error": "RUC no encontrado en SUNAT"}), 404

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
            return jsonify({"success": False, "error": "RUC no encontrado en SUNAT"}), 404

    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "Tiempo de espera agotado. Inténtalo de nuevo."}), 503
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "error": f"Error de conexión con SUNAT: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"success": False, "error": f"Error inesperado: {str(e)}"}), 500


# ---------------- MICROSERVICIO INVENTARIO ----------------
@api_bp.route('/api/inventario/productos', methods=["GET"])
@login_required
def api_inventario_productos():
    try:
        productos = db.session.execute(text("SELECT * FROM inventario_productos ORDER BY nombre")).mappings().all()
        return jsonify([dict(p) for p in productos])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/api/inventario/productos/<int:id>', methods=["GET"])
@login_required
def api_inventario_producto(id):
    try:
        producto = db.session.execute(
            text("SELECT * FROM inventario_productos WHERE id = :id"),
            {"id": id}
        ).mappings().first()
        if not producto:
            return jsonify({"error": "Producto no encontrado"}), 404
        return jsonify(dict(producto))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/api/inventario/stock/<int:id>', methods=["PUT"])
@login_required
def api_inventario_actualizar_stock(id):
    if session.get("rol") not in ["administrador"]:
        return jsonify({"error": "No autorizado"}), 403

    try:
        data = request.get_json()
        cantidad = data.get("cantidad")
        if cantidad is None:
            return jsonify({"error": "Cantidad requerida"}), 400

        result = db.session.execute(
            text("UPDATE inventario_productos SET cantidad = :cantidad WHERE id = :id"),
            {"cantidad": cantidad, "id": id}
        )
        db.session.commit()

        if result.rowcount == 0:
            return jsonify({"error": "Producto no encontrado"}), 404

        return jsonify({"success": True, "message": "Stock actualizado"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route('/api/inventario/stock/bajo/<int:minimo>', methods=["GET"])
@login_required
def api_inventario_bajo_stock(minimo):
    try:
        productos = db.session.execute(
            text("SELECT * FROM inventario_productos WHERE cantidad < :minimo ORDER BY cantidad"),
            {"minimo": minimo}
        ).mappings().all()
        return jsonify([dict(p) for p in productos])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/api/inventario/verificar-stock/<int:id>/<int:cantidad>', methods=["GET"])
@login_required
def api_inventario_verificar_stock(id, cantidad):
    try:
        producto = db.session.execute(
            text("SELECT cantidad FROM inventario_productos WHERE id = :id"),
            {"id": id}
        ).mappings().first()

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


# ---------------- HEALTH ----------------
@api_bp.route('/api/health', methods=["GET"])
@api_bp.route('/health', methods=["GET"])
def api_health():
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


# ---------------- DASHBOARD MICROSERVICIOS ----------------
@api_bp.route('/microservicios/dashboard')
@login_required
def microservicios_dashboard():
    if session.get("rol") != "administrador":
        flash("❌ Solo administradores pueden ver este panel", "danger")
        return redirect(url_for("main.dashboard"))

    total_pedidos = db.session.execute(text("SELECT COUNT(*) FROM comercial_pedidos")).scalar() or 0
    pedidos_pendientes = db.session.execute(text("SELECT COUNT(*) FROM comercial_pedidos WHERE estado = 'pendiente'")).scalar() or 0
    pedidos_confirmados = db.session.execute(text("SELECT COUNT(*) FROM comercial_pedidos WHERE estado = 'confirmado'")).scalar() or 0

    total_productos = db.session.execute(text("SELECT COUNT(*) FROM inventario_productos")).scalar() or 0
    productos_bajo_stock = db.session.execute(text("SELECT COUNT(*) FROM inventario_productos WHERE cantidad < 10")).scalar() or 0
    productos_agotados = db.session.execute(text("SELECT COUNT(*) FROM inventario_productos WHERE cantidad = 0")).scalar() or 0

    return render_template("microservicios_dashboard.html",
                           total_pedidos=total_pedidos,
                           pedidos_pendientes=pedidos_pendientes,
                           pedidos_confirmados=pedidos_confirmados,
                           total_productos=total_productos,
                           productos_bajo_stock=productos_bajo_stock,
                           productos_agotados=productos_agotados)


def _solo_fecha(valor):
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Fecha inválida '%s'. Usa el formato YYYY-MM-DD" % valor)


def _solo_fecha_fin(valor):
    fecha = _solo_fecha(valor)
    if fecha:
        fecha = fecha.replace(hour=23, minute=59, second=59)
    return fecha


def _venta_json(v):
    producto = v.producto
    precio = float(producto.precio) if producto and producto.precio else 0.0
    cliente = " ".join(x for x in [v.cliente_nombres, v.cliente_apellidos] if x)
    return {
        "id": v.id,
        "fecha_venta": v.fecha_venta.isoformat() if v.fecha_venta else None,
        "producto_id": v.producto_id,
        "producto_nombre": producto.nombre if producto else None,
        "cantidad": v.cantidad,
        "precio_unitario": precio,
        "monto": round(precio * (v.cantidad or 0), 2),
        "tipo_comprobante": v.tipo_comprobante,
        "numero_comprobante": v.numero_comprobante,
        "cliente": cliente or None,
        "estado": v.estado,
    }


@api_bp.route('/api/categorias')
def api_listar_categorias():
    try:
        filas = (
            db.session.query(
                Categoria.id_categoria,
                Categoria.nombre,
                Categoria.descripcion,
                func.count(Producto.id).label("total_productos"),
            )
            .outerjoin(Producto, Producto.id_categoria == Categoria.id_categoria)
            .filter(Categoria.activo == True)
            .group_by(Categoria.id_categoria)
            .order_by(Categoria.nombre)
            .all()
        )
        return jsonify([
            {
                "id": f.id_categoria,
                "nombre": f.nombre,
                "descripcion": f.descripcion,
                "total_productos": int(f.total_productos or 0),
            }
            for f in filas
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/api/productos/<int:producto_id>')
def api_producto_detalle(producto_id):
    producto = Producto.query.get(producto_id)
    if not producto:
        return jsonify({"error": "Producto no encontrado"}), 404
    categoria = getattr(producto, "categoria_rel", None)
    return jsonify({
        "id": producto.id,
        "nombre": producto.nombre,
        "descripcion": producto.descripcion,
        "precio": float(producto.precio) if producto.precio else 0,
        "precio_oferta": float(producto.precio_oferta) if producto.precio_oferta else None,
        "stock": producto.cantidad,
        "destacado": producto.destacado,
        "codigo_barras": producto.codigo_barras,
        "categoria": {
            "id": categoria.id_categoria,
            "nombre": categoria.nombre,
        } if categoria else None,
        "imagen_url": url_for("static", filename=f"img/productos/{producto.imagen}") if producto.imagen else None,
    })


@api_bp.route('/api/clientes')
@login_required
def api_listar_clientes():
    try:
        q = request.args.get("q", "").strip()
        limite = min(request.args.get("limit", type=int) or 50, 200)
        query = Cliente.query
        if q:
            like = f"%{q}%"
            query = query.filter(or_(
                Cliente.nombres.like(like),
                Cliente.apellidos.like(like),
                Cliente.correo.like(like),
                Cliente.dni.like(like),
            ))
        clientes = query.order_by(Cliente.fecha_registro.desc()).limit(limite).all()
        return jsonify([
            {
                "id": c.id,
                "dni": c.dni,
                "nombres": c.nombres,
                "apellidos": c.apellidos,
                "correo": c.correo,
                "telefono": c.telefono,
                "direccion": c.direccion,
                "puntos": c.puntos,
                "estado": c.estado,
                "fecha_registro": c.fecha_registro.isoformat() if c.fecha_registro else None,
            }
            for c in clientes
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/api/clientes/<int:cliente_id>')
@login_required
def api_cliente_detalle(cliente_id):
    cliente = Cliente.query.get(cliente_id)
    if not cliente:
        return jsonify({"error": "Cliente no encontrado"}), 404
    return jsonify({
        "id": cliente.id,
        "dni": cliente.dni,
        "nombres": cliente.nombres,
        "apellidos": cliente.apellidos,
        "correo": cliente.correo,
        "telefono": cliente.telefono,
        "direccion": cliente.direccion,
        "puntos": cliente.puntos,
        "estado": cliente.estado,
        "fecha_registro": cliente.fecha_registro.isoformat() if cliente.fecha_registro else None,
        "total_pedidos": len(cliente.pedidos or []),
    })


@api_bp.route('/api/ventas')
@login_required
def api_listar_ventas():
    try:
        desde = _solo_fecha(request.args.get("desde"))
        hasta = _solo_fecha_fin(request.args.get("hasta"))
        limite = min(request.args.get("limit", type=int) or 50, 200)
        query = Venta.query
        if desde:
            query = query.filter(Venta.fecha_venta >= desde)
        if hasta:
            query = query.filter(Venta.fecha_venta <= hasta)
        ventas = query.order_by(Venta.fecha_venta.desc()).limit(limite).all()
        return jsonify([_venta_json(v) for v in ventas])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/api/ventas/<int:venta_id>')
@login_required
def api_venta_detalle(venta_id):
    venta = Venta.query.get(venta_id)
    if not venta:
        return jsonify({"error": "Venta no encontrada"}), 404
    data = _venta_json(venta)
    data["vendedor_id"] = venta.vendedor_id
    data["cliente_id"] = venta.cliente_id
    return jsonify(data)


@api_bp.route('/api/ventas/resumen')
@login_required
def api_ventas_resumen():
    try:
        desde = _solo_fecha(request.args.get("desde"))
        hasta = _solo_fecha_fin(request.args.get("hasta"))
        query = db.session.query(
            func.count(Venta.id),
            func.coalesce(func.sum(Venta.cantidad * Producto.precio), 0),
            func.coalesce(func.sum(Venta.cantidad), 0),
        ).join(Producto, Venta.producto_id == Producto.id)
        if desde:
            query = query.filter(Venta.fecha_venta >= desde)
        if hasta:
            query = query.filter(Venta.fecha_venta <= hasta)
        total_ventas, monto_total, unidades = query.one()
        return jsonify({
            "total_ventas": int(total_ventas or 0),
            "monto_total": round(float(monto_total or 0), 2),
            "unidades": int(unidades or 0),
            "desde": request.args.get("desde"),
            "hasta": request.args.get("hasta"),
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/api/pedidos')
@login_required
def api_listar_pedidos():
    try:
        estado = request.args.get("estado", "").strip()
        limite = min(request.args.get("limit", type=int) or 50, 200)
        query = Pedido.query
        if estado:
            query = query.filter(Pedido.estado == estado)
        pedidos = query.order_by(Pedido.fecha_pedido.desc()).limit(limite).all()
        return jsonify([
            {
                "id": p.id,
                "cliente_id": p.cliente_id,
                "cliente": f"{p.cliente.nombres} {p.cliente.apellidos}" if p.cliente else None,
                "fecha_pedido": p.fecha_pedido.isoformat() if p.fecha_pedido else None,
                "estado": p.estado,
                "total": float(p.total) if p.total else 0.0,
                "tipo_entrega": p.tipo_entrega,
                "direccion_entrega": p.direccion_entrega,
                "items": len(p.detalles or []),
            }
            for p in pedidos
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/api/pedidos/<int:pedido_id>')
@login_required
def api_pedido_detalle(pedido_id):
    pedido = Pedido.query.get(pedido_id)
    if not pedido:
        return jsonify({"error": "Pedido no encontrado"}), 404
    return jsonify({
        "id": pedido.id,
        "cliente_id": pedido.cliente_id,
        "cliente": f"{pedido.cliente.nombres} {pedido.cliente.apellidos}" if pedido.cliente else None,
        "fecha_pedido": pedido.fecha_pedido.isoformat() if pedido.fecha_pedido else None,
        "estado": pedido.estado,
        "total": float(pedido.total) if pedido.total else 0.0,
        "tipo_entrega": pedido.tipo_entrega,
        "direccion_entrega": pedido.direccion_entrega,
        "nota": pedido.nota,
        "detalles": [
            {
                "id": d.id,
                "producto_id": d.producto_id,
                "producto": d.producto.nombre if d.producto else None,
                "cantidad": d.cantidad,
                "precio_unitario": float(d.precio_unitario) if d.precio_unitario else 0.0,
                "subtotal": float(d.subtotal) if d.subtotal else 0.0,
            }
            for d in (pedido.detalles or [])
        ],
    })


@api_bp.route('/api/pedidos/resumen')
@login_required
def api_pedidos_resumen():
    try:
        filas = db.session.query(
            Pedido.estado, func.count(Pedido.id)
        ).group_by(Pedido.estado).all()
        por_estado = {estado: int(total) for estado, total in filas}
        return jsonify({
            "total": sum(por_estado.values()),
            "por_estado": por_estado,
            "pendientes": por_estado.get("pendiente", 0),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/api/stock/alertas')
@login_required
def api_stock_alertas():
    try:
        minimo = request.args.get("minimo", default=10, type=int)
        productos = Producto.query.filter(
            Producto.cantidad <= minimo
        ).order_by(Producto.cantidad.asc()).all()
        return jsonify({
            "minimo": minimo,
            "total": len(productos),
            "agotados": sum(1 for p in productos if (p.cantidad or 0) == 0),
            "productos": [
                {
                    "id": p.id,
                    "nombre": p.nombre,
                    "stock": p.cantidad,
                    "precio": float(p.precio) if p.precio else 0,
                    "estado": "agotado" if (p.cantidad or 0) == 0 else "bajo",
                }
                for p in productos
            ],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route('/api/dashboard/resumen')
@login_required
def api_dashboard_resumen():
    try:
        hoy = datetime.now().date()
        inicio_mes = hoy.replace(day=1)
        semana = datetime.now() - timedelta(days=7)

        ventas_hoy = db.session.query(
            func.count(Venta.id),
            func.coalesce(func.sum(Venta.cantidad * Producto.precio), 0),
        ).join(Producto, Venta.producto_id == Producto.id)\
         .filter(func.date(Venta.fecha_venta) == hoy).one()

        ventas_mes = db.session.query(
            func.count(Venta.id),
            func.coalesce(func.sum(Venta.cantidad * Producto.precio), 0),
        ).join(Producto, Venta.producto_id == Producto.id)\
         .filter(func.date(Venta.fecha_venta) >= inicio_mes).one()

        return jsonify({
            "fecha": datetime.now().isoformat(),
            "ventas_hoy": {
                "cantidad": int(ventas_hoy[0] or 0),
                "monto": round(float(ventas_hoy[1] or 0), 2),
            },
            "ventas_mes": {
                "cantidad": int(ventas_mes[0] or 0),
                "monto": round(float(ventas_mes[1] or 0), 2),
            },
            "pedidos_pendientes": Pedido.query.filter_by(estado="pendiente").count(),
            "pedidos_en_proceso": Pedido.query.filter(
                Pedido.estado.in_(["confirmado", "preparando", "enviado", "listo_tienda"])
            ).count(),
            "clientes_total": Cliente.query.count(),
            "clientes_nuevos_7d": Cliente.query.filter(
                Cliente.fecha_registro >= semana
            ).count(),
            "productos_stock_bajo": Producto.query.filter(
                Producto.cantidad > 0, Producto.cantidad <= 10
            ).count(),
            "productos_agotados": Producto.query.filter(
                Producto.cantidad == 0
            ).count(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500