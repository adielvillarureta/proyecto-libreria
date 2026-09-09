# app/routes/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from app import db, bcrypt
from app.models import UsuarioSistema
from app.utils import (
    login_required, admin_required, obtener_ip_cliente,
    registrar_intento_fallido, verificar_bloqueo_ip, verificar_bloqueo_email,
    limpiar_bloqueos_expirados, limpiar_intentos_exitosos
)

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Todo el código de login del sistema (usuarios_sistema)
    # que estaba en el monolítico
    # ...
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    session.clear()
    flash("✅ Sesión cerrada", "success")
    return redirect(url_for('auth.login'))

@auth_bp.route('/usuarios/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo_usuario():
    # ...
    pass

@auth_bp.route('/usuario/bloquear/<int:usuario_id>', methods=['POST'])
@login_required
def bloquear_usuario_sistema(usuario_id):
    # ...
    pass

@auth_bp.route('/usuario/desbloquear/<int:usuario_id>', methods=['POST'])
@login_required
def desbloquear_usuario_sistema(usuario_id):
    # ...
    pass

@auth_bp.route('/cambiar_clave', methods=['GET', 'POST'])
@login_required
def cambiar_clave():
    # ...
    pass

@auth_bp.route('/usuarios-sistema')
@login_required
def usuarios_sistema():
    # ...
    pass