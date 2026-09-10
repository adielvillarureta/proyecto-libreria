# app/routes/main.py
from flask import Blueprint, render_template, session, flash, jsonify
from app import db
from app.models import Venta, Pedido, Cliente, Producto
from app.utils import login_required
from datetime import datetime, timedelta
import plotly, json
import plotly.graph_objs as go
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


@main_bp.route('/')
def inicio():
    return render_template('index.html')
