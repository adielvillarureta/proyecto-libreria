# models.py
from datetime import datetime
from . import db

class Bloqueo(db.Model):
    __tablename__ = "bloqueos"
    id = db.Column(db.Integer, primary_key=True)
    tipo_usuario = db.Column(db.Enum('sistema', 'cliente'), nullable=False)
    usuario_sistema_id = db.Column(db.Integer, db.ForeignKey("usuarios_sistema.id"), nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=True)
    motivo = db.Column(db.String(255), nullable=True)
    bloqueado_por = db.Column(db.Integer, db.ForeignKey("usuarios_sistema.id"), nullable=True)
    fecha_bloqueo = db.Column(db.DateTime, default=datetime.now)
    fecha_desbloqueo = db.Column(db.DateTime, nullable=True)
    desbloqueado_por = db.Column(db.Integer, db.ForeignKey("usuarios_sistema.id"), nullable=True)
    estado = db.Column(db.Boolean, default=True)
    permanente = db.Column(db.Boolean, default=False)
    minutos_bloqueo = db.Column(db.Integer, nullable=True)

class IntentosLogin(db.Model):
    __tablename__ = "intentos_login"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150))
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=True)  # ← NUEVO
    usuario_sistema_id = db.Column(db.Integer, db.ForeignKey("usuarios_sistema.id"), nullable=True)  # ← NUEVO
    ip = db.Column(db.String(45))
    intentos = db.Column(db.Integer, default=1)
    ultimo_intento = db.Column(db.DateTime, default=datetime.now)
    usuarios_distintos = db.Column(db.Integer, default=0)
    ips_bloqueadas = db.Column(db.DateTime, nullable=True)  
    email_bloqueado = db.Column(db.DateTime, nullable=True)
    intentos_totales = db.Column(db.Integer, default=0) 

class Proveedor(db.Model):
    __tablename__ = "proveedores"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    contacto = db.Column(db.String(20), nullable=False)
    ruc_empresa_id = db.Column(db.Integer, db.ForeignKey("ruc_empresas.id"), nullable=True)
    estado = db.Column(db.Integer, default=1)
    productos = db.relationship("Producto", back_populates="proveedor")

class Producto(db.Model):
    __tablename__ = "productos"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    cantidad = db.Column(db.Integer, default=0)
    proveedor_id = db.Column(db.Integer, db.ForeignKey("proveedores.id"), nullable=True)
    precio = db.Column(db.Numeric(10,2), default=0.0)
    imagen = db.Column(db.String(255))
    destacado = db.Column(db.Integer, default=0)
    precio_oferta = db.Column(db.Numeric(10,2), nullable=True) 
    codigo_barras = db.Column(db.String(50), nullable=True)
    id_categoria = db.Column(db.Integer, db.ForeignKey("categorias.id_categoria"), nullable=True)
    
    ventas = db.relationship("Venta", back_populates="producto")
    proveedor = db.relationship("Proveedor", back_populates="productos")
    categoria_rel = db.relationship("Categoria", back_populates="productos")  

class UsuarioSistema(db.Model):
    __tablename__ = "usuarios_sistema"
    id = db.Column(db.Integer, primary_key=True)
    correo = db.Column(db.String(150), unique=True, nullable=False)
    nombres = db.Column(db.String(100), nullable=False)
    apellidos = db.Column(db.String(100), nullable=False)
    clave = db.Column(db.String(255), nullable=False)
    estado = db.Column(db.Integer, default=1)
    rol_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    rol = db.Column(db.String(20), nullable=False)  
    ventas = db.relationship("Venta", back_populates="vendedor")

class Categoria(db.Model):
    __tablename__ = "categorias"
    id_categoria = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True)
    
    productos = db.relationship("Producto", back_populates="categoria_rel") 

class Venta(db.Model):
    __tablename__ = "ventas"
    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)
    vendedor_id = db.Column(db.Integer, db.ForeignKey("usuarios_sistema.id"), nullable=False)
    fecha_venta = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    cantidad = db.Column(db.Integer, default=1)
    tipo_comprobante = db.Column(db.String(20), default="boleta")
    numero_comprobante = db.Column(db.String(50), nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=True)
    estado = db.Column(db.Integer, default=1)
    
    cliente_nombres = db.Column(db.String(100), nullable=True)
    cliente_apellidos = db.Column(db.String(100), nullable=True)
    cliente_documento = db.Column(db.String(20), nullable=True)
    cliente_email = db.Column(db.String(150), nullable=True)
    cliente_direccion = db.Column(db.Text, nullable=True)
    cliente_direccion_fiscal = db.Column(db.Text, nullable=True)
    cliente_razon_social = db.Column(db.String(200), nullable=True)
    
    producto = db.relationship("Producto", back_populates="ventas")
    vendedor = db.relationship("UsuarioSistema", back_populates="ventas")
    cliente = db.relationship("Cliente", back_populates="ventas")
    
    @property
    def cliente_nombre_completo(self):
        if self.cliente_nombres and self.cliente_apellidos:
            return f"{self.cliente_nombres} {self.cliente_apellidos}"
        return self.cliente_nombres or ""
class Cliente(db.Model):
    __tablename__ = "clientes"
    id = db.Column(db.Integer, primary_key=True)
    dni = db.Column(db.String(8))
    nombres = db.Column(db.String(100), nullable=False)
    apellidos = db.Column(db.String(100), nullable=False)
    correo = db.Column(db.String(150), unique=True, nullable=False)     
    telefono = db.Column(db.String(15))
    direccion = db.Column(db.Text)
    clave = db.Column(db.String(255), nullable=False)
    fecha_registro = db.Column(db.DateTime, default=datetime.now)
    puntos = db.Column(db.Integer, default=0)
    token_recuperacion = db.Column(db.String(100), nullable=True)
    token_expiracion = db.Column(db.DateTime, nullable=True)
    estado = db.Column(db.Integer, default=1)  
    pedidos = db.relationship("Pedido", back_populates="cliente")
    ventas = db.relationship("Venta", back_populates="cliente")
class Rol(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    estado = db.Column(db.Integer, default=1)
class Pedido(db.Model):
    __tablename__ = "pedidos"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))
    fecha_pedido = db.Column(db.DateTime, default=datetime.now)
    estado = db.Column(db.String(20), default="pendiente")
    total = db.Column(db.Float)
    direccion_entrega = db.Column(db.Text)
    tipo_entrega = db.Column(db.String(20), default="recojo")
    nota = db.Column(db.Text)
    cliente = db.relationship("Cliente", back_populates="pedidos")
    detalles = db.relationship("DetallePedido", back_populates="pedido")

class DetallePedido(db.Model):
    __tablename__ = "detalle_pedido"
    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"))
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"))
    cantidad = db.Column(db.Integer)
    precio_unitario = db.Column(db.Float)
    subtotal = db.Column(db.Float)
    pedido = db.relationship("Pedido", back_populates="detalles")
    producto = db.relationship("Producto")

class RucEmpresa(db.Model):
    __tablename__ = "ruc_empresas"
    id = db.Column(db.Integer, primary_key=True)
    ruc = db.Column(db.String(11), unique=True, nullable=False)
    razon_social = db.Column(db.String(200), nullable=False)
    direccion = db.Column(db.Text, nullable=True)