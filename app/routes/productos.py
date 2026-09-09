# app/routes/productos.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app import db, proveedores
from app.models import Producto, Proveedor, Categoria
from app.utils import login_required, admin_required, requerir_permisos_escritura, allowed_file
import os, time
from werkzeug.utils import secure_filename

productos_bp = Blueprint('productos', __name__)

@productos_bp.route('/')
@login_required
def listar_productos():
        categoria_id = request.args.get("categoria", type=int)
        destacado = request.args.get("destacado")
        
        query = Producto.query
        
        if categoria_id:
            query = query.filter_by(id_categoria=categoria_id)
        if destacado:
            query = query.filter_by(destacado=1)
        
        productos_lista = query.order_by(Producto.destacado.desc(), Producto.nombre.asc()).all()
        
        categorias = Categoria.query.filter_by(activo=True).all()
        
        return render_template("productos.html", 
                            productos=productos_lista,
                            categorias=categorias,
                            categoria_seleccionada=categoria_id)


@productos_bp.route('/nuevo', methods=['GET'])
@login_required
@requerir_permisos_escritura
def nuevo_producto():
   proveedores = Proveedor.query.all()
   categorias = Categoria.query.filter_by(activo=True).all()  # ← Obtener categorías activas
   return render_template("producto_form.html", 
                             proveedores=proveedores,
                             categorias=categorias)

@productos_bp.route('/guardar', methods=['POST'])
@login_required
@requerir_permisos_escritura
def guardar_producto():
    try:
        precio_oferta = request.form.get("precio_oferta")
        precio_oferta = float(precio_oferta) if precio_oferta and precio_oferta.strip() else None
        
        destacado = 1 if request.form.get("destacado") else 0
        
        id_categoria = request.form.get("id_categoria")
        id_categoria = int(id_categoria) if id_categoria and id_categoria.strip() else None
        
        nuevo = Producto(
            nombre=request.form["nombre"],
            descripcion=request.form["descripcion"],
            cantidad=int(request.form["cantidad"]),
            proveedor_id=request.form.get("proveedor") or None,
            precio=float(request.form["precio"]),
            id_categoria=id_categoria,  
            precio_oferta=precio_oferta,
            destacado=destacado,
            codigo_barras=request.form.get("codigo_barras") or None,
        )
        db.session.add(nuevo)
        db.session.flush()
        
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        if "imagen" in request.files:
            file = request.files["imagen"]
            if file and file.filename and allowed_file(file.filename):
                filename = f"{nuevo.id}_{int(time.time())}_{secure_filename(file.filename)}"
                filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(filepath)
                nuevo.imagen = filename
        
        db.session.commit()
        flash("✅ Producto creado exitosamente", "success")
        return redirect(url_for("productos"))
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al guardar: {str(e)}", "danger")
        return redirect(url_for("nuevo_producto"))

@productos_bp.route('/editar/<int:id>')
@login_required
@requerir_permisos_escritura
def editar_producto(id):
    producto = db.session.get(Producto, id)
    if not producto:
        flash("❌ Producto no encontrado", "error")
        return redirect(url_for("productos"))
    
    proveedores = Proveedor.query.all()
    categorias = Categoria.query.filter_by(activo=True).all()  # ← Obtener categorías activas
    
    return render_template("producto_form.html", 
                          producto=producto, 
                          proveedores=proveedores,
                          categorias=categorias)

@productos_bp.route('/actualizar/<int:id>', methods=['POST'])
@login_required
@requerir_permisos_escritura
def actualizar_producto(id):
    producto_obj = db.session.get(Producto, id)
    if not producto_obj:
        flash("❌ Producto no encontrado", "error")
        return redirect(url_for("productos"))
    
    try:
        precio_oferta = request.form.get("precio_oferta")
        precio_oferta = float(precio_oferta) if precio_oferta and precio_oferta.strip() else None
        
        id_categoria = request.form.get("id_categoria")
        id_categoria = int(id_categoria) if id_categoria and id_categoria.strip() else None
        
        producto_obj.nombre = request.form["nombre"]
        producto_obj.descripcion = request.form["descripcion"]
        producto_obj.cantidad = int(request.form["cantidad"])
        producto_obj.proveedor_id = request.form.get("proveedor") or None
        producto_obj.precio = float(request.form["precio"])
        producto_obj.id_categoria = id_categoria  # ← USAR id_categoria
        producto_obj.precio_oferta = precio_oferta
        producto_obj.destacado = 1 if request.form.get("destacado") else 0
        producto_obj.codigo_barras = request.form.get("codigo_barras") or None
        
        file = request.files.get("imagen")
        if file and file.filename and allowed_file(file.filename):
            if producto_obj.imagen:
                old_path = os.path.join(app.config["UPLOAD_FOLDER"], producto_obj.imagen)
                if os.path.exists(old_path):
                    os.remove(old_path)
            filename = f"{id}_{int(time.time())}_{secure_filename(file.filename)}"
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            producto_obj.imagen = filename
        
        db.session.commit()
        flash("✅ Producto actualizado exitosamente", "success")
        return redirect(url_for("productos"))
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al actualizar: {str(e)}", "danger")
        return redirect(url_for("editar_producto", id=id))

@productos_bp.route('/eliminar/<int:id>')
@login_required
@requerir_permisos_escritura
def eliminar_producto(id):
    producto_obj = db.session.get(Producto, id)
    if not producto_obj:
        flash("❌ Producto no encontrado", "error")
        return redirect(url_for("productos"))
    
    try:
        if producto_obj.imagen:
            img_path = os.path.join(app.config["UPLOAD_FOLDER"], producto_obj.imagen)
            if os.path.exists(img_path):
                os.remove(img_path)
        
        db.session.delete(producto_obj)
        db.session.commit()
        flash("✅ Producto eliminado exitosamente", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error al eliminar: {str(e)}", "danger")
    
    return redirect(url_for("productos"))

@productos_bp.route('/preview/<int:producto_id>')
@login_required
def producto_preview(producto_id):
    producto = db.session.get(Producto, producto_id)
    if not producto:
        return {"error": "Producto no encontrado"}, 404
    
    imagen_url = None
    if producto.imagen:
        imagen_url = url_for("static", filename=f"img/productos/{producto.imagen}")
    
    return {
        "id": producto.id,
        "nombre": producto.nombre,
        "descripcion": producto.descripcion[:60] + "..." if len(producto.descripcion or "") > 60 else (producto.descripcion or ""),
        "precio": float(producto.precio or 0),
        "cantidad": producto.cantidad,
        "categoria": producto.categoria_rel.nombre if producto.categoria_rel else None,  # ← AGREGAR
        "imagen_url": imagen_url,
    }

# Proveedores
@productos_bp.route('/proveedores')
@login_required
def proveedores():
    proveedoreslocal = Proveedor.query.all()
    return render_template("proveedores.html")

@productos_bp.route('/proveedores/nuevo')
@login_required
@requerir_permisos_escritura
def nuevo_proveedor():
    return render_template("proveedor_form.html")

@productos_bp.route('/proveedores/guardar', methods=['POST'])
@login_required
@requerir_permisos_escritura
def guardar_proveedor():
    nuevo = Proveedor(
        nombre=request.form["nombre"],
        email=request.form["email"],
        contacto=request.form["contacto"],
    )
    db.session.add(nuevo)
    db.session.commit()
    flash("✅ Proveedor registrado", "success")
    return redirect(url_for("proveedores"))

@productos_bp.route('/proveedores/editar/<int:id>')
@login_required
@requerir_permisos_escritura
def editar_proveedor(id):
    proveedor = db.session.get(Proveedor, id)
    if not proveedor:
        flash("❌ Proveedor no encontrado", "error")
        return redirect(url_for("proveedores"))
    return render_template("proveedor_form.html", proveedor=proveedor)

@productos_bp.route("/proveedores/actualizar/<int:id>", methods=["POST"])
@login_required
@requerir_permisos_escritura
def actualizar_proveedor(id):
    proveedor = db.session.get(Proveedor, id)
    if not proveedor:
        flash("❌ Proveedor no encontrado", "error")
        return redirect(url_for("proveedores"))
    proveedor.nombre = request.form["nombre"]
    proveedor.email = request.form["email"]
    proveedor.contacto = request.form["contacto"]
    db.session.commit()
    flash("✅ Proveedor actualizado", "success")
    return redirect(url_for("proveedores"))

@productos_bp.route("/proveedores/eliminar/<int:id>")
@login_required
@requerir_permisos_escritura
def eliminar_proveedor(id):
    proveedor = db.session.get(Proveedor, id)
    if not proveedor:
        flash("❌ Proveedor no encontrado", "error")
        return redirect(url_for("proveedores"))
    db.session.delete(proveedor)
    db.session.commit()
    flash("✅ Proveedor eliminado", "success")
    return redirect(url_for("proveedores"))
