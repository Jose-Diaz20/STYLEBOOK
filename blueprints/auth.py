"""RF-01 Registro de usuario (cliente, establecimiento o profesional independiente)
RF-02 Inicio de sesión"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash

import logging

from supabase_client import cliente_anonimo, sb_como_usuario
from utilidades import (
    ROLES_PROVEEDOR, cliente_sesion, correo_valido, telefono_valido, destino_seguro,
    mensaje_error, primero, proveedor_propio,
)

log = logging.getLogger("stylebook")

auth_bp = Blueprint("auth", __name__)

# RN-02: los únicos tipos de cuenta que se pueden elegir al registrarse.
TIPOS_CUENTA = {
    "cliente": "Cliente — quiero reservar citas",
    "establecimiento": "Establecimiento — salón o barbería",
    "profesional": "Profesional independiente",
}


@auth_bp.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "GET":
        return render_template("auth/registro.html", tipos=TIPOS_CUENTA, form={})

    form = {
        "nombre": request.form.get("nombre", "").strip(),
        "email": request.form.get("email", "").strip().lower(),
        "telefono": request.form.get("telefono", "").strip(),
        "tipo_cuenta": request.form.get("tipo_cuenta", "cliente"),
    }
    password = request.form.get("password", "")

    def volver(mensaje):
        flash(mensaje, "error")
        return render_template("auth/registro.html", tipos=TIPOS_CUENTA, form=form)

    if form["tipo_cuenta"] not in TIPOS_CUENTA:   # 'admin' nunca es elegible
        return volver("Elige un tipo de cuenta válido.")
    if not form["nombre"] or not form["email"] or not password:
        return volver("Nombre, correo y contraseña son obligatorios.")
    if len(form["nombre"]) > 100:
        return volver("El nombre es demasiado largo.")
    if not correo_valido(form["email"]):
        return volver("Escribe un correo electrónico válido.")
    if not telefono_valido(form["telefono"]):
        return volver("El teléfono no es válido (solo números, espacios, + y guiones).")
    if len(password) < 6:
        return volver("La contraseña debe tener al menos 6 caracteres.")

    try:
        # Nombre, teléfono y tipo de cuenta viajan en el sign_up; el trigger crear_perfil()
        # los guarda, así funciona igual si Supabase exige confirmar el correo.
        resultado = cliente_anonimo().auth.sign_up({   # cliente aislado: no contamina el compartido
            "email": form["email"],
            "password": password,
            "options": {"data": {
                "nombre": form["nombre"],
                "telefono": form["telefono"],
                "tipo_cuenta": form["tipo_cuenta"],
            }},
        })
    except Exception as error:
        return volver(mensaje_error(error, "No se pudo completar el registro."))

    if resultado.user is None:
        return volver("No se pudo crear la cuenta. Inténtalo de nuevo.")

    if resultado.session is None:
        flash("Cuenta creada. Revisa tu correo para confirmar antes de iniciar sesión.", "success")
        return redirect(url_for("auth.login"))

    if not _guardar_sesion(resultado):
        return volver("Tu cuenta se creó pero no pudimos cargar tu perfil. Inicia sesión de nuevo.")
    flash("Cuenta creada correctamente. ¡Bienvenido a StyleBook!", "success")
    return _destino_inicial()


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("auth/login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    try:
        resultado = cliente_anonimo().auth.sign_in_with_password({"email": email, "password": password})
    except Exception as error:
        if "not confirmed" in str(error).lower():
            flash("Debes confirmar tu correo antes de iniciar sesión.", "error")
        else:
            flash("Correo o contraseña incorrectos.", "error")
        return render_template("auth/login.html")

    if not _guardar_sesion(resultado):
        flash("No pudimos cargar tu perfil. Inténtalo de nuevo o contacta al administrador.", "error")
        return render_template("auth/login.html")
    flash("Sesión iniciada correctamente.", "success")

    destino = destino_seguro(request.args.get("volver"))
    if destino:
        return redirect(destino)
    return _destino_inicial()


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada.", "success")
    return redirect(url_for("index"))


def _destino_inicial():
    """Adónde ir tras entrar (RF-02, RN-03). Todos aterrizan en la página principal, salvo el
    administrador (su panel) y el proveedor que aún no registró su negocio."""
    rol = session.get("rol")
    if rol == "admin":
        return redirect(url_for("admin.panel"))
    if rol in ROLES_PROVEEDOR and proveedor_propio(cliente_sesion()) is None:
        flash("Completa los datos de tu negocio para aparecer en el listado.", "success")
        return redirect(url_for("profesionales.registro"))
    return redirect(url_for("index"))


def _guardar_sesion(resultado):
    """Guarda tokens, nombre y tipo de cuenta en la sesión de Flask.
    Devuelve False (sin dejar sesión iniciada) si no se puede leer el perfil: antes se asumía
    'cliente' en silencio, y por eso un profesional podía ver el menú y los permisos de cliente."""
    csrf = session.get("csrf_token")
    session.clear()                      # evita arrastrar datos de una sesión anterior
    if csrf:
        session["csrf_token"] = csrf

    try:
        cliente = sb_como_usuario(resultado.session.access_token, resultado.session.refresh_token)
        perfil = primero(cliente.table("perfiles").select("rol, nombre")
                         .eq("id", resultado.user.id).limit(1).execute())
    except Exception as error:
        log.error("No se pudo leer el perfil de %s: %r", resultado.user.id, error)
        return False
    if perfil is None:
        log.error("El usuario %s no tiene fila en `perfiles`. Ejecuta db/schema.sql y "
                  "db/reparar_cuentas.sql en Supabase.", resultado.user.id)
        return False

    session["access_token"] = resultado.session.access_token
    session["refresh_token"] = resultado.session.refresh_token
    session["user_id"] = resultado.user.id
    session["rol"] = perfil["rol"]
    session["nombre"] = perfil["nombre"]
    return True
