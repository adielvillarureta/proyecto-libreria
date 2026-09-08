from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from .. import db, bcrypt
from ..models import UsuarioSistema, Cliente, IntentosLogin, Bloqueo
from ..utils import (verificar_bloqueo_ip, verificar_bloqueo_email, 
                     registrar_intento_fallido, limpiar_intentos_exitosos,
                     limpiar_bloqueos_expirados, obtener_ip_cliente, login_required)