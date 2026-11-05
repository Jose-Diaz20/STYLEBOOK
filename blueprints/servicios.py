"""RF-05 Gestión de servicios (crear, editar, activar/desactivar los propios)
RF-06 Consultar servicios (catálogo público)"""
from flask import Blueprint, abort, render_template, request, redirect, url_for, flash

from supabase_client import sb
from utilidades import exigir_proveedor, cliente_sesion, primero, proveedor_propio, mensaje_error

# INICIO AGREGADO JESUS: cliente Storage autenticado.
from supabase_client import storage_como_usuario
# FIN AGREGADO JESUS: cliente Storage autenticado.
##Jesus
from flask import Blueprint, abort, render_template, request, redirect, url_for, flash, session
# INICIO AGREGADO: herramientas para cargar imágenes de servicios.
from werkzeug.utils import secure_filename
import uuid
from flask import session
# FIN AGREGADO JESUS: herramientas para cargar imágenes de servicios.

servicios_bp = Blueprint("servicios", __name__)

CATEGORIAS = ["cortes", "color", "barbería", "uñas", "spa", "maquillaje", "general"]

# INICIO AGREGADO: configuración para las imágenes de los servicios.

BUCKET_IMAGENES_SERVICIOS = "servicios"

# Tamaño máximo permitido: 5 MB.
MAX_IMAGEN_BYTES = 5 * 1024 * 1024

# Formatos de imagen permitidos.
TIPOS_IMAGEN = {
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/webp": (".webp",),
}


def _validar_imagen(archivo):
    """
    Comprueba que el profesional haya seleccionado una imagen válida.
    """

    if archivo is None or not archivo.filename:
        return None, "Debes seleccionar una imagen para el servicio."

    nombre = secure_filename(archivo.filename)

    extension = (
        "." + nombre.rsplit(".", 1)[-1].lower()
        if "." in nombre else ""
    )

    mimetype = (archivo.mimetype or "").lower()

    extensiones = TIPOS_IMAGEN.get(mimetype)

    if not extensiones or extension not in extensiones:
        return None, "La imagen debe ser JPG, PNG o WEBP."

    contenido = archivo.read(MAX_IMAGEN_BYTES + 1)
    archivo.stream.seek(0)

    if not contenido:
        return None, "El archivo seleccionado está vacío."

    if len(contenido) > MAX_IMAGEN_BYTES:
        return None, "La imagen no puede superar los 5 MB."

    # Verificar la firma real del archivo.
    firmas = {
        "image/jpeg": contenido.startswith(b"\xff\xd8\xff"),
        "image/png": contenido.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": (
            len(contenido) >= 12
            and contenido[:4] == b"RIFF"
            and contenido[8:12] == b"WEBP"
        ),
    }

    if not firmas.get(mimetype, False):
        return None, "El archivo no parece ser una imagen válida."

    return {
        "contenido": contenido,
        "mimetype": mimetype,
        "extension": extension
    }, None



# INICIO AGREGADO JESUS: carga de imágenes con autenticación JWT correcta.

def _subir_imagen_servicio(sb_usuario, imagen):
    # INICIO AGREGADO JESUS: validar y comprobar identidad del profesional.

    access_token = session.get("access_token")

    if not access_token:
        raise RuntimeError("No existe una sesión autenticada.")

    if not session.get("user_id"):
        raise RuntimeError("No se encontró el usuario de la sesión.")

    import base64
    import json

    partes_token = access_token.split(".")

    if len(partes_token) != 3:
        raise RuntimeError("El token de autenticación no es válido.")

    payload = partes_token[1]
    payload += "=" * (-len(payload) % 4)

    datos_token = json.loads(
        base64.urlsafe_b64decode(payload)
    )

    uid_token = datos_token.get("sub")
    uid_sesion = session.get("user_id")

    print("========== COMPARACIÓN DE UID ==========")
    print("UID de Flask:", uid_sesion)
    print("UID del token:", uid_token)
    print("¿Coinciden?:", uid_sesion == uid_token)
    print("========================================")

    if uid_sesion != uid_token:
        raise RuntimeError(
            "El usuario de la sesión no coincide con el usuario del token."
        )

    # FIN AGREGADO JESUS: validar y comprobar identidad del profesional.

    nombre_archivo = (
        f"{uid_sesion}/"
        f"{uuid.uuid4().hex}{imagen['extension']}"
    )

    storage = storage_como_usuario(access_token)

    try:
        bucket = storage.from_(BUCKET_IMAGENES_SERVICIOS)

        bucket.upload(
            nombre_archivo,
            imagen["contenido"],
            {
                "content-type": imagen["mimetype"],
                "upsert": "false"
            }
        )

        imagen_url = bucket.get_public_url(nombre_archivo)

        return imagen_url

    finally:
        storage.session.close()

# FIN AGREGADO JESUS: carga de imágenes con autenticación JWT correcta.


@servicios_bp.route("/servicios")
def catalogo():
    """RF-06: catálogo público (solo servicios activos de proveedores aprobados)."""
    categoria = request.args.get("categoria")
    consulta = sb.table("servicios").select(
        "*, profesionales!inner(id, nombre_negocio, especialidad, ubicacion, estado)"
        ).eq("activo", True).eq("profesionales.estado", "aprobado").eq("profesionales.activo", True)

    if categoria in CATEGORIAS:
        consulta = consulta.eq("categoria", categoria)
    else:
        categoria = None

    respuesta = consulta.order("creado_en", desc=True).execute()
    servicios = respuesta.data
    _agregar_calificaciones(servicios)
    return render_template("servicios/listar.html", servicios=servicios,
                           categoria=categoria, categorias=CATEGORIAS)


def _agregar_calificaciones(servicios):
    """HU-15: cada servicio muestra solo las opiniones de las citas de ESE servicio
    (no las del proveedor en general). Agrega 'total_calificaciones' y 'calificacion_promedio'."""
    suma, total = {}, {}
    ids = [s["id"] for s in servicios]
    try:
        for i in range(0, len(ids), 50):      # por lotes: evita URLs demasiado largas
            filas = sb.table("calificaciones").select("servicio_id, puntuacion").in_(
                "servicio_id", ids[i:i + 50]).execute().data
            for f in filas:
                total[f["servicio_id"]] = total.get(f["servicio_id"], 0) + 1
                suma[f["servicio_id"]] = suma.get(f["servicio_id"], 0) + f["puntuacion"]
    except Exception as error:
        mensaje_error(error)                  # queda en el log; el catálogo se muestra sin estrellas
        suma, total = {}, {}
    for s in servicios:
        n = total.get(s["id"], 0)
        s["total_calificaciones"] = n
        s["calificacion_promedio"] = round(suma[s["id"]] / n, 2) if n else None


def _negocio_o_redirigir(sb_usuario):
    negocio = proveedor_propio(sb_usuario)
    if negocio is None:
        flash("Primero registra los datos de tu negocio.", "error")
        return None, redirect(url_for("profesionales.registro"))
    return negocio, None


def _servicio_propio(sb_usuario, negocio, servicio_id):
    return primero(sb_usuario.table("servicios").select("*")
                   .eq("id", servicio_id).eq("profesional_id", negocio["id"]).limit(1).execute())


@servicios_bp.route("/mis-servicios")
@exigir_proveedor
def gestionar():
    """RF-05: el proveedor ve y administra sus servicios (activos e inactivos)."""
    sb_usuario = cliente_sesion()
    negocio, redireccion = _negocio_o_redirigir(sb_usuario)
    if redireccion:
        return redireccion

    servicios = sb_usuario.table("servicios").select("*").eq(
        "profesional_id", negocio["id"]).order("creado_en", desc=True).execute()
    return render_template("servicios/gestionar.html", servicios=servicios.data, negocio=negocio)


# INICIO AGREGADO JESUS: creación de servicios con imagen obligatoria.

@servicios_bp.route("/mis-servicios/nuevo", methods=["GET", "POST"])
@exigir_proveedor
def nuevo():

    sb_usuario = cliente_sesion()

    negocio, redireccion = _negocio_o_redirigir(sb_usuario)

    if redireccion:
        return redireccion

    if request.method == "GET":
        return render_template(
            "servicios/form.html",
            servicio=None,
            categorias=CATEGORIAS
        )

    # Leer la información del formulario.
    datos = _leer_formulario()

    # Obtener y validar la imagen.
    imagen, error_imagen = _validar_imagen(
        request.files.get("imagen")
    )

    if datos is None or error_imagen:

        if error_imagen:
            flash(error_imagen, "error")

        return render_template(
            "servicios/form.html",
            servicio=request.form,
            categorias=CATEGORIAS
        )

    datos["profesional_id"] = negocio["id"]

    try:

        # Subir primero la imagen.
        datos["imagen_url"] = _subir_imagen_servicio(
            sb_usuario,
            imagen
        )

        # Guardar el servicio con su imagen.
        sb_usuario.table("servicios").insert(datos).execute()

    except Exception as error:

        flash(
            mensaje_error(error, "No se pudo guardar el servicio."),
            "error"
        )

        return render_template(
            "servicios/form.html",
            servicio=request.form,
            categorias=CATEGORIAS
        )

    flash("Servicio agregado al catálogo.", "success")

    return redirect(url_for("servicios.gestionar"))

# FIN AGREGADO JESUS: creación de servicios con imagen obligatoria.


# INICIO AGREGADO JESUS: edición de servicios con posibilidad de cambiar la imagen.

@servicios_bp.route("/mis-servicios/<servicio_id>/editar", methods=["GET", "POST"])
@exigir_proveedor
def editar(servicio_id):

    sb_usuario = cliente_sesion()

    negocio, redireccion = _negocio_o_redirigir(sb_usuario)

    if redireccion:
        return redireccion

    servicio = _servicio_propio(
        sb_usuario,
        negocio,
        servicio_id
    )

    if servicio is None:
        abort(404)

    if request.method == "GET":
        return render_template(
            "servicios/form.html",
            servicio=servicio,
            categorias=CATEGORIAS
        )

    datos = _leer_formulario()

    archivo_imagen = request.files.get("imagen")

    imagen = None

    # La imagen es opcional al editar.
    if archivo_imagen and archivo_imagen.filename:

        imagen, error_imagen = _validar_imagen(
            archivo_imagen
        )

        if error_imagen:

            flash(error_imagen, "error")

            return render_template(
                "servicios/form.html",
                servicio={**servicio, **request.form},
                categorias=CATEGORIAS
            )

    if datos is None:

        return render_template(
            "servicios/form.html",
            servicio={**servicio, **request.form},
            categorias=CATEGORIAS
        )

    try:

        # Si selecciona una nueva imagen, se reemplaza la URL.
        if imagen:

            datos["imagen_url"] = _subir_imagen_servicio(
                sb_usuario,
                imagen
            )

        sb_usuario.table("servicios").update(datos).eq(
            "id", servicio_id
        ).eq(
            "profesional_id", negocio["id"]
        ).execute()

    except Exception as error:

        flash(
            mensaje_error(error, "No se pudo actualizar el servicio."),
            "error"
        )

        return render_template(
            "servicios/form.html",
            servicio={**servicio, **request.form},
            categorias=CATEGORIAS
        )

    flash("Servicio actualizado.", "success")

    return redirect(url_for("servicios.gestionar"))

# FIN AGREGADO JESUS: edición de servicios con imagen.


@servicios_bp.route("/mis-servicios/<servicio_id>/estado", methods=["POST"])
@exigir_proveedor
def cambiar_estado(servicio_id):
    """RN-05: en vez de borrar (y perder el historial de citas) el servicio se desactiva/reactiva."""
    sb_usuario = cliente_sesion()
    negocio, redireccion = _negocio_o_redirigir(sb_usuario)
    if redireccion:
        return redireccion

    servicio = _servicio_propio(sb_usuario, negocio, servicio_id)
    if servicio is None:
        abort(404)

    nuevo_estado = not servicio["activo"]
    try:
        sb_usuario.table("servicios").update({"activo": nuevo_estado}).eq(
            "id", servicio_id).eq("profesional_id", negocio["id"]).execute()
    except Exception as error:
        flash(mensaje_error(error), "error")
        return redirect(url_for("servicios.gestionar"))

    flash("Servicio reactivado: ya se puede reservar." if nuevo_estado
          else "Servicio desactivado: ya no aparece para reservas (el historial se conserva).", "success")
    return redirect(url_for("servicios.gestionar"))


def _leer_formulario():
    """RN-04/06/07: nombre, precio y duración obligatorios y válidos. None si hay error."""
    nombre = request.form.get("nombre", "").strip()
    categoria = request.form.get("categoria", "general").strip().lower()
    descripcion = request.form.get("descripcion", "").strip()
    precio = request.form.get("precio", "").strip()
    duracion_min = request.form.get("duracion_min", "").strip()

    if not nombre or not precio or not duracion_min:
        flash("Nombre, precio y duración son obligatorios.", "error")
        return None
    if len(nombre) > 100 or len(descripcion) > 500:
        flash("El nombre (máx. 100) o la descripción (máx. 500) es demasiado largo.", "error")
        return None
    if categoria not in CATEGORIAS:
        flash("Elige una categoría de la lista.", "error")
        return None

    try:
        precio = round(float(precio), 2)
        duracion_min = int(duracion_min)
    except ValueError:
        flash("Precio y duración deben ser numéricos.", "error")
        return None
    if precio <= 0 or precio > 99999999:
        flash("El precio debe ser mayor que cero.", "error")
        return None
    if not 10 <= duracion_min <= 480:
        flash("La duración debe estar entre 10 y 480 minutos.", "error")
        return None

    return {"nombre": nombre, "categoria": categoria, "descripcion": descripcion,
            "precio": precio, "duracion_min": duracion_min}
