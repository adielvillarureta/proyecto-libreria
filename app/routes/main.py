# app/routes/main.py
from flask import Blueprint, render_template, session, flash, redirect, url_for
from app import db
from app.models import Venta, Pedido, Cliente, Producto, Categoria
from app.utils import login_required
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import plotly
import plotly.graph_objs as go
from sqlalchemy import func, text

main_bp = Blueprint('main', __name__)

PERU_TZ = ZoneInfo("America/Lima")


@main_bp.route('/')
def inicio():
    categorias = Categoria.query.filter_by(activo=True).all()
    return render_template('index.html', categorias=categorias)


@main_bp.route('/acerca-de')
def acerca_de():
    return render_template('acerca_de.html')


@main_bp.route('/contacto')
def contacto():
    return render_template('contacto.html')


@main_bp.route('/favicon.ico')
def favicon():
    return ("", 204)


@main_bp.route('/dashboard')
@login_required
def dashboard():
    rol = session.get("rol")

    # Vendedor: punto de venta rápido
    if rol == "vendedor":
        return render_template("vendedor_dashboard.html")

    try:
        ahora_peru = datetime.now(PERU_TZ)
        hoy = ahora_peru.date()
        inicio_mes = hoy.replace(day=1)

        # Ventas de hoy
        ventas_hoy = db.session.query(
            func.coalesce(func.sum(Venta.cantidad * Producto.precio), 0),
            func.count(Venta.id)
        ).join(Producto, Venta.producto_id == Producto.id)\
         .filter(func.date(Venta.fecha_venta) == hoy).one()
        total_ventas_hoy = float(ventas_hoy[0] or 0)
        cantidad_ventas_hoy = ventas_hoy[1]

        # Ventas del mes
        ventas_mes = db.session.query(
            func.coalesce(func.sum(Venta.cantidad * Producto.precio), 0),
            func.count(Venta.id)
        ).join(Producto, Venta.producto_id == Producto.id)\
         .filter(func.date(Venta.fecha_venta) >= inicio_mes).one()
        total_ventas_mes = float(ventas_mes[0] or 0)
        cantidad_ventas_mes = ventas_mes[1]

        # Pedidos
        pedidos_pendientes = Pedido.query.filter_by(estado="pendiente").count()
        pedidos_en_proceso = Pedido.query.filter(
            Pedido.estado.in_(['confirmado', 'preparando', 'enviado', 'listo_tienda'])
        ).count()

        # Clientes
        total_clientes = Cliente.query.count()
        clientes_nuevos = Cliente.query.filter(
            Cliente.fecha_registro >= (ahora_peru - timedelta(days=7))
        ).count()

        # Top productos
        top_productos = db.session.query(
            Producto,
            func.coalesce(func.sum(Venta.cantidad), 0).label("total_vendido")
        ).outerjoin(Venta, Venta.producto_id == Producto.id)\
         .group_by(Producto.id)\
         .order_by(func.coalesce(func.sum(Venta.cantidad), 0).desc())\
         .limit(5).all()
        top_productos = [
            {"nombre": p.nombre, "imagen": p.imagen, "total_vendido": int(v or 0)}
            for p, v in top_productos
        ]

        # Stock
        stock_bajo = Producto.query.filter(Producto.cantidad > 0, Producto.cantidad <= 10).all()
        stock_critico = Producto.query.filter(Producto.cantidad == 0).all()

        # Ventas por día (últimos 7 días)
        desde = hoy - timedelta(days=6)
        ventas_dias = db.session.query(
            func.date(Venta.fecha_venta).label("dia"),
            func.coalesce(func.sum(Venta.cantidad * Producto.precio), 0).label("total")
        ).join(Producto, Venta.producto_id == Producto.id)\
         .filter(func.date(Venta.fecha_venta) >= desde)\
         .group_by(func.date(Venta.fecha_venta)).all()
        ventas_por_dia = {d.dia: float(d.total) for d in ventas_dias}
        dias = [desde + timedelta(days=i) for i in range(7)]
        dias_labels = [d.strftime("%d/%m") for d in dias]
        valores_ventas = [ventas_por_dia.get(d, 0.0) for d in dias]

        # Top por categoría
        totales_categoria = db.session.query(
            Categoria.nombre,
            func.coalesce(func.sum(Venta.cantidad * Producto.precio), 0).label("total")
        ).join(Producto, Producto.id_categoria == Categoria.id_categoria)\
         .join(Venta, Venta.producto_id == Producto.id)\
         .group_by(Categoria.nombre).all()

        # Pedidos por estado
        estados_pedidos = db.session.query(
            Pedido.estado, func.count(Pedido.id)
        ).group_by(Pedido.estado).all()

        # ---- Gráficos Plotly ----
        fig_ventas = go.Figure()
        fig_ventas.add_trace(go.Scatter(
            x=dias_labels, y=valores_ventas,
            mode="lines+markers", name="Ventas",
            line=dict(color="#1e3a8a", width=3),
            fill="tozeroy", fillcolor="rgba(30,58,138,0.08)"
        ))
        fig_ventas.update_layout(
            title="Ventas de los últimos 7 días",
            xaxis_title="Día", yaxis_title="S/",
            template="plotly_white", margin=dict(l=40, r=20, t=50, b=40), height=320
        )

        fig_top = go.Figure(go.Bar(
            x=[p["nombre"][:20] for p in top_productos] or ["Sin ventas"],
            y=[p["total_vendido"] for p in top_productos] or [0],
            marker_color="#3b82f6"
        ))
        fig_top.update_layout(
            title="Top productos vendidos",
            template="plotly_white", margin=dict(l=40, r=20, t=50, b=40), height=300
        )

        if totales_categoria:
            fig_cat = go.Figure(go.Pie(
                labels=[c.nombre for c in totales_categoria],
                values=[float(c.total) for c in totales_categoria], hole=0.4
            ))
        else:
            fig_cat = go.Figure(go.Pie(labels=["Sin ventas"], values=[1], hole=0.4))
        fig_cat.update_layout(title="Ventas por categoría", template="plotly_white",
                              margin=dict(l=20, r=20, t=50, b=20), height=300)

        if estados_pedidos:
            fig_estados = go.Figure(go.Pie(
                labels=[e[0] for e in estados_pedidos],
                values=[e[1] for e in estados_pedidos], hole=0.4
            ))
        else:
            fig_estados = go.Figure(go.Pie(labels=["Sin pedidos"], values=[1], hole=0.4))
        fig_estados.update_layout(title="Pedidos por estado", template="plotly_white",
                                  margin=dict(l=20, r=20, t=50, b=20), height=300)

        graph_ventas = fig_ventas.to_json()
        graph_top = fig_top.to_json()
        graph_cat = fig_cat.to_json()
        graph_estados = fig_estados.to_json()

        return render_template(
            "dashboard.html",
            ahora_peru=ahora_peru,
            total_ventas_hoy=total_ventas_hoy,
            cantidad_ventas_hoy=cantidad_ventas_hoy,
            total_ventas_mes=total_ventas_mes,
            cantidad_ventas_mes=cantidad_ventas_mes,
            pedidos_pendientes=pedidos_pendientes,
            pedidos_en_proceso=pedidos_en_proceso,
            total_clientes=total_clientes,
            clientes_nuevos=clientes_nuevos,
            top_productos=top_productos,
            stock_bajo=stock_bajo,
            stock_critico=stock_critico,
            graph_ventas=graph_ventas,
            graph_top=graph_top,
            graph_cat=graph_cat,
            graph_estados=graph_estados,
        )
    except Exception as e:
        print(f"❌ Error en dashboard: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error al cargar el dashboard: {e}", "danger")
        return render_template(
            "dashboard.html",
            ahora_peru=datetime.now(PERU_TZ),
            total_ventas_hoy=0, cantidad_ventas_hoy=0,
            total_ventas_mes=0, cantidad_ventas_mes=0,
            pedidos_pendientes=0, pedidos_en_proceso=0,
            total_clientes=0, clientes_nuevos=0,
            top_productos=[], stock_bajo=[], stock_critico=[],
            graph_ventas="{}", graph_top="{}", graph_cat="{}", graph_estados="{}",
        )
