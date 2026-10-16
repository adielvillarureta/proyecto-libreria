# app/ajustes_pago.py
"""Ajustes de los métodos de pago editables desde el panel.

Las llaves de las pasarelas no viven aquí: van en el .env. Esto solo guarda
lo que el personal cambia seguido (cuenta bancaria, QR de Yape, cargos).
"""
from datetime import datetime

from app import db
from app.models import AjustePago

DEFAULTS = {
    # Culqi
    "culqi_activo": {"valor": "1", "tipo": "bool", "descripcion": "Habilitar pasarela Culqi (tarjeta, Yape, PagoEfectivo)"},
    # PagoEfectivo por QR / CIP propio de Culqi
    "pago_efectivo_activo": {"valor": "1", "tipo": "bool", "descripcion": "Ofrecer PagoEfectivo con QR y código CIP"},
    # Yape / Plin con el QR de la librería
    "yape_activo": {"valor": "1", "tipo": "bool", "descripcion": "Ofrecer pago por Yape/Plin con nuestro QR"},
    "yape_titular": {"valor": "Librería Salesiana Huancayo", "tipo": "texto", "descripcion": "Titular de la cuenta Yape/Plin"},
    "yape_numero": {"valor": "", "tipo": "texto", "descripcion": "Número Yape/Plin que recibe el pago"},
    "yape_qr": {"valor": "", "tipo": "imagen", "descripcion": "Imagen del QR de Yape/Plin"},
    "yape_instruccion": {"valor": "Escanea el QR desde la app de Yape o Plin e ingresa el monto exacto.", "tipo": "texto", "descripcion": "Texto de ayuda para el cliente"},
    # Transferencia bancaria
    "transferencia_activo": {"valor": "1", "tipo": "bool", "descripcion": "Ofrecer transferencia bancaria"},
    "transferencia_banco": {"valor": "BCP", "tipo": "texto", "descripcion": "Banco de la cuenta de transferencia"},
    "transferencia_titular": {"valor": "Librería Salesiana Huancayo", "tipo": "texto", "descripcion": "Titular de la cuenta de transferencia"},
    "transferencia_cuenta": {"valor": "", "tipo": "texto", "descripcion": "Número de cuenta soles"},
    "transferencia_cci": {"valor": "", "tipo": "texto", "descripcion": "CCI interbancaria"},
    # Contraentrega
    "contraentrega_activo": {"valor": "1", "tipo": "bool", "descripcion": "Ofrecer pago contraentrega"},
    "contraentrega_cargo": {"valor": "3.00", "tipo": "numero", "descripcion": "Cargo adicional por contraentrega (S/.)"},
    # Mercado Pago
    "mercadopago_activo": {"valor": "0", "tipo": "bool", "descripcion": "Habilitar Mercado Pago"},
}


def _normalizar(clave, valor, tipo):
    if valor is None:
        valor = ""
    if tipo == "bool":
        return "1" if str(valor).strip().lower() in ("1", "true", "on", "si", "sí") else "0"
    if tipo == "numero":
        try:
            return str(round(float(str(valor).replace(",", ".")), 2))
        except (TypeError, ValueError):
            return DEFAULTS.get(clave, {}).get("valor", "0")
    return str(valor).strip()


def obtener(clave, default=None):
    """Valor de un ajuste. Si no existe todavía devuelve el del DEFAULTS."""
    fila = db.session.get(AjustePago, clave)
    if fila is not None and fila.valor is not None:
        return fila.valor
    if default is not None:
        return default
    return DEFAULTS.get(clave, {}).get("valor", "")


def obtener_bool(clave):
    return obtener(clave) == "1"


def obtener_numero(clave, default=0.0):
    try:
        return float(obtener(clave) or default)
    except (TypeError, ValueError):
        return float(default)


def guardar(clave, valor, tipo=None):
    fila = db.session.get(AjustePago, clave)
    if fila is None:
        fila = AjustePago(clave=clave)
        db.session.add(fila)
    fila.tipo = tipo or DEFAULTS.get(clave, {}).get("tipo", "texto")
    fila.valor = _normalizar(clave, valor, fila.tipo)
    fila.actualizado = datetime.now()
    return fila


def asegurar_defaults():
    """Crea las filas que falten. Se llama al arrancar la app."""
    for clave, meta in DEFAULTS.items():
        if db.session.get(AjustePago, clave) is None:
            fila = AjustePago(clave=clave)
            fila.valor = meta["valor"]
            fila.tipo = meta["tipo"]
            fila.descripcion = meta["descripcion"]
            db.session.add(fila)


def metodos_disponibles():
    """Qué métodos pintar en /pago, según lo configurado."""
    return {
        # Yape aparece siempre que esté el interruptor: sin QR ni número
        # la pantalla avisa que falta configurarlos, pero el cliente igual
        # puede crear el pedido y pagar por otra vía.
        "culqi": obtener_bool("culqi_activo"),
        "pago_efectivo": obtener_bool("pago_efectivo_activo"),
        "yape": obtener_bool("yape_activo"),
        "transferencia": obtener_bool("transferencia_activo") and bool(obtener("transferencia_cuenta") or obtener("transferencia_cci")),
        "contraentrega": obtener_bool("contraentrega_activo"),
        "mercadopago": obtener_bool("mercadopago_activo"),
    }