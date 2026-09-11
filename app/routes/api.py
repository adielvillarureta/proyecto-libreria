# app/routes/api.py
from flask import Blueprint, request, jsonify, url_for, session, flash, redirect
from app import db
from app.models import Producto, Venta, Cliente, RucEmpresa
from app.utils import login_required, login_required_cliente
from app.config import Config
from sqlalchemy import func, text
from datetime import datetime
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
        url = f"https://dniruc.apisperu.com/api/v1/dni/{dni}"
        headers = {
            "Authorization": f"Bearer {Config.API_PERU_TOKEN}",
            "Accept": "application/json"
        }

        print(f"🔍 Consultando DNI {dni} en ApisPerú...")
        response = requests.get(url, headers=headers, timeout=10)
        print(f"📡 Respuesta: {response.status_code}")

        if response.status_code == 200:
            data = response.json()

            if data.get("nombres"):
                return jsonify({
                    "success": True,
                    "nombres": data.get("nombres", ""),
                    "apellidos": f"{data.get('apellidoPaterno', '')} {data.get('apellidoMaterno', '')}".strip(),
                    "dni": dni,
                    "origen": "apis_peru"
                })
            elif data.get("Nombre"):
                return jsonify({
                    "success": True,
                    "nombres": data.get("Nombre", ""),
                    "apellidos": f"{data.get('ApellidoPaterno', '')} {data.get('ApellidoMaterno', '')}".strip(),
                    "dni": dni,
                    "origen": "apis_peru"
                })
            else:
                return jsonify({
                    "success": True,
                    "nombres": request.args.get("nombres", ""),
                    "apellidos": request.args.get("apellidos", ""),
                    "dni": dni,
                    "origen": "usuario",
                    "mensaje": "DNI válido pero sin nombres completos"
                })
        elif response.status_code == 404:
            return jsonify({"success": False, "error": "DNI no encontrado en RENIEC"}), 404
        else:
            return jsonify({"success": False, "error": f"Error al consultar DNI: {response.status_code}"}), 500

    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "Tiempo de espera agotado"}), 500
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "error": f"Error de conexión: {str(e)}"}), 500
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
        url = f"https://dniruc.apisperu.com/api/v1/ruc/{ruc}"
        headers = {
            "Authorization": f"Bearer {Config.API_PERU_TOKEN}",
            "Accept": "application/json"
        }

        print(f"🔍 Consultando RUC {ruc} en ApisPerú...")
        response = requests.get(url, headers=headers, timeout=10)
        print(f"📡 Respuesta: {response.status_code}")

        if response.status_code == 200:
            data = response.json()

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
        elif response.status_code == 404:
            return jsonify({"success": False, "error": "RUC no encontrado en SUNAT"}), 404
        else:
            return jsonify({"success": False, "error": f"Error al consultar RUC: {response.status_code}"}), 500

    except requests.exceptions.Timeout:
        return jsonify({"success": False, "error": "Tiempo de espera agotado"}), 500
    except requests.exceptions.RequestException as e:
        return jsonify({"success": False, "error": f"Error de conexión: {str(e)}"}), 500


# ---------------- DEBUG ----------------
@api_bp.route('/debug-token')
def debug_token():
    return jsonify({
        "token_existe": bool(Config.API_PERU_TOKEN),
        "token_preview": Config.API_PERU_TOKEN[:20] + "..." if Config.API_PERU_TOKEN else None,
        "db_host": "mysql-librospe.alwaysdata.net"
    })


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