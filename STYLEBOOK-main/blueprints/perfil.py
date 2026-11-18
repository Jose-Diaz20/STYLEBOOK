"""RF-03 Gestión del perfil"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from utilidades import (
    ROLES_PROVEEDOR, exigir_sesion, cliente_sesion, primero, proveedor_propio,
    telefono_valido, direccion_valida, mensaje_error, MSG_TELEFONO, MSG_DIRECCION,
)

perfil_bp = Blueprint("perfil", __name__)


def _mi_perfil(sb_usuario):
    return primero(sb_usuario.table("perfiles").select("*")
                   .eq("id", session["user_id"]).limit(1).execute())


@perfil_bp.route("/perfil")
@exigir_sesion
def ver():
    sb_usuario = cliente_sesion()
    perfil = _mi_perfil(sb_usuario)
    if perfil is None:
        flash("No encontramos tu perfil. Vuelve a iniciar sesión.", "error")
        return redirect(url_for("auth.logout"))
    negocio = proveedor_propio(sb_usuario) if perfil["rol"] in ROLES_PROVEEDOR else None
    return render_template("perfil/ver.html", perfil=perfil, negocio=negocio)


@perfil_bp.route("/perfil/editar", methods=["GET", "POST"])
@exigir_sesion
def editar():
    sb_usuario = cliente_sesion()
    perfil = _mi_perfil(sb_usuario)
    if perfil is None:
        return redirect(url_for("perfil.ver"))

    if request.method == "GET":
        return render_template("perfil/editar.html", perfil=perfil)

    nombre = request.form.get("nombre", "").strip()
    telefono = request.form.get("telefono", "").strip()
    direccion = " ".join(request.form.get("direccion", "").split())

    if not nombre or len(nombre) > 100:
        flash("El nombre es obligatorio (máximo 100 caracteres).", "error")
        return redirect(url_for("perfil.editar"))
    if not telefono_valido(telefono):
        flash(MSG_TELEFONO, "error")
        return redirect(url_for("perfil.editar"))
    if not direccion_valida(direccion):
        flash(MSG_DIRECCION, "error")
        return redirect(url_for("perfil.editar"))

    try:
        # Solo nombre, teléfono y dirección; el tipo de cuenta (rol) no se toca y además lo protege la base.
        sb_usuario.table("perfiles").update({
            "nombre": nombre,
            "telefono": telefono or None,
            "direccion": direccion,
        }).eq("id", session["user_id"]).execute()
    except Exception as error:
        flash(mensaje_error(error), "error")
        return redirect(url_for("perfil.editar"))

    session["nombre"] = nombre
    flash("Perfil actualizado correctamente.", "success")
    return redirect(url_for("perfil.ver"))