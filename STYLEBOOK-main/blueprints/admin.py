"""
Panel de administrador:
  · aprobar o rechazar el registro de proveedores antes de que aparezcan públicamente;
  · ver los servicios (con foto) que ofrece cada proveedor;
  · eliminar un servicio indicando el motivo (el proveedor lo recibe como notificación).
"""
from flask import Blueprint, abort, render_template, redirect, request, session, url_for, flash

from blueprints.servicios import BUCKET_IMAGENES_SERVICIOS
from supabase_client import storage_como_usuario
from utilidades import exigir_admin, cliente_sesion, mensaje_error, primero, log

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

MOTIVO_MIN = 10
MOTIVO_MAX = 500


def _servicios_por_proveedor(sb_admin):
    """{profesional_id: [servicios…]} con todos los servicios (activos e inactivos)."""
    filas = sb_admin.table("servicios").select("*").order("creado_en", desc=True).execute().data
    agrupados = {}
    for s in filas:
        agrupados.setdefault(s["profesional_id"], []).append(s)
    return agrupados


@admin_bp.route("/")
@exigir_admin
def panel():
    sb_admin = cliente_sesion()

    profesionales = sb_admin.table("profesionales").select("*").order("nombre_negocio").execute().data
    servicios = _servicios_por_proveedor(sb_admin)
    for p in profesionales:
        p["servicios"] = servicios.get(p["id"], [])

    pendientes = sorted((p for p in profesionales if p["estado"] == "pendiente"),
                        key=lambda p: str(p.get("creado_en")))
    registrados = [p for p in profesionales if p["estado"] != "pendiente"]

    return render_template(
        "admin/panel.html",
        pendientes=pendientes,
        registrados=registrados,
        total_aprobados=sum(1 for p in profesionales if p["estado"] == "aprobado"),
        total_servicios=sum(1 for lista in servicios.values() for s in lista if s["activo"]),
    )


def _cambiar_estado(profesional_id, estado, mensaje_ok):
    sb_admin = cliente_sesion()
    try:
        resultado = sb_admin.table("profesionales").update({"estado": estado}).eq(
            "id", profesional_id).execute()
    except Exception as error:
        flash(mensaje_error(error), "error")
        return redirect(url_for("admin.panel"))
    if not resultado.data:
        abort(404)
    flash(mensaje_ok, "success")
    return redirect(url_for("admin.panel"))


@admin_bp.route("/profesionales/<profesional_id>/aprobar", methods=["POST"])
@exigir_admin
def aprobar(profesional_id):
    return _cambiar_estado(profesional_id, "aprobado",
                           "Proveedor aprobado. Ya aparece en el listado público.")


@admin_bp.route("/profesionales/<profesional_id>/rechazar", methods=["POST"])
@exigir_admin
def rechazar(profesional_id):
    return _cambiar_estado(profesional_id, "rechazado", "Registro de proveedor rechazado.")


def _ruta_en_storage(imagen_url):
    """'https://…/object/public/servicios/<uid>/<archivo>.jpg?x' → '<uid>/<archivo>.jpg'."""
    marca = f"/object/public/{BUCKET_IMAGENES_SERVICIOS}/"
    if not imagen_url or marca not in imagen_url:
        return None
    return imagen_url.split(marca, 1)[1].split("?", 1)[0] or None


def _borrar_foto(imagen_url):
    """Quita del Storage la foto de un servicio eliminado. Si falla solo queda en el log:
    el servicio ya se eliminó y no vale la pena asustar al administrador por un archivo suelto."""
    ruta = _ruta_en_storage(imagen_url)
    if not ruta:
        return
    storage = None
    try:
        storage = storage_como_usuario(session.get("access_token"))
        storage.from_(BUCKET_IMAGENES_SERVICIOS).remove([ruta])
    except Exception as error:
        log.warning("No se pudo borrar la foto %s del Storage: %r", ruta, error)
    finally:
        if storage is not None:
            storage.session.close()


def _volver_al_panel(profesional_id=None):
    """De regreso al panel dejando abierto el proveedor que se estaba revisando."""
    if not profesional_id:
        return redirect(url_for("admin.panel"))
    return redirect(url_for("admin.panel", abrir=profesional_id) + f"#prov-{profesional_id}")


@admin_bp.route("/servicios/<servicio_id>/eliminar", methods=["POST"])
@exigir_admin
def eliminar_servicio(servicio_id):
    """El administrador elimina un servicio y debe justificarlo (el proveedor recibe el motivo)."""
    motivo = request.form.get("motivo", "").strip()

    sb_admin = cliente_sesion()
    servicio = primero(sb_admin.table("servicios").select("id, nombre, imagen_url, profesional_id")
                       .eq("id", servicio_id).limit(1).execute())
    if servicio is None:
        abort(404)
    volver = lambda: _volver_al_panel(servicio["profesional_id"])

    if len(motivo) < MOTIVO_MIN:
        flash(f"Escribe el motivo de la eliminación (mínimo {MOTIVO_MIN} caracteres).", "error")
        return volver()
    if len(motivo) > MOTIVO_MAX:
        flash(f"El motivo es demasiado largo (máximo {MOTIVO_MAX} caracteres).", "error")
        return volver()

    try:
        resultado = sb_admin.rpc("admin_retirar_servicio",
                                 {"p_servicio_id": servicio_id, "p_motivo": motivo}).execute().data
    except Exception as error:
        flash(mensaje_error(error, "No se pudo eliminar el servicio. Inténtalo de nuevo."), "error")
        return volver()

    if resultado == "eliminado":
        _borrar_foto(servicio.get("imagen_url"))
        flash(f"Servicio «{servicio['nombre']}» eliminado. El profesional recibió el motivo.", "success")
    else:
        flash(f"«{servicio['nombre']}» ya tenía citas, así que se retiró del catálogo y se conserva "
              "el historial de los clientes. Las citas futuras se cancelaron y el profesional "
              "recibió el motivo.", "success")
    return volver()
