# app/culqi.py
"""Cliente mínimo de la API de Culqi (órdenes y cargos).

No usamos el SDK oficial: son tres endpoints y `requests` ya es dependencia
del proyecto. Toda llamada usa la llave secreta (CULQI_SK) y nunca expone
datos de tarjeta: la tarjeta se tokeniza en el navegador con el checkout de
Culqi y aquí solo llega el token.
"""

import requests
from flask import current_app

TIMEOUT = 20


class CulqiError(Exception):
    def __init__(self, mensaje, codigo=None, status=502, payload=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo
        self.status = status
        self.payload = payload or {}


def esta_configurado():
    return bool(current_app.config.get("CULQI_PK")) and bool(current_app.config.get("CULQI_SK"))


def llave_publica():
    return current_app.config.get("CULQI_PK", "")


def _base():
    return current_app.config.get("CULQI_API_URL", "https://api.culqi.com").rstrip("/")


def _headers():
    return {
        "Authorization": f"Bearer {current_app.config.get('CULQI_SK', '')}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _parse(respuesta):
    try:
        cuerpo = respuesta.json()
    except ValueError:
        raise CulqiError("Culqi devolvió una respuesta ilegible", status=502)

    if respuesta.status_code >= 400:
        mensaje = (
            cuerpo.get("user_message")
            or cuerpo.get("message")
            or "Culqi rechazó la operación"
        )
        raise CulqiError(
            mensaje,
            codigo=cuerpo.get("code") or cuerpo.get("error_code"),
            status=respuesta.status_code,
            payload=cuerpo,
        )
    return cuerpo


def _post(ruta, cuerpo):
    try:
        respuesta = requests.post(f"{_base()}{ruta}", headers=_headers(), json=cuerpo, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise CulqiError(f"No se pudo conectar con Culqi: {exc}", status=502)
    return _parse(respuesta)


def _get(ruta):
    try:
        respuesta = requests.get(f"{_base()}{ruta}", headers=_headers(), timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise CulqiError(f"No se pudo conectar con Culqi: {exc}", status=502)
    return _parse(respuesta)


def crear_orden(monto, order_number, descripcion, cliente, expiracion_segundos=1800, metadata=None):
    """Crea una orden de Culqi.

    Sin orden, el checkout de Culqi solo habilita tarjeta. Con `order` en los
    ajustes del checkout se habilitan PagoEfectivo, billeteras móviles (Yape,
    Plin) y Cuotéalo.

    Devuelve el objeto order de Culqi, con `id`, `payment_code` y `actions`.
    """
    cuerpo = {
        "amount": int(monto),
        "currency_code": "PEN",
        "description": descripcion[:250],
        "order_number": str(order_number)[:100],
        "client_details": {
            "first_name": (cliente.get("nombres") or "")[:50],
            "last_name": (cliente.get("apellidos") or "")[:50],
            "email": (cliente.get("email") or "")[:100],
            "phone_number": (cliente.get("telefono") or "")[:20],
        },
        "confirm": True,
        "actions": ["QUERY_QR", "CODE"],
    }

    if expiracion_segundos:
        import time
        cuerpo["expiration_date"] = int(time.time()) + int(expiracion_segundos)

    if metadata:
        cuerpo["metadata"] = metadata

    cuerpo["client_details"] = {k: v for k, v in cuerpo["client_details"].items() if v}
    return _post("/v2/orders", cuerpo)


def consultar_orden(orden_id):
    return _get(f"/v2/orders/{orden_id}")


def cobrar(token_id, monto, order_id=None, descripcion="", installments="1", metadata=None):
    """Cobra un token de tarjeta (o de Yape) generado por el checkout."""
    cuerpo = {
        "token_id": token_id,
        "amount": int(monto),
        "currency_code": "PEN",
        "capture": True,
        "installments": str(installments or "1"),
        "description": descripcion[:250],
    }
    if order_id:
        cuerpo["order_id"] = order_id
    if metadata:
        cuerpo["metadata"] = metadata
    return _post("/v2/charges", cuerpo)


def consultar_cargo(cargo_id):
    return _get(f"/v2/charges/{cargo_id}")


def reembolsar(cargo_id, monto=None):
    cuerpo = {}
    if monto:
        cuerpo["amount"] = int(monto)
    return _post(f"/v2/charges/{cargo_id}/refunds", cuerpo)