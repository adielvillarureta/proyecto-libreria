# app/esquema.py
"""Sincroniza columnas nuevas sin usar Alembic.

El proyecto no tiene carpeta de migraciones y `db.create_all()` solo crea
tablas nuevas: si después agregas una columna al modelo, en la base existente
no aparece y la app revienta con "Unknown column". Esto compara el modelo
contra la base y agrega lo que falte.

Solo toca la tabla de pagos, que es la que se ha venido ampliando. Para
cambios en el resto del esquema sigue haciendo falta una migración de verdad.
"""
from sqlalchemy import inspect, text

from app import db

# tabla -> [(columna, tipo SQL)]
COLUMNAS = {
    "pagos": [
        ("orden_id", "VARCHAR(60)"),
        ("cargo_id", "VARCHAR(60)"),
        ("token_id", "VARCHAR(60)"),
        ("metodo", "VARCHAR(30)"),
        ("monto", "INTEGER"),
        ("estado", "VARCHAR(20)"),
        ("codigo_pago", "VARCHAR(30)"),
        ("respuesta", "TEXT"),
        ("datos", "TEXT"),
        ("comprobante", "VARCHAR(255)"),
        ("codigo_error", "VARCHAR(120)"),
        ("mensaje_error", "VARCHAR(255)"),
        ("fecha_pago", "DATETIME"),
    ],
}


def sincronizar_columnas():
    """Agrega las columnas que falten. Es idempotente: se puede llamar siempre."""
    inspector = inspect(db.engine)
    tablas = set(inspector.get_table_names())
    agregadas = []

    for tabla, columnas in COLUMNAS.items():
        if tabla not in tablas:
            continue  # esa tabla la crea db.create_all()

        actuales = {c["name"] for c in inspector.get_columns(tabla)}

        for nombre, tipo in columnas:
            if nombre in actuales:
                continue
            # El dialecto pone las comillas que correspondan (backticks en
            # MySQL, comillas dobles en SQLite).
            t = db.engine.dialect.identifier_preparer.quote(tabla)
            c = db.engine.dialect.identifier_preparer.quote(nombre)
            db.session.execute(text(f"ALTER TABLE {t} ADD COLUMN {c} {tipo}"))
            db.session.commit()
            agregadas.append(f"{tabla}.{nombre}")
            print(f"Columna agregada: {tabla}.{nombre} {tipo}")

    return agregadas