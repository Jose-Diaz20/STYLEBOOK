"""
Notificaciones dentro de la app. Las crea la base de datos (trigger `notificar_cita` en schema.sql)
cuando se solicita, confirma, rechaza, cancela, completa o reprograma una cita:
  · al profesional le llega cada nueva solicitud y las cancelaciones/reprogramaciones del cliente;
  · al cliente le llega el acuse de su solicitud, la confirmación, el rechazo, la cancelación y la finalización;
  · el recordatorio de una cita confirmada (24 h antes) lo crea `generar_recordatorios()` (schema.sql):
    pg_cron cada 15 min y, como respaldo, la llamada de abajo cuando el cliente abre la app.
"""
from datetime import datetime

from flask import Blueprint, render_template, session

from disponibilidad import ZONA
from utilidades import cliente_sesion, exigir_sesion, log

notificaciones_bp = Blueprint("notificaciones", __name__)


def generar_recordatorios():
    """Respaldo de pg_cron: pide a la base los recordatorios pendientes de las citas del cliente.
    Nunca rompe la página (si la función aún no existe en la base solo queda en el log)."""
    if session.get("rol") != "cliente":
        return
    try:
        cliente_sesion().rpc("generar_recordatorios", {}).execute()
    except Exception as error:
        log.warning("No se pudieron generar los recordatorios: %r", error)


def contar_sin_leer():
    generar_recordatorios()
    respuesta = cliente_sesion().table("notificaciones").select("id", count="exact").eq(
        "usuario_id", session["user_id"]).eq("leida", False).execute()
    return respuesta.count or 0


def _cuando(texto):
    """ISO con zona (UTC) → '30/09/2026 14:05' en hora de Colombia; vacío si no se puede leer."""
    try:
        return datetime.fromisoformat(texto).astimezone(ZONA).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return ""


@notificaciones_bp.route("/notificaciones")
@exigir_sesion
def listar():
    generar_recordatorios()
    sb_usuario = cliente_sesion()
    filas = sb_usuario.table("notificaciones").select("*").eq(
        "usuario_id", session["user_id"]).order("creado_en", desc=True).limit(50).execute().data
    for n in filas:
        n["cuando"] = _cuando(n.get("creado_en"))

    if any(not n["leida"] for n in filas):
        try:   # se muestran como "nuevas" en esta visita y quedan leídas para la siguiente
            sb_usuario.table("notificaciones").update({"leida": True}).eq(
                "usuario_id", session["user_id"]).eq("leida", False).execute()
        except Exception as error:
            log.warning("No se pudieron marcar las notificaciones como leídas: %r", error)
    session.pop("_notif", None)
    return render_template("notificaciones/listar.html", notificaciones=filas)
