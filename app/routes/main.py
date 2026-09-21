# app/routes/main.py
from flask import Blueprint, render_template, session, flash, jsonify
from app import db
from app.models import Venta, Pedido, Cliente, Producto
from app.utils import login_required
from datetime import datetime, timedelta
from sqlalchemy import func, text

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def inicio():
    return render_template('index.html')

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
    import pandas as pd
    import plotly
    import plotly.graph_objs as go
    import json
    
    hoy = datetime.now().date()
    inicio_mes = datetime.now().replace(day=1).date()
    hace_30_dias = datetime.now() - timedelta(days=30)
    
    # ========== HORA PER├Ü ==========
    ahora_peru = datetime.now() - timedelta(hours=5)
    
    # ========== 1. ESTAD├ìSTICAS ==========
    ventas_hoy = Venta.query.filter(func.date(Venta.fecha_venta) == hoy).all()
    total_ventas_hoy = sum(v.cantidad * v.producto.precio for v in ventas_hoy) if ventas_hoy else 0
    cantidad_ventas_hoy = len(ventas_hoy) if ventas_hoy else 0
    
    ventas_mes = Venta.query.filter(func.date(Venta.fecha_venta) >= inicio_mes).all()
    total_ventas_mes = sum(v.cantidad * v.producto.precio for v in ventas_mes) if ventas_mes else 0
    cantidad_ventas_mes = len(ventas_mes) if ventas_mes else 0
    
    pedidos_pendientes = Pedido.query.filter(Pedido.estado == 'pendiente').count()
    pedidos_en_proceso = Pedido.query.filter(Pedido.estado.in_(['confirmado', 'preparando', 'enviado'])).count()
    
    total_clientes = Cliente.query.count()
    hace_7_dias = datetime.now() - timedelta(days=7)
    clientes_nuevos = Cliente.query.filter(Cliente.fecha_registro >= hace_7_dias).count()
    
    # Ventas por d├¡a
    ventas_por_dia = []
    for i in range(6, -1, -1):
        fecha = datetime.now() - timedelta(days=i)
        fecha_str = fecha.strftime('%d/%m')
        resultado = db.session.execute(
            text("""
                SELECT COALESCE(SUM(v.cantidad * p.precio), 0) as total
                FROM ventas v
                JOIN productos p ON v.producto_id = p.id
                WHERE DATE(v.fecha_venta) = :fecha
            """),
            {"fecha": fecha.date()}
        ).fetchone()
        total_dia = float(resultado[0]) if resultado and resultado[0] else 0
        ventas_por_dia.append({'fecha': fecha_str, 'total': total_dia})
    

    top_productos = db.session.query(
        Producto.nombre,
        func.sum(Venta.cantidad).label('total_vendido')
    ).join(Venta).filter(
        func.date(Venta.fecha_venta) >= hace_30_dias.date()
    ).group_by(Producto.id).order_by(func.sum(Venta.cantidad).desc()).limit(5).all()
    

    stock_bajo = Producto.query.filter(Producto.cantidad <= 10, Producto.cantidad > 0).order_by(Producto.cantidad.asc()).limit(10).all()
    stock_critico = Producto.query.filter(Producto.cantidad == 0).order_by(Producto.nombre.asc()).limit(10).all()

    fechas_7d = [datetime.now() - timedelta(days=i) for i in range(6, -1, -1)]
    ventas_7d = []
    for fecha in fechas_7d:
        resultado = db.session.execute(
            text("""
                SELECT COALESCE(SUM(v.cantidad * p.precio), 0) as total
                FROM ventas v
                JOIN productos p ON v.producto_id = p.id
                WHERE DATE(v.fecha_venta) = :fecha
            """),
            {"fecha": fecha.date()}
        ).fetchone()
        ventas_7d.append(float(resultado[0]) if resultado else 0)
    
    fig_ventas = go.Figure()
    fig_ventas.add_trace(go.Bar(
        x=[fecha.strftime('%d/%m') for fecha in fechas_7d],
        y=ventas_7d,
        name='Ventas (S/)',
        marker_color='#2563eb',
        text=[f'S/. {v:.2f}' for v in ventas_7d],
        textposition='outside'
    ))
    fig_ventas.update_layout(
        title='­ƒôê Ventas ├Ültimos 7 D├¡as',
        xaxis_title='Fecha',
        yaxis_title='Total S/.',
        template='plotly_white',
        height=350,
        showlegend=False
    )
    

    fig_top = go.Figure()
    if top_productos:
        nombres = [p[0] for p in top_productos]   
        vendidos = [float(p[1]) for p in top_productos] 
        fig_top.add_trace(go.Bar(
            x=nombres,
            y=vendidos,
            name='Unidades',
            marker_color='#10b981',
            text=vendidos,
            textposition='outside'
        ))
    fig_top.update_layout(
        title='­ƒÅå Top 5 Productos M├ís Vendidos',
        xaxis_title='Producto',
        yaxis_title='Unidades Vendidas',
        template='plotly_white',
        height=350,
        showlegend=False
    )

    ventas_categoria = db.session.execute(
        text("""
            SELECT c.nombre as categoria,
                   COALESCE(SUM(v.cantidad * p.precio), 0) as total_ventas
            FROM ventas v
            JOIN productos p ON v.producto_id = p.id
            LEFT JOIN categorias c ON p.id_categoria = c.id_categoria
            WHERE v.fecha_venta >= :fecha_inicio
            GROUP BY c.nombre
            ORDER BY total_ventas DESC
        """),
        {"fecha_inicio": hace_30_dias.date()}
    ).fetchall()
    
    fig_cat = go.Figure()
    if ventas_categoria:
        categorias = [row[0] or 'Sin categor├¡a' for row in ventas_categoria]
        totales = [float(row[1]) for row in ventas_categoria]
        fig_cat.add_trace(go.Pie(
            labels=categorias,
            values=totales,
            hole=0.4,
            marker=dict(colors=['#2563eb', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899'])
        ))
    fig_cat.update_layout(
        title='­ƒôè Ventas por Categor├¡a',
        template='plotly_white',
        height=350,
        showlegend=True
    )
    

    estados_pedidos = db.session.execute(
        text("""
            SELECT estado, COUNT(*) as cantidad
            FROM pedidos
            GROUP BY estado
        """)
    ).fetchall()
    
    fig_estados = go.Figure()
    if estados_pedidos:
        estados = [row[0] for row in estados_pedidos]
        cantidades = [row[1] for row in estados_pedidos]
        colores = {'pendiente': '#f59e0b', 'confirmado': '#3b82f6', 
                   'preparando': '#8b5cf6', 'enviado': '#06b6d4',
                   'entregado': '#10b981', 'cancelado': '#ef4444'}
        colors = [colores.get(e, '#6b7280') for e in estados]
        fig_estados.add_trace(go.Bar(
            x=estados,
            y=cantidades,
            marker_color=colors,
            text=cantidades,
            textposition='outside'
        ))
    fig_estados.update_layout(
        title='­ƒôï Estado de Pedidos',
        xaxis_title='Estado',
        yaxis_title='Cantidad',
        template='plotly_white',
        height=350,
        showlegend=False
    )
    

    graph_ventas = json.dumps(fig_ventas, cls=plotly.utils.PlotlyJSONEncoder)
    graph_top = json.dumps(fig_top, cls=plotly.utils.PlotlyJSONEncoder)
    graph_cat = json.dumps(fig_cat, cls=plotly.utils.PlotlyJSONEncoder)
    graph_estados = json.dumps(fig_estados, cls=plotly.utils.PlotlyJSONEncoder)
    

    return render_template("dashboard.html",
                          total_ventas_hoy=total_ventas_hoy,
                          cantidad_ventas_hoy=cantidad_ventas_hoy,
                          total_ventas_mes=total_ventas_mes,
                          cantidad_ventas_mes=cantidad_ventas_mes,
                          pedidos_pendientes=pedidos_pendientes,
                          pedidos_en_proceso=pedidos_en_proceso,
                          total_clientes=total_clientes,
                          clientes_nuevos=clientes_nuevos,
                          ventas_por_dia=ventas_por_dia,
                          top_productos=top_productos,
                          stock_bajo=stock_bajo,
                          stock_critico=stock_critico,
                          graph_ventas=graph_ventas,
                          graph_top=graph_top,
                          graph_cat=graph_cat,
                          graph_estados=graph_estados,
                          datetime=datetime,
                          timedelta=timedelta,
                          ahora_peru=ahora_peru) 

