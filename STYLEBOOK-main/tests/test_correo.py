"""Recordatorio por correo: contenido del mensaje y manejo de fallos (sin red ni Supabase)."""
from enviar_recordatorios import armar_mensaje, enviar_pendientes, texto_fecha

FILA = {"id_cita": "c1", "clave_aviso": "2026-10-08 09:00", "correo": "ana@x.co", "nombre_cliente": "Ana",
        "nombre_servicio": "Corte", "nombre_profesional": "Barbería Central", "dia": "2026-10-08", "hora": "09:00:00"}


def test_el_correo_va_al_correo_de_inicio_de_sesion_con_los_cuatro_datos():
    m = armar_mensaje(FILA, "StyleBook <a@b.co>")
    cuerpo = m.get_content()
    assert m["To"] == "ana@x.co"
    assert "Corte" in cuerpo and "Barbería Central" in cuerpo
    assert "jueves 08/10/2026" in cuerpo and "09:00" in cuerpo and "09:00:00" not in cuerpo
    assert "Corte" in m["Subject"] and "09:00" in m["Subject"]


def test_texto_fecha():
    assert texto_fecha("2026-10-08") == "jueves 08/10/2026"


def test_un_fallo_no_detiene_a_los_demas_y_solo_se_registran_los_enviados():
    otra = dict(FILA, id_cita="c2", correo="mal")
    enviados, registrados = [], []

    def enviar(f):
        if f["correo"] == "mal":
            raise RuntimeError("rechazado")
        enviados.append(f["id_cita"])

    ok, mal = enviar_pendientes([otra, FILA], enviar, lambda f: registrados.append(f["id_cita"]))
    assert (ok, mal) == (1, 1) and enviados == ["c1"] and registrados == ["c1"]
