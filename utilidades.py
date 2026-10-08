"""
Utilidades compartidas: sesión, roles, validaciones, redirección segura y
traducción de errores técnicos a mensajes para el usuario.
"""
import base64
import json
import logging
import re
import time
from functools import wraps
from urllib.parse import urlparse

from flask import session, redirect, url_for, request, abort, flash

from supabase_client import sb_como_usuario, renovar_sesion

log = logging.getLogger("stylebook")

# RN-02: tipos de cuenta. "admin" es interno (se asigna desde la base de datos).
ROLES_PROVEEDOR = ("establecimiento", "profesional")

_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RE_TELEFONO = re.compile(r"^\+?[0-9][0-9\s().-]{6,19}$")


# ---------- Sesión y roles (RF-02, RN-03) ----------

class SesionExpirada(Exception):
    """La sesión de Supabase venció y no se pudo renovar: hay que iniciar sesión de nuevo."""


def _expira_en(token):
    """Campo `exp` (segundos) del JWT, o None si no se puede leer."""
    try:
        carga = token.split(".")[1]
        carga += "=" * (-len(carga) % 4)
        return int(json.loads(base64.urlsafe_b64decode(carga))["exp"])
    except Exception:
        return None


def renovar_si_hace_falta():
    """Si el access token vence en menos de 60 s, lo renueva y guarda los tokens NUEVOS en la
    sesión de Flask (el refresh token anterior deja de servir). Lanza SesionExpirada si no se puede."""
    exp = _expira_en(session.get("access_token", ""))
    if exp is None or exp - time.time() > 60:
        return
    try:
        nueva = renovar_sesion(session.get("refresh_token", "")).session
    except Exception as error:
        log.warning("No se pudo renovar la sesión: %r", error)
        nueva = None
    if nueva is None:
        session.clear()
        raise SesionExpirada()
    session["access_token"] = nueva.access_token
    session["refresh_token"] = nueva.refresh_token


def _a_login():
    return redirect(url_for("auth.login", volver=request.full_path.rstrip("?")))


def _sesion_activa():
    if "access_token" not in session:
        return False
    try:
        renovar_si_hace_falta()
    except SesionExpirada:
        flash("Tu sesión expiró. Inicia sesión de nuevo.", "error")
        return False
    return True


def exigir_sesion(vista):
    """Redirige a /login si no hay sesión activa."""
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if not _sesion_activa():
            return _a_login()
        return vista(*args, **kwargs)
    return envoltura


_MENSAJE_403 = {
    "cliente": "Esta sección es solo para cuentas de cliente.",
    "establecimiento": "Esta sección es solo para cuentas de profesional o establecimiento.",
    "profesional": "Esta sección es solo para cuentas de profesional o establecimiento.",
    "admin": "Esta sección es solo para administradores.",
}


def exigir_rol(*roles):
    """Exige sesión activa y que el tipo de cuenta esté entre los permitidos (RN-03)."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if not _sesion_activa():
                return _a_login()
            if session.get("rol") not in roles:
                log.warning("403 en %s: el rol de la sesión es %r y se requería uno de %s",
                            request.path, session.get("rol"), roles)
                abort(403, description=_MENSAJE_403.get(roles[0], "No tienes permiso para ver esta página."))
            return vista(*args, **kwargs)
        return envoltura
    return decorador


exigir_admin = exigir_rol("admin")
exigir_cliente = exigir_rol("cliente")
exigir_proveedor = exigir_rol(*ROLES_PROVEEDOR)


def cliente_sesion():
    """Cliente de Supabase autenticado como el usuario actual (para que apliquen las RLS).
    Renueva el token si está por vencer."""
    renovar_si_hace_falta()
    return sb_como_usuario(session["access_token"], session["refresh_token"])


# ---------- Consultas ----------

def primero(respuesta):
    """Primera fila de una respuesta de Supabase o None (evita maybe_single, que según
    la versión devuelve None en vez de una respuesta vacía)."""
    datos = respuesta.data
    return datos[0] if datos else None


def proveedor_propio(sb_usuario):
    """Fila de `profesionales` del usuario en sesión, o None si aún no registró su negocio."""
    return primero(
        sb_usuario.table("profesionales").select("*")
        .eq("perfil_id", session["user_id"]).limit(1).execute()
    )


# ---------- Validaciones (RN-04) ----------

def correo_valido(correo: str) -> bool:
    return bool(_RE_EMAIL.match(correo or "")) and len(correo) <= 254


def telefono_valido(telefono: str) -> bool:
    """El teléfono es opcional; si viene, debe tener un formato razonable."""
    return not telefono or bool(_RE_TELEFONO.match(telefono))


def destino_seguro(destino, por_defecto=None):
    """Solo acepta rutas internas ('/algo'); evita open redirect con //host, http://… o \\."""
    if not destino or not destino.startswith("/") or destino.startswith("//") or "\\" in destino:
        return por_defecto
    partes = urlparse(destino)
    if partes.scheme or partes.netloc:
        return por_defecto
    return destino


# ---------- Errores ----------

def mensaje_error(error, generico="No se pudo completar la operación. Inténtalo de nuevo."):
    """Convierte una excepción de Supabase/Postgres en un mensaje entendible.
    El detalle técnico va al log, nunca a la pantalla del usuario."""
    log.warning("Error de Supabase: %r", error)
    texto = str(getattr(error, "message", "") or error)
    codigo = str(getattr(error, "code", "") or "")
    bajo = texto.lower()

    # Mensajes escritos a propósito en los triggers de schema.sql ("SB: ...")
    if "SB: " in texto:
        return texto.split("SB: ", 1)[1].strip().strip("'\"}").rstrip()
    if codigo == "23P01" or "sin_cruces_horario" in bajo:
        return "Ese horario acaba de ser ocupado por otra reserva. Elige otro."
    if codigo == "23505" or "already registered" in bajo or "already been registered" in bajo:
        return "Ya existe un registro con esos datos."
    if codigo == "42501" or "row-level security" in bajo:
        return "No tienes permiso para realizar esta acción."
    if "email not confirmed" in bajo:
        return "Debes confirmar tu correo antes de iniciar sesión."
    if "rate limit" in bajo or "too many" in bajo:
        return "Demasiados intentos. Espera unos minutos e inténtalo de nuevo."
    if "password" in bajo and "at least" in bajo:
        return "La contraseña es demasiado corta."
    return generico
