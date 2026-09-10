# app/routes/main.py
from flask import Blueprint, render_template, session, flash, jsonify
from app import db
from app.models import Venta, Pedido, Cliente, Producto
from app.utils import login_required
from datetime import datetime, timedelta
import plotly, json
import plotly.graph_objs as go
from sqlalchemy import func, text

main_bp = Blueprint('main', __name__)   # ← ESTA LÍNEA ES CLAVE