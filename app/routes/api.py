# app/routes/api.py
from flask import Blueprint, request, jsonify, url_for, session, flash, redirect, render_template
from app import db
from app.models import Producto, Venta, Cliente, RucEmpresa, Categoria, Pedido
from app.utils import login_required, login_required_cliente, tabla_existe, no_configurado
from app.config import Config
from sqlalchemy import func, text, or_
from sqlalchemy.orm import joinedload
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
        if not producto:
            return jsonify({"error": "Producto no encontrado"}), 404
        return jsonify({
            "id": producto.id,
            "nombre": producto.nombre,
            "precio": float(producto.precio) if producto.precio else 0,
            "cantidad": producto.cantidad,
        })
    productos = Producto.query.filter(
        Producto.nombre.ilike(f"%{q}%"),
        Producto.cantidad > 0
    ).limit(10).all()
    return jsonify([
        {
            "id": p.id,
            "nombre": p.nombre,
            "precio": float(p.precio) if p.precio else 0,
            "cantidad": p.cantidad,
        }
        for p in productos
    ])


# ---------------- DASHBOARD RESUMEN ----------------
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


# ---------------- VALIDACIÓN DE CORREOS Y DIRECCIONES ----------------
@api_bp.route('/api/validar/correo', methods=['POST'])
@login_required
def api_validar_correo():
    """Valida un correo electrónico usando AbstractAPI."""
    from app.validacion import get_email_validator
    
    data = request.get_json() or {}
    email = (data.get("email") or "").strip()
    
    if not email:
        return jsonify({"error": "El correo es requerido"}), 400
    
    try:
        validador = get_email_validator()
        resultado = validador.validar(email)
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"error": f"Error validando correo: {e}"}), 500


@api_bp.route('/api/validar/direccion', methods=['POST'])
@login_required
def api_validar_direccion():
    """Valida y normaliza una dirección usando Google Maps Address Validation."""
    from app.validacion import get_address_validator
    
    data = request.get_json() or {}
    direccion = (data.get("direccion") or "").strip()
    
    if not direccion:
        return jsonify({"error": "La dirección es requerida"}), 400
    
    try:
        validador = get_address_validator()
        resultado = validador.validar(direccion)
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"error": f"Error validando dirección: {e}"}), 500


@api_bp.route('/api/validar/completo', methods=['POST'])
@login_required
def api_validar_completo():
    """Valida correo y dirección en una sola llamada."""
    from app.validacion import get_email_validator, get_address_validator
    
    data = request.get_json() or {}
    email = (data.get("email") or "").strip()
    direccion = (data.get("direccion") or "").strip()
    
    if not email or not direccion:
        return jsonify({"error": "Se requieren email y dirección"}), 400
    
    try:
        email_validador = get_email_validator()
        dir_validador = get_address_validator()
        
        email_result = email_validador.validar(email)
        dir_result = dir_validador.validar(direccion)
        
        return jsonify({
            "email": email_result,
            "direccion": dir_result,
            "ambos_validos": email_result.get("valido", False) and dir_result.get("valido", False)
        })
    except Exception as e:
        return jsonify({"error": f"Error en validación completa: {e}"}), 500