"""
Envía por correo el recordatorio de las citas confirmadas que empiezan en los próximos días.
Va al correo con el que el cliente inicia sesión. Pensado para correrse una vez al día
(cron, tarea programada del hosting, GitHub Actions…):

    python enviar_recordatorios.py            # envía
    python enviar_recordatorios.py --simular  # solo muestra a quién le escribiría

Variables de entorno (.env):
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY   (la clave service_role; NUNCA la pongas en la web ni en git)
    SMTP_HOST, SMTP_PORT (587 por defecto; 465 usa SSL), SMTP_USER, SMTP_PASSWORD, SMTP_FROM
    RECORDATORIO_DIAS                         (días de antelación; 2 por defecto)
"""
import logging
import os
import smtplib
import sys
from datetime import date
from email.message import EmailMessage

from dotenv import load_dotenv

log = logging.getLogger("stylebook.recordatorios")

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def texto_fecha(dia):
    """'2026-10-08' → 'jueves 08/10/2026'."""
    d = date.fromisoformat(str(dia)[:10])
    return f"{DIAS[d.weekday()]} {d:%d/%m/%Y}"


def armar_mensaje(fila, remitente):
    """Correo de recordatorio con servicio, profesional, fecha y hora."""
    hora = str(fila["hora"])[:5]
    fecha = texto_fecha(fila["dia"])
    nombre = (fila.get("nombre_cliente") or "").strip() or "cliente"
    msg = EmailMessage()
    msg["From"] = remitente
    msg["To"] = fila["correo"]
    msg["Subject"] = f"Recordatorio de tu cita: {fila['nombre_servicio']} el {fecha} a las {hora}"
    msg.set_content(
        f"Hola {nombre},\n\n"
        f"Te recordamos tu cita confirmada en StyleBook:\n\n"
        f"  Servicio:     {fila['nombre_servicio']}\n"
        f"  Profesional:  {fila['nombre_profesional']}\n"
        f"  Fecha:        {fecha}\n"
        f"  Hora:         {hora}\n\n"
        f"Si no puedes asistir, cancela o reprograma desde \"Mis citas\" para liberar el horario.\n\n"
        f"— StyleBook\n"
    )
    return msg


def enviar_pendientes(filas, enviar, registrar):
    """Envía un correo por fila y, solo si salió bien, lo registra. Un fallo no detiene a los demás.
    Devuelve (enviados, fallidos)."""
    enviados = fallidos = 0
    for fila in filas:
        try:
            enviar(fila)
        except Exception as error:
            fallidos += 1
            log.warning("No se pudo enviar el recordatorio de la cita %s: %r", fila.get("id_cita"), error)
            continue
        enviados += 1
        try:
            registrar(fila)
        except Exception as error:   # el correo ya salió: se avisa para revisar, pero no se reenvía a mano
            log.error("Correo enviado pero NO registrado (cita %s): %r — puede repetirse.", fila.get("id_cita"), error)
    return enviados, fallidos


def _conectar_smtp():
    host = os.environ["SMTP_HOST"]
    puerto = int(os.environ.get("SMTP_PORT", "587"))
    if puerto == 465:
        servidor = smtplib.SMTP_SSL(host, puerto, timeout=30)
    else:
        servidor = smtplib.SMTP(host, puerto, timeout=30)
        servidor.starttls()
    usuario = os.environ.get("SMTP_USER")
    if usuario:
        servidor.login(usuario, os.environ["SMTP_PASSWORD"])
    return servidor


def main(simular=False):
    load_dotenv()
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    dias = int(os.environ.get("RECORDATORIO_DIAS", "2"))
    filas = sb.rpc("citas_para_recordar", {"p_dias": dias}).execute().data or []
    log.info("%d recordatorio(s) por enviar (citas en los próximos %d días).", len(filas), dias)
    if not filas:
        return 0

    registrar = lambda f: sb.table("recordatorios_correo").insert(
        {"cita_id": f["id_cita"], "clave": f["clave_aviso"]}).execute()

    if simular:
        for f in filas:
            log.info("[simulación] %s ← %s el %s %s", f["correo"], f["nombre_servicio"], f["dia"], str(f["hora"])[:5])
        return 0

    remitente = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or "StyleBook <no-reply@stylebook.local>"
    with _conectar_smtp() as servidor:
        enviados, fallidos = enviar_pendientes(
            filas, lambda f: servidor.send_message(armar_mensaje(f, remitente)), registrar)
    log.info("Enviados: %d · fallidos: %d", enviados, fallidos)
    return 1 if fallidos else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    sys.exit(main(simular="--simular" in sys.argv))
