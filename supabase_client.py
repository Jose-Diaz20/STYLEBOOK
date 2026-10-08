"""
Clientes de Supabase.

IMPORTANTE (causa de varios errores del proyecto):
  · El cliente compartido `sb` es SOLO para lecturas públicas (anónimo). Nunca se usa para
    iniciar sesión: si se hace, la librería le cambia la cabecera Authorization al token de
    ese usuario y TODAS las consultas públicas de TODOS los visitantes pasan a ejecutarse
    como esa persona, hasta que el token vence (~1 h) y entonces todo responde 500.
  · Ningún cliente refresca tokens por su cuenta (auto_refresh_token=False): Supabase rota el
    refresh token en cada uso, y un refresco en segundo plano invalida el que guarda la sesión
    de Flask, lo que termina cerrando la sesión del usuario.
"""
import os

from dotenv import load_dotenv
from supabase import create_client, Client
from supabase.lib.client_options import ClientOptions

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise RuntimeError(
        "Faltan SUPABASE_URL o SUPABASE_ANON_KEY. "
        "Copia .env.example como .env y completa tus credenciales."
    )


def _opciones() -> ClientOptions:
    return ClientOptions(auto_refresh_token=False, persist_session=False)


def cliente_anonimo() -> Client:
    """Cliente nuevo y aislado (anónimo). Se usa para registro, login y renovar tokens."""
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=_opciones())


# Cliente compartido: solo lecturas públicas. No iniciar sesión con este objeto.
sb: Client = cliente_anonimo()


def sb_como_usuario(access_token: str, refresh_token: str = None) -> Client:
    """
    Cliente que envía el JWT del usuario a PostgREST, para que las políticas RLS (auth.uid())
    se apliquen como ese usuario. No hace llamadas de red ni refresca nada: la renovación del
    token la hace `utilidades.cliente_sesion()` y guarda el resultado en la sesión de Flask.
    """
    cliente = cliente_anonimo()
    cliente.postgrest.auth(access_token)
    return cliente


def renovar_sesion(refresh_token: str):
    """Canjea un refresh token por una sesión nueva (access + refresh)."""
    return cliente_anonimo().auth.refresh_session(refresh_token)
