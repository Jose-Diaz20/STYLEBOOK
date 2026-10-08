"""StyleBook - Sprint 1"""
import logging
import os
import secrets
import time

from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.exceptions import Forbidden, NotFound

load_dotenv()

from blueprints.auth import auth_bp
from blueprints.perfil import perfil_bp
from blueprints.profesionales import profesionales_bp
from blueprints.servicios import servicios_bp
from blueprints.admin import admin_bp
from blueprints.horarios import horarios_bp
from blueprints.citas import citas_bp
from blueprints.notificaciones import notificaciones_bp, contar_sin_leer
from utilidades import SesionExpirada

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

_clave = os.environ.get("FLASK_SECRET_KEY")

if not _clave:
    # En desarrollo local puedes usar una por defecto, pero es mejor lanzar un error explícito
    raise KeyError("ERROR CRÍTICO: La variable de entorno FLASK_SECRET_KEY no está definida en el archivo .env.")

app.secret_key = _clave

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",  # =1 en producción (HTTPS)
)

for bp in (auth_bp, perfil_bp, profesionales_bp, servicios_bp, admin_bp, horarios_bp, citas_bp,
           notificaciones_bp):
    app.register_blueprint(bp)


# ---------- Protección CSRF para todo formulario POST ----------
def _token_csrf():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


@app.context_processor
def _inyectar_csrf():
    return {"csrf_token": _token_csrf}


@app.before_request
def _verificar_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        enviado = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        esperado = session.get("csrf_token", "")
        if not esperado or not secrets.compare_digest(enviado.encode(), esperado.encode()):
            abort(400, description="La sesión del formulario expiró. Recarga la página e inténtalo de nuevo.")


# ---------- Notificaciones sin leer (globito del menú) ----------
@app.context_processor
def _inyectar_notificaciones():
    def sin_leer():
        if "access_token" not in session:
            return 0
        cache = session.get("_notif")
        if cache and time.time() - cache[0] < 30:      # como máximo una consulta cada 30 s
            return cache[1]
        try:
            total = contar_sin_leer()
        except Exception:
            return 0
        session["_notif"] = [time.time(), total]
        return total
    return {"notificaciones_sin_leer": sin_leer}


# ---------- Páginas de error ----------
@app.errorhandler(SesionExpirada)
def _sesion_expirada(error):
    flash("Tu sesión expiró. Inicia sesión de nuevo.", "error")
    return redirect(url_for("auth.login"))


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
def _error_cliente(error):
    por_defecto = {
        403: ("No tienes permiso para ver esta página.", Forbidden.description),
        404: ("No encontramos lo que buscas.", NotFound.description),
    }
    if error.code in por_defecto:
        propio, original = por_defecto[error.code]
        mensaje = propio if error.description == original else error.description
    else:
        mensaje = getattr(error, "description", None) or "Solicitud no válida."
    return render_template("error.html", codigo=error.code, mensaje=mensaje), error.code


@app.errorhandler(500)
def _error_servidor(error):
    return render_template("error.html", codigo=500,
                           mensaje="Algo salió mal de nuestro lado. Inténtalo de nuevo en un momento."), 500


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
