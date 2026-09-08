# api.py
from flask import Blueprint, jsonify, request, url_for, session
from models import db, Producto, Venta, Cliente, Pedido, RucEmpresa
from utils import login_required, login_required_cliente
from datetime import datetime
from sqlalchemy import text, func
import requests
from app.config import API_PERU_TOKEN

api_bp = Blueprint('api', __name__, url_prefix='/api')

# ---- Productos ----
@api_bp.route('/productos/<int:producto_id>/stock')
def api_producto_stock(producto_id):
    producto = Producto.query.get(producto_id)
    if not producto:
        return jsonify({"error": "Producto no encontrado"}), 404
    return jsonify({
        "id": producto.id,
        "stock": producto.cantidad,
        "nombre": producto.nombre
    })

@api_bp.route('/productos', methods=['GET'])
@login_required
def api_listar_productos():
    productos = Producto.query.filter(Producto.cantidad > 0).all()
    return jsonify([{
        "id": p.id,
        "nombre": p.nombre,
        "descripcion": p.descripcion,
        "precio": float(p.precio),
        "imagen_url": url_for("static", filename=f"img/productos/{p.imagen}") if p.imagen else None,
    } for p in productos])

@api_bp.route('/productos/catalogo')
def api_productos_catalogo():
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
        resultado.append({
            "id": p.id,
            "nombre": p.nombre,
            "descripcion": p.descripcion,
            "precio": float(p.precio) if p.precio else 0,
            "precio_oferta": float(p.precio_oferta) if p.precio_oferta else None,
            "categoria_id": p.id_categoria,
            "categoria_nombre": p.categoria_rel.nombre if p.categoria_rel else None,
            "cantidad": p.cantidad,
            "destacado": p.destacado,
            "imagen_url": url_for("static", filename=f"img/productos/{p.imagen}") if p.imagen else None,
        })
    return jsonify(resultado)

@api_bp.route('/buscar_producto')
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

@api_bp.route('/productos/top')
@login_required
def productos_top():
    top = (db.session.query(
        Producto.id, Producto.nombre, Producto.precio,
        func.sum(Venta.cantidad).label("total_vendido")
    ).join(Venta)
     .filter(func.date(Venta.fecha_venta) == datetime.now().date())
     .group_by(Producto.id)
     .order_by(func.sum(Venta.cantidad).desc())
     .limit(10).all())
    return jsonify([{
        "id": p.id,
        "nombre": p.nombre,
        "precio": float(p.precio),
        "vendidos": p.total_vendido,
    } for p in top])

# ---- Ventas ----
@api_bp.route('/ventas/rapida', methods=['POST'])
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

# ---- Clientes ----
@api_bp.route('/cliente/direccion')
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

@api_bp.route('/consultar-dni/<dni>')
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
        headers = {"Authorization": f"Bearer {API_PERU_TOKEN}", "Accept": "application/json"}
        response = requests.get(url, headers=headers, timeout=10)
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
                return jsonify({"success": False, "error": "DNI no encontrado"}), 404
        else:
            return jsonify({"success": False, "error": f"Error al consultar DNI: {response.status_code}"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@api_bp.route('/consultar-ruc/<ruc>')
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
        headers = {"Authorization": f"Bearer {API_PERU_TOKEN}", "Accept": "application/json"}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get("razonSocial"):
                razon_social = data.get("razonSocial", "")
                direccion = data.get("direccion", "")
                nueva_empresa = RucEmpresa(ruc=ruc, razon_social=razon_social, direccion=direccion)
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
                return jsonify({"success": False, "error": "RUC no encontrado"}), 404
        else:
            return jsonify({"success": False, "error": f"Error al consultar RUC: {response.status_code}"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ---- Pedidos ----
@api_bp.route('/mis-pedidos')
@login_required_cliente
def api_mis_pedidos():
    pedidos = Pedido.query.filter_by(cliente_id=session["cliente_id"]).order_by(Pedido.fecha_pedido.desc()).all()
    return jsonify([{
        "id": p.id,
        "fecha_pedido": p.fecha_pedido.strftime("%d/%m/%Y %H:%M"),
        "estado": p.estado,
        "total": float(p.total),
        "tipo_entrega": p.tipo_entrega,
    } for p in pedidos])

@api_bp.route('/pedidos/crear', methods=['POST'])
@login_required_cliente
def crear_pedido():
    data = request.get_json()
    try:
        for item in data["items"]:
            producto = Producto.query.get(item["id"])
            if not producto:
                return jsonify({"success": False, "error": f'Producto no encontrado: {item["nombre"]}'})
            if producto.cantidad < item["cantidad"]:
                return jsonify({"success": False, "error": f'Stock insuficiente: {item["nombre"]}. Disponible: {producto.cantidad}'})
        
        cliente_data = data.get("cliente", {})
        cliente_nombres = cliente_data.get("nombres", session.get("cliente_nombres", ""))
        cliente_apellidos = cliente_data.get("apellidos", session.get("cliente_apellidos", ""))
        cliente_email = cliente_data.get("email", session.get("cliente_correo", ""))
        cliente_telefono = cliente_data.get("telefono", session.get("cliente_telefono", ""))
        cliente_documento = cliente_data.get("documento", session.get("cliente_dni", ""))
        cliente_razon_social = cliente_data.get("razon_social", "")
        cliente_direccion_fiscal = cliente_data.get("direccion_fiscal", "")
        cliente_direccion = data.get("direccion", session.get("cliente_direccion", ""))

        pedido = Pedido(
            cliente_id=session["cliente_id"],
            total=float(data["total"]),
            tipo_entrega=data["tipo_entrega"],
            direccion_entrega=cliente_direccion if data["tipo_entrega"] == "delivery" else "",
        )
        db.session.add(pedido)
        db.session.flush()
        productos_para_correo = []
        for item in data["items"]:
            producto = Producto.query.get(item["id"])
            subtotal = float(item["precio"]) * int(item["cantidad"])
            detalle = DetallePedido(
                pedido_id=pedido.id,
                producto_id=item["id"],
                cantidad=int(item["cantidad"]),
                precio_unitario=float(item["precio"]),
                subtotal=subtotal,
            )
            db.session.add(detalle)
            producto.cantidad -= int(item["cantidad"])
            venta = Venta(
                producto_id=item["id"],
                cantidad=int(item["cantidad"]),
                vendedor_id=1,
                fecha_venta=datetime.now(),
                tipo_comprobante=data.get("comprobante", {}).get("tipo", "boleta"),
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
                'cantidad': int(item["cantidad"]),
                'precio_unitario': float(item["precio"]),
                'total': subtotal
            })
        db.session.commit()
        try:
            enviar_comprobante_email(
                destinatario=cliente_email,
                cliente_nombre=f"{cliente_nombres} {cliente_apellidos}".strip(),
                tipo_comprobante=data.get("comprobante", {}).get("tipo", "boleta"),
                numero_comprobante=f"ONLINE-{pedido.id}",
                fecha=datetime.now(),
                productos=productos_para_correo,
                total_venta=float(data["total"])
            )
        except Exception as e:
            print(f"Error enviando correo: {e}")
        return jsonify({"success": True, "pedido_id": pedido.id})
    except Exception as e:
        db.session.rollback()
        print(f"Error en crear_pedido: {e}")
        return jsonify({"success": False, "error": str(e)})

# ---- Bloqueos (API para administradores) ----
@api_bp.route('/bloqueos')
@login_required
def api_bloqueos():
    if session.get("rol") != "administrador":
        return jsonify({"error": "No autorizado"}), 403
    try:
        limpiar_bloqueos_expirados()
        bloqueos_bd = db.session.execute(text("""
            SELECT b.id, b.cliente_id, b.motivo, b.fecha_bloqueo, b.permanente, b.minutos_bloqueo,
                   c.correo AS cliente_correo, c.nombres AS cliente_nombres, c.apellidos AS cliente_apellidos
            FROM bloqueos b
            LEFT JOIN clientes c ON b.cliente_id = c.id
            WHERE b.tipo_usuario = 'cliente' AND b.estado = 1
              AND (b.permanente = 1 OR b.fecha_bloqueo > DATE_SUB(NOW(), INTERVAL b.minutos_bloqueo MINUTE))
            ORDER BY b.fecha_bloqueo DESC
        """)).mappings().all()
        intentos_bloqueados = db.session.execute(text("""
            SELECT i.id, i.email, i.intentos, i.email_bloqueado,
                   c.id AS cliente_id, c.nombres AS cliente_nombres, c.apellidos AS cliente_apellidos, c.correo AS cliente_correo
            FROM intentos_login i
            JOIN clientes c ON i.email = c.correo
            WHERE i.email_bloqueado IS NOT NULL AND i.email_bloqueado > NOW()
            ORDER BY i.email_bloqueado DESC
        """)).mappings().all()
        resultado = []
        emails_vistos = set()
        for b in bloqueos_bd:
            email = b['cliente_correo']
            if email in emails_vistos: continue
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
            if email in emails_vistos: continue
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

# ---- Microservicios comerciales e inventario (simulados) ----
@api_bp.route('/comercial/pedidos', methods=['GET'])
@login_required
def api_comercial_pedidos():
    try:
        pedidos = db.session.execute(text("SELECT * FROM comercial_pedidos ORDER BY fecha_pedido DESC")).mappings().all()
        return jsonify([dict(p) for p in pedidos])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/comercial/pedidos/<int:id>', methods=['GET'])
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

@api_bp.route('/comercial/pedidos/<int:id>/estado', methods=['PUT'])
@login_required
def api_comercial_actualizar_estado(id):
    if session.get("rol") != "administrador":
        return jsonify({"error": "No autorizado"}), 403
    try:
        data = request.get_json()
        estado = data.get("estado")
        if not estado:
            return jsonify({"error": "Estado requerido"}), 400
        result = db.session.execute(text("UPDATE comercial_pedidos SET estado = :estado WHERE id = :id"),
                                     {"estado": estado, "id": id})
        db.session.commit()
        if result.rowcount == 0:
            return jsonify({"error": "Pedido no encontrado"}), 404
        return jsonify({"success": True, "message": "Estado actualizado"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@api_bp.route('/comercial/ventas', methods=['GET'])
@login_required
def api_comercial_ventas():
    try:
        ventas = db.session.execute(text("SELECT * FROM comercial_ventas ORDER BY fecha_venta DESC")).mappings().all()
        return jsonify([dict(v) for v in ventas])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/inventario/productos', methods=['GET'])
@login_required
def api_inventario_productos():
    try:
        productos = db.session.execute(text("SELECT * FROM inventario_productos ORDER BY nombre")).mappings().all()
        return jsonify([dict(p) for p in productos])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/inventario/productos/<int:id>', methods=['GET'])
@login_required
def api_inventario_producto(id):
    try:
        producto = db.session.execute(text("SELECT * FROM inventario_productos WHERE id = :id"), {"id": id}).mappings().first()
        if not producto:
            return jsonify({"error": "Producto no encontrado"}), 404
        return jsonify(dict(producto))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/inventario/stock/<int:id>', methods=['PUT'])
@login_required
def api_inventario_actualizar_stock(id):
    if session.get("rol") != "administrador":
        return jsonify({"error": "No autorizado"}), 403
    try:
        data = request.get_json()
        cantidad = data.get("cantidad")
        if cantidad is None:
            return jsonify({"error": "Cantidad requerida"}), 400
        result = db.session.execute(text("UPDATE inventario_productos SET cantidad = :cantidad WHERE id = :id"),
                                     {"cantidad": cantidad, "id": id})
        db.session.commit()
        if result.rowcount == 0:
            return jsonify({"error": "Producto no encontrado"}), 404
        return jsonify({"success": True, "message": "Stock actualizado"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@api_bp.route('/inventario/stock/bajo/<int:minimo>', methods=['GET'])
@login_required
def api_inventario_bajo_stock(minimo):
    try:
        productos = db.session.execute(text("SELECT * FROM inventario_productos WHERE cantidad < :minimo ORDER BY cantidad"),
                                       {"minimo": minimo}).mappings().all()
        return jsonify([dict(p) for p in productos])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/inventario/verificar-stock/<int:id>/<int:cantidad>', methods=['GET'])
@login_required
def api_inventario_verificar_stock(id, cantidad):
    try:
        producto = db.session.execute(text("SELECT cantidad FROM inventario_productos WHERE id = :id"), {"id": id}).mappings().first()
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

@api_bp.route('/health', methods=['GET'])
def api_health():
    try:
        db.session.execute(text("SELECT 1"))
        comercial_existe = db.session.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'librospe_db' AND table_name = 'comercial_pedidos'"
        )).scalar()
        inventario_existe = db.session.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'librospe_db' AND table_name = 'inventario_productos'"
        )).scalar()
        return jsonify({
            "status": "OK",
            "services": {
                "comercial": "active" if comercial_existe else "not_configured",
                "inventario": "active" if inventario_existe else "not_configured"
            },
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({"status": "ERROR", "error": str(e), "timestamp": datetime.now().isoformat()}), 500