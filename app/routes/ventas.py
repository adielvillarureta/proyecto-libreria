# app/routes/ventas.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app import db
from app.models import Venta, Producto, UsuarioSistema, Pedido, DetallePedido, Cliente
from app.utils import (
    login_required, requerir_permisos_escritura,
    enviar_comprobante_email, login_required_cliente
)
from datetime import datetime
from sqlalchemy import func, text

ventas_bp = Blueprint('ventas', __name__)


# ---------------- VENTAS ----------------
@ventas_bp.route('/ventas/nueva', methods=['GET', 'POST'])
@login_required
def venta_nueva():
    lista_productos = Producto.query.filter(Producto.cantidad > 0).order_by(Producto.nombre).all()

    if session.get("rol") == "administrador":
        vendedores = UsuarioSistema.query.filter(
            UsuarioSistema.rol.in_(['administrador', 'vendedor'])
        ).order_by(UsuarioSistema.nombres).all()
    else:
        vendedor = UsuarioSistema.query.filter_by(id=session.get("usuario_id")).first()
        vendedores = [vendedor] if vendedor else []

    if request.method == "POST":
        try:
            producto_id = int(request.form["producto_id"])
            cantidad = int(request.form["cantidad"])
            fecha_venta = datetime.now()
            tipo_comprobante = request.form.get("tipo_comprobante", "boleta")

            if session.get("rol") == "administrador":
                vendedor_id = int(request.form.get("vendedor_id", session.get("usuario_id")))
            else:
                vendedor_id = session.get("usuario_id")

            cliente_email = request.form.get("cliente_email", "")
            cliente_nombres = request.form.get("cliente_nombres", "")
            enviar_email = request.form.get("enviar_email", "0")

            numero_comprobante = f"{datetime.now().strftime('%Y%m%d')}-{datetime.now().strftime('%H%M%S')}"

            producto = Producto.query.get(producto_id)
            if not producto:
                flash("❌ Producto no encontrado", "danger")
                return render_template("ventas_form.html", productos=lista_productos, vendedores=vendedores, now=datetime.now())

            if producto.cantidad < cantidad:
                flash(f"❌ Stock insuficiente. Disponible: {producto.cantidad}", "danger")
                return render_template("ventas_form.html", productos=lista_productos, vendedores=vendedores, now=datetime.now())

            precio_unitario = float(producto.precio or 0)
            total_venta = precio_unitario * cantidad

            nueva_venta = Venta(
                producto_id=producto_id,
                cantidad=cantidad,
                fecha_venta=fecha_venta,
                vendedor_id=vendedor_id,
                tipo_comprobante=tipo_comprobante,
                numero_comprobante=numero_comprobante,
            )
            db.session.add(nueva_venta)
            producto.cantidad -= cantidad
            db.session.commit()

            if enviar_email == "1" and cliente_email and '@' in cliente_email:
                try:
                    enviar_comprobante_email(
                        destinatario=cliente_email,
                        cliente_nombre=cliente_nombres if cliente_nombres else "Cliente",
                        tipo_comprobante=tipo_comprobante,
                        numero_comprobante=numero_comprobante,
                        fecha=fecha_venta,
                        productos=[{
                            'nombre': producto.nombre,
                            'cantidad': cantidad,
                            'precio_unitario': precio_unitario,
                            'total': total_venta
                        }],
                        total_venta=total_venta
                    )
                    flash(f"✅ {tipo_comprobante.upper()} registrada y enviada a {cliente_email}", "success")
                except Exception as e:
                    print(f"❌ Error enviando email: {e}")
                    flash("⚠️ Venta registrada, pero error al enviar correo", "warning")
            else:
                flash(f"✅ Venta #{nueva_venta.id} registrada - Total: S/. {total_venta:.2f}", "success")

            return redirect(url_for("ventas.ver_comprobante", venta_id=nueva_venta.id))

        except Exception as e:
            db.session.rollback()
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            flash(f"❌ Error al registrar la venta: {str(e)}", "danger")
            return render_template("ventas_form.html", productos=lista_productos, vendedores=vendedores, now=datetime.now())

    return render_template("ventas_form.html", productos=lista_productos, vendedores=vendedores, now=datetime.now())


@ventas_bp.route('/ventas')
@login_required
def listar_ventas():
    try:
        if session.get("rol") == "vendedor":
            vendedor_filtro = session.get("usuario_id")
        else:
            vendedor_filtro = request.args.get('vendedor_id', type=int)

        query = """
            SELECT
                v.id,
                v.cantidad,
                v.fecha_venta,
                v.tipo_comprobante,
                v.numero_comprobante,
                p.nombre as producto,
                p.precio,
                u.id as vendedor_id,
                u.nombres as vendedor_nombres,
                u.apellidos as vendedor_apellidos
            FROM ventas v
            JOIN productos p ON v.producto_id = p.id
            LEFT JOIN usuarios_sistema u ON v.vendedor_id = u.id
        """
        params = {}
        if vendedor_filtro:
            query += " WHERE v.vendedor_id = :vendedor_id"
            params['vendedor_id'] = vendedor_filtro
        query += " ORDER BY v.id DESC"

        resultados = db.session.execute(text(query), params).mappings().all()

        ventas_lista = []
        for row in resultados:
            venta_dict = dict(row)
            venta_dict['precio_unitario'] = float(venta_dict.get('precio') or 0)
            venta_dict['total_venta'] = venta_dict['precio_unitario'] * venta_dict.get('cantidad', 1)
            ventas_lista.append(venta_dict)

        vendedores = []
        vendedor_seleccionado = None
        vendedor_id_actual = None
        if session.get("rol") == "administrador":
            vendedores = UsuarioSistema.query.filter_by(rol='vendedor').all()
            vendedor_id_actual = vendedor_filtro
            if vendedor_filtro:
                vendedor_seleccionado = UsuarioSistema.query.get(vendedor_filtro)

        return render_template("ventas.html",
                               ventas=ventas_lista,
                               vendedores=vendedores,
                               vendedor_seleccionado=vendedor_seleccionado,
                               vendedor_id_actual=vendedor_id_actual,
                               rol_usuario=session.get("rol"))
    except Exception as e:
        print(f"Error en ventas: {e}")
        flash(f"Error al cargar ventas: {str(e)}", "danger")
        return render_template("ventas.html", ventas=[], vendedores=[])


@ventas_bp.route('/comprobante/<int:venta_id>')
@login_required
def ver_comprobante(venta_id):
    venta = db.session.query(
        Venta,
        Producto.nombre.label("producto_nombre"),
        Producto.precio,
        UsuarioSistema.nombres.label("vendedor_nombres"),
        UsuarioSistema.apellidos.label("vendedor_apellidos")
    ).join(Producto, Venta.producto_id == Producto.id)\
     .outerjoin(UsuarioSistema, Venta.vendedor_id == UsuarioSistema.id)\
     .filter(Venta.id == venta_id).first()

    if not venta:
        flash("❌ Venta no encontrada", "danger")
        return redirect(url_for("ventas.listar_ventas"))

    total = venta.Venta.cantidad * venta.precio
    return render_template("comprobante.html", venta=venta, total=total)


@ventas_bp.route('/ver_ventas', methods=['GET', 'POST'])
@login_required
@requerir_permisos_escritura
def ver_ventas():
    ventas_lista = []
    totalProductos = 0
    totalPrecio = 0
    fecha_seleccionada = request.args.get("fecha") or request.form.get("fecha")
    if fecha_seleccionada:
        fecha_obj = datetime.strptime(fecha_seleccionada, "%Y-%m-%d").date()
        ventas_lista = (
            db.session.query(
                Venta.id,
                func.concat(UsuarioSistema.nombres, " ", UsuarioSistema.apellidos).label("vendedor"),
                Producto.nombre.label("producto"),
                Venta.cantidad,
                Venta.fecha_venta,
                Producto.precio,
                (Venta.cantidad * Producto.precio).label("subtotal"),
            )
            .join(Producto, Venta.producto_id == Producto.id)
            .outerjoin(UsuarioSistema, Venta.vendedor_id == UsuarioSistema.id)
            .filter(func.date(Venta.fecha_venta) == fecha_obj)
            .order_by(Venta.id.asc())
            .all()
        )
        ventas_lista = [
            {
                "id": v.id,
                "vendedor": v.vendedor,
                "producto": v.producto,
                "cantidad": v.cantidad,
                "fecha_venta": v.fecha_venta,
                "precio": float(v.precio),
                "subtotal": float(v.subtotal),
            }
            for v in ventas_lista
        ]
        totalProductos = sum(v["cantidad"] for v in ventas_lista)
        totalPrecio = sum(v["cantidad"] * v["precio"] for v in ventas_lista)
    return render_template("ver_ventas.html",
                           ventas=ventas_lista,
                           totalProductos=totalProductos,
                           totalPrecio=totalPrecio,
                           fecha_seleccionada=fecha_seleccionada)


# ---------------- PROCESAR PAGO ----------------
@ventas_bp.route('/procesar_pago', methods=['POST'])
@login_required_cliente
def procesar_pago():
    try:
        data = request.get_json()
        email_cliente = data.get("email")
        nombres = data.get("nombres")
        apellidos = data.get("apellidos")
        total = data.get("total")
        tipo_comprobante = data.get("tipo_comprobante")
        productos = data.get("productos", [])

        exito = enviar_comprobante_email(
            destinatario=email_cliente,
            cliente_nombre=f"{nombres} {apellidos}".strip(),
            tipo_comprobante=tipo_comprobante,
            numero_comprobante=f"PAGO-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            fecha=datetime.now(),
            productos=productos,
            total_venta=total
        )
        if exito:
            return jsonify({"success": True, "message": "Correo enviado correctamente"})
        else:
            return jsonify({"success": False, "message": "Error al enviar correo"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})