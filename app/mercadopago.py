# app/mercadopago.py
"""Mercado Pago: preferencias de pago y confirmación por webhook.

No usamos el SDK: son dos endpoints de la API REST y `requests` ya es
dependencia del proyecto.
"""

import hashlib
import hmac
import requests
from flask import current_app, request

TIMEOUT = 20
API = "https://api.mercadopago.com"


class MpError(Exception):
    def __init__(self, mensaje, status=502, payload=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.status = status
        self.payload = payload or {}


def _token():
    return current_app.config.get("MP_ACCESS_TOKEN", "")


def esta_configurado():
    return bool(_token())


def _headers():
    return {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _parse(respuesta):
    try:
        cuerpo = respuesta.json()
    except ValueError:
        raise MpError("Mercado Pago devolvió una respuesta ilegible", status=502)

    if respuesta.status_code >= 400:
        causa = (cuerpo.get("cause") or [{}])[0]
        raise MpError(
            causa.get("explanation") or cuerpo.get("message") or "Mercado Pago rechazó la operación",
            status=respuesta.status_code,
            payload=cuerpo,
        )
    return cuerpo


def crear_preferencia(monto, referencia, descripcion, payer, url_ok, url_fail, url_pending=None):
    """Devuelve la preferencia con su `init_point` (la URL a la que mandamos
    al cliente) y su `sandbox_init_point` cuando el token es de pruebas."""
    cuerpo = {
        "items": [{
            "title": descripcion[:120],
            "quantity": 1,
            "currency_id": "PEN",
            "unit_price": int(monto),
        }],
        "external_reference": str(referencia)[:120],
        "notification_url": url_pending,
        "back_urls": {
            "success": url_ok,
            "failure": url_fail,
            "pending": url_pending,
        },
        "auto_return": "approved",
        "statement_descriptor": "LIBRERIA SALESIANA",
    }

    if payer.get("email"):
        cuerpo["payer"] = {"email": payer["email"]}

    try:
        respuesta = requests.post(f"{API}/checkout/preferences", headers=_headers(), json=cuerpo, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise MpError(f"No se pudo conectar con Mercado Pago: {exc}", status=502)

    datos = _parse(respuesta)
    return {
        "id": datos.get("id"),
        "url": datos.get("sandbox_init_point") or datos.get("init_point"),
        "init_point": datos.get("init_point"),
    }


def consultar_pago(payment_id):
    try:
        respuesta = requests.get(f"{API}/v1/payments/{payment_id}", headers=_headers(), timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise MpError(f"No se pudo conectar con Mercado Pago: {exc}", status=502)
    return _parse(respuesta)


def firma_valida():
    """Valida el header `x-signature` del webhook.

    Mercado Pago manda: x-signature (ts=...,v1=...), x-request-id y x-id.
    La firma es HMAC-SHA256 de "id:{x-id};request-id:{x-request-id};ts:{ts}"
    con el secreto del webhook, y `v1` es el digest en hexadecimal.
    """
    secreto = current_app.config.get("MP_WEBHOOK_SECRET", "")
    if not secreto:
        # Sin secreto configurado no se puede verificar: preferimos rechazar.
        return False

    firma = request.headers.get("x-signature", "")
    if not firma.startswith("ts=") or "v1=" not in firma:
        return False

    partes = dict(parte.split("=", 1) for parte in firma.split(",") if "=" in parte)
    ts = partes.get("ts", "")
    esperado = partes.get("v1", "")

    id_ = request.headers.get("x-id", "")
    request_id = request.headers.get("x-request-id", "")

    base = f"id:{id_};request-id:{request_id};ts:{ts}"
    calculado = hmac.new(secreto.encode(), base.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(calculado, esperado)