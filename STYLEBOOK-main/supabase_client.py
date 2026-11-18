
"""
Clientes de Supabase.

IMPORTANTE:
  - El cliente compartido sb es SOLO para lecturas públicas.
  - No iniciar sesión con el cliente compartido.
  - Ningún cliente refresca tokens por su cuenta.
"""

import os

from dotenv import load_dotenv
from supabase import create_client, Client
from supabase.client import ClientOptions

# INICIO AGREGADO JESUS: cliente independiente de Storage.
from storage3 import SyncStorageClient
# FIN AGREGADO JESUS: cliente independiente de Storage.

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    raise RuntimeError(
        "Faltan SUPABASE_URL o SUPABASE_ANON_KEY. "
        "Copia .env.example como .env y completa tus credenciales."
    )


def _opciones() -> ClientOptions:
    return ClientOptions(
        auto_refresh_token=False,
        persist_session=False
    )


def cliente_anonimo() -> Client:
    """Cliente nuevo y aislado (anónimo)."""
    return create_client(
        SUPABASE_URL,
        SUPABASE_ANON_KEY,
        options=_opciones()
    )


# Cliente compartido: solo lecturas públicas.
sb: Client = cliente_anonimo()


def sb_como_usuario(access_token: str, refresh_token: str = None) -> Client:
    """
    Cliente que envía el JWT del usuario a PostgREST.
    Las políticas RLS se aplican como ese usuario.
    """
    cliente = cliente_anonimo()
    cliente.postgrest.auth(access_token)
    return cliente


# INICIO AGREGADO JESUS: cliente Storage autenticado con el JWT del profesional.

def storage_como_usuario(access_token: str):
    """
    Crea un cliente independiente de Storage autenticado
    con el JWT del profesional.
    """

    if not access_token:
        raise ValueError("No se recibió el token de autenticación.")

    return SyncStorageClient(
        f"{SUPABASE_URL.rstrip('/')}/storage/v1",
        {
            "apiKey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {access_token}"
        }
    )

# FIN AGREGADO JESUS: cliente Storage autenticado con el JWT del profesional.


def renovar_sesion(refresh_token: str):
    """Canjea un refresh token por una sesión nueva."""
    return cliente_anonimo().auth.refresh_session(refresh_token)
