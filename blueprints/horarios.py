"""Horario semanal de atención del proveedor (RN-08, RF-04)."""
from flask import Blueprint, abort, render_template, request, redirect, url_for, flash

from disponibilidad import parsear_hora
from utilidades import exigir_proveedor, cliente_sesion, primero, proveedor_propio, mensaje_error

horarios_bp = Blueprint("horarios", __name__)
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def _negocio(sb_usuario):
    negocio = proveedor_propio(sb_usuario)
    if negocio is None:
        flash("Primero registra los datos de tu negocio.", "error")
    return negocio


@horarios_bp.route("/mis-horarios")
@exigir_proveedor
def gestionar():
    sb_usuario = cliente_sesion()
    negocio = _negocio(sb_usuario)
    if negocio is None:
        return redirect(url_for("profesionales.registro"))
    horarios = sb_usuario.table("horarios_profesional").select("*").eq(
        "profesional_id", negocio["id"]).order("dia_semana").order("hora_inicio").execute().data or []
    por_dia = {int(h["dia_semana"]): h for h in horarios}
    return render_template("horarios/gestionar.html", horarios=horarios, por_dia=por_dia, dias=DIAS)


@horarios_bp.route("/mis-horarios/semana", methods=["POST"])
@exigir_proveedor
def guardar_semana():
    """Guarda los siete días en una operación lógica, con pausas opcionales."""
    sb_usuario = cliente_sesion()
    negocio = _negocio(sb_usuario)
    if negocio is None:
        return redirect(url_for("profesionales.registro"))

    nuevos = []
    for dia in range(7):
        activo = request.form.get(f"activo_{dia}") == "on"
        if not activo:
            continue
        inicio = parsear_hora(request.form.get(f"hora_inicio_{dia}", "").strip())
        fin = parsear_hora(request.form.get(f"hora_fin_{dia}", "").strip())
        pausa_inicio_txt = request.form.get(f"pausa_inicio_{dia}", "").strip()
        pausa_fin_txt = request.form.get(f"pausa_fin_{dia}", "").strip()
        pausa_inicio = parsear_hora(pausa_inicio_txt) if pausa_inicio_txt else None
        pausa_fin = parsear_hora(pausa_fin_txt) if pausa_fin_txt else None

        if inicio is None or fin is None or fin <= inicio:
            flash(f"Revisa las horas de atención del {DIAS[dia].lower()}.", "error")
            return redirect(url_for("horarios.gestionar"))
        if bool(pausa_inicio_txt) != bool(pausa_fin_txt):
            flash(f"Debes indicar inicio y fin de la pausa del {DIAS[dia].lower()}, o dejar ambos vacíos.", "error")
            return redirect(url_for("horarios.gestionar"))
        if pausa_inicio and (pausa_fin <= pausa_inicio or pausa_inicio <= inicio or pausa_fin >= fin):
            flash(f"La pausa del {DIAS[dia].lower()} debe estar dentro del horario de atención.", "error")
            return redirect(url_for("horarios.gestionar"))

        nuevos.append({
            "profesional_id": negocio["id"],
            "dia_semana": dia,
            "hora_inicio": inicio.strftime("%H:%M"),
            "hora_fin": fin.strftime("%H:%M"),
            "pausa_inicio": pausa_inicio.strftime("%H:%M") if pausa_inicio else None,
            "pausa_fin": pausa_fin.strftime("%H:%M") if pausa_fin else None,
        })

    anteriores = sb_usuario.table("horarios_profesional").select(
        "dia_semana, hora_inicio, hora_fin, pausa_inicio, pausa_fin"
    ).eq("profesional_id", negocio["id"]).execute().data or []
    try:
        # Sustituir la configuración semanal existente.
        sb_usuario.table("horarios_profesional").delete().eq(
            "profesional_id", negocio["id"]).execute()
        if nuevos:
            sb_usuario.table("horarios_profesional").insert(nuevos).execute()
    except Exception as error:
        # Intento de restauración si el insert falla después del borrado.
        try:
            sb_usuario.table("horarios_profesional").delete().eq(
                "profesional_id", negocio["id"]).execute()
            restaurar = []
            for h in anteriores:
                restaurar.append({
                    "profesional_id": negocio["id"],
                    "dia_semana": h["dia_semana"],
                    "hora_inicio": str(h["hora_inicio"])[:5],
                    "hora_fin": str(h["hora_fin"])[:5],
                    "pausa_inicio": str(h["pausa_inicio"])[:5] if h.get("pausa_inicio") else None,
                    "pausa_fin": str(h["pausa_fin"])[:5] if h.get("pausa_fin") else None,
                })
            if restaurar:
                sb_usuario.table("horarios_profesional").insert(restaurar).execute()
        except Exception:
            pass
        flash(mensaje_error(error, "No se pudo guardar el horario semanal. Verifica que ejecutaste la migración SQL de pausas."), "error")
        return redirect(url_for("horarios.gestionar"))

    flash("Horario semanal guardado correctamente.", "success")
    return redirect(url_for("horarios.gestionar"))


# Compatibilidad con enlaces/formularios antiguos.
@horarios_bp.route("/mis-horarios/nuevo", methods=["POST"])
@exigir_proveedor
def nuevo():
    flash("Ahora configura los siete días desde el formulario de horario semanal.", "info")
    return redirect(url_for("horarios.gestionar"))


@horarios_bp.route("/mis-horarios/<horario_id>/eliminar", methods=["POST"])
@exigir_proveedor
def eliminar(horario_id):
    sb_usuario = cliente_sesion()
    negocio = _negocio(sb_usuario)
    if negocio is None:
        return redirect(url_for("profesionales.registro"))
    fila = primero(sb_usuario.table("horarios_profesional").select("id").eq(
        "id", horario_id).eq("profesional_id", negocio["id"]).limit(1).execute())
    if fila is None:
        abort(404)
    try:
        sb_usuario.table("horarios_profesional").delete().eq("id", horario_id).eq(
            "profesional_id", negocio["id"]).execute()
    except Exception as error:
        flash(mensaje_error(error), "error")
        return redirect(url_for("horarios.gestionar"))
    flash("Franja horaria eliminada.", "success")
    return redirect(url_for("horarios.gestionar"))
