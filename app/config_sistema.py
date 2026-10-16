# app/config_sistema.py
"""Configuración técnica editable desde el panel.

Precedencia: lo guardado en la base de datos manda sobre el .env. Si aquí no
hay nada para una clave, se usa la del archivo. Así el .env sigue siendo la
salida de emergencia y esta pantalla es la forma cómoda de cambiar las cosas.
"""
from datetime import datetime

from app import db
from app.models import ConfiguracionSistema, CambioConfiguracion

# clave -> (etiqueta, grupo, secreto)
CATALOGO = {
    # Base de datos
    "DB_HOST": ("Servidor MySQL", "base", False),
    "DB_USER": ("Usuario de la base", "base", False),
    "DB_PASSWORD": ("Contraseña de la base", "base", True),
    "DB_NAME": ("Nombre de la base", "base", False),
    "DATABASE_URL": ("URL de conexión completa", "base", True),

    # Correo
    "EMAIL_HOST": ("Servidor SMTP", "correo", False),
    "EMAIL_PORT": ("Puerto SMTP", "correo", False),
    "EMAIL_USER": ("Usuario de correo", "correo", False),
    "EMAIL_PASSWORD": ("Contraseña de correo", "correo", True),
    "EMAIL_FROM": ("Remitente", "correo", False),

    # Culqi
    "CULQI_PK": ("Llave pública de Culqi", "culqi", False),
    "CULQI_SK": ("Llave secreta de Culqi", "culqi", True),
    "CULQI_MODO": ("Modo de Culqi (test / live)", "culqi", False),

    # Mercado Pago
    "MP_ACCESS_TOKEN": ("Access Token de Mercado Pago", "mercadopago", True),
    "MP_WEBHOOK_SECRET": ("Secreto del webhook de Mercado Pago", "mercadopago", True),

    # API Perú
    "API_PERU_TOKEN": ("Token de API Perú (DNI/RUC)", "api_peru", True),

    # Seguridad
    "SECRET_KEY": ("Clave secreta de la sesión", "seguridad", True),
}

GRUPOS = [
    ("base", "Base de datos", "fas fa-database"),
    ("correo", "Correo de comprobantes", "fas fa-envelope"),
    ("culqi", "Pasarela Culqi", "fas fa-credit-card"),
    ("mercadopago", "Pasarela Mercado Pago", "fas fa-hand-holding-dollar"),
    ("api_peru", "API Perú (DNI y RUC)", "fas fa-id-card"),
    ("seguridad", "Seguridad", "fas fa-lock"),
]


def leer(clave, por_defecto=""):
    fila = db.session.get(ConfiguracionSistema, clave)
    if fila is not None and fila.tiene_valor:
        return fila.valor
    return por_defecto


def escribir(clave, valor, usuario_id=None, ip=None):
    """Guarda el valor y deja rastro de quién lo cambió."""
    if clave not in CATALOGO:
        raise KeyError(f"'{clave}' no es una clave de configuración válida")

    fila = db.session.get(ConfiguracionSistema, clave)
    if fila is None:
        fila = ConfiguracionSistema(clave=clave)
        db.session.add(fila)

    etiqueta, grupo, secreto = CATALOGO[clave]
    anterior = fila.valor

    fila.valor = "" if valor is None else str(valor)
    fila.grupo = grupo
    fila.secreto = secreto
    fila.descripcion = etiqueta
    fila.actualizado = datetime.now()
    fila.actualizado_por = usuario_id

    if anterior != fila.valor:
        db.session.add(CambioConfiguracion(
            clave=clave,
            valor_anterior=anterior,
            usuario_id=usuario_id,
            ip=ip,
        ))

    return fila


def enmascarar(valor):
    """Muestra solo los últimos 4 caracteres. Lo suficiente para reconocerlo,
    insuficiente para robarlo de una captura de pantalla."""
    if not valor:
        return ""
    texto = str(valor)
    if len(texto) <= 4:
        return "•" * len(texto)
    return "•" * 8 + texto[-4:]


def listar_para_panel():
    """Lo que se muestra en la pantalla: nunca el valor entero si es secreto."""
    salida = []
    for clave, (etiqueta, grupo, secreto) in CATALOGO.items():
        fila = db.session.get(ConfiguracionSistema, clave)
        valor = fila.valor if fila is not None and fila.tiene_valor else ""
        origen = "panel" if valor else ".env"
        if valor and secreto:
            valor = enmascarar(valor)

        salida.append({
            "clave": clave,
            "etiqueta": etiqueta,
            "grupo": grupo,
            "secreto": secreto,
            "valor": valor,
            "definido": bool(fila.tiene_valor) if fila is not None else False,
            "origen": origen,
            "actualizado": fila.actualizado.strftime("%d/%m/%Y %H:%M") if fila and fila.actualizado else None,
        })
    return salida


def aplicar_a_app(app):
    """Pasa lo guardado en la base al app.config, para que tenga efecto sin
    reiniciar.

    Lo del panel manda sobre el .env: es el propósito de la pantalla. Si la
    clave no está guardada, el valor que ya traía el .env se queda.
    """
    aplicados = []
    with app.app_context():
        try:
            filas = ConfiguracionSistema.query.all()
        except Exception as e:
            print(f"⚠️ No se pudo leer la configuración guardada: {e}")
            return aplicados

        for fila in filas:
            if not fila.tiene_valor or fila.clave not in CATALOGO:
                continue
            app.config[fila.clave] = fila.valor
            aplicados.append(fila.clave)

        if aplicados:
            print(f"Configuración del panel aplicada: {', '.join(aplicados)}")

    return aplicados


def requiere_reinicio(cambios):
    """Avisa de qué cambios no surtan efecto hasta reiniciar."""
    reinicio = []
    for clave in cambios:
        if clave in ("SECRET_KEY", "DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME", "DATABASE_URL"):
            reinicio.append(clave)
    return reinicio