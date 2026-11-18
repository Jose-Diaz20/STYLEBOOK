# StyleBook

Aplicación web en Flask + Supabase para reservar citas en salones de belleza, barberías y con profesionales independientes.

## Tipos de cuenta (RF-01, RN-02)

| Tipo | Qué hace |
|---|---|
| **Cliente** | Consulta servicios y proveedores, reserva, cancela y reprograma sus citas. |
| **Establecimiento** | Salón o barbería: registra su negocio (nombre, ubicación, contacto), servicios, horario y atiende su agenda. |
| **Profesional independiente** | Igual que el establecimiento, pero a título personal. |
| *Administrador* | Interno (no se elige al registrarse): aprueba o rechaza proveedores. Se asigna desde el SQL Editor de Supabase. |

> **Modelo actual:** cada establecimiento o profesional independiente es *un proveedor con una agenda propia*
> (tabla `profesionales`, columna `tipo_proveedor`). Un establecimiento con varios profesionales, cada uno con su
> propia agenda, queda para un sprint posterior.

## Puesta en marcha

1. **Entorno:** `python -m venv venv`, activarlo, y `pip install -r requirements.txt`.
2. **Variables:** copia `.env.example` a `.env` y completa:
   ```env
   SUPABASE_URL=https://TU-PROYECTO.supabase.co
   SUPABASE_ANON_KEY=tu_clave_anon_publica
   FLASK_SECRET_KEY=una_cadena_larga_y_aleatoria
   SESSION_COOKIE_SECURE=0   # 1 cuando publiques con HTTPS
   ```
3. **Base de datos:** pega **`db/schema.sql`** completo en Supabase → SQL Editor → Run (**hay que volver a correrlo**: agrega la tabla `notificaciones` y el aviso automático de citas).
   Si alguna cuenta ve el menú o los permisos de otro tipo, corre **`db/reparar_cuentas.sql`** (diagnóstico y reparación de perfiles).
   Es un único script, ordenado e idempotente: sirve para un proyecto nuevo y también migra uno que ya corrió
   los scripts anteriores (`schema.sql` viejo + `schema_citas.sql`, que ya no existe).
4. **Primer administrador:** regístrate desde la app y luego, en el SQL Editor:
   `update public.perfiles set rol = 'admin' where id = (select id from auth.users where email = 'tu@correo');`
5. **Recordatorios por correo** (`enviar_recordatorios.py`): avisa por correo, al email con el que el cliente inicia sesión,
   de sus citas confirmadas que empiezan en los próximos días. Supabase solo envía correos de autenticación, así que este
   usa tu propio SMTP (Gmail con contraseña de aplicación, Brevo, Resend, SendGrid…). Agrega al `.env` **del servidor**:
   ```env
   SUPABASE_SERVICE_ROLE_KEY=...   # clave service_role (Settings → API). Secreta: nunca en la web ni en git
   SMTP_HOST=smtp.tu-proveedor.com
   SMTP_PORT=587                   # 465 usa SSL
   SMTP_USER=...
   SMTP_PASSWORD=...
   SMTP_FROM=StyleBook <avisos@tu-dominio.com>
   RECORDATORIO_DIAS=2             # días de antelación (opcional, 2 por defecto)
   ```
   Pruébalo con `python enviar_recordatorios.py --simular` (solo lista) y prográmalo **una vez al día**, p. ej. con cron
   `0 8 * * * cd /ruta/STYLEBOOK && python enviar_recordatorios.py` o la tarea programada de tu hosting. Cada cita se avisa
   una sola vez por fecha/hora (si se reprograma, se avisa de nuevo).
6. **Ejecutar:** `python app.py` (desarrollo) o `gunicorn -w 4 -b 0.0.0.0:5000 app:app` (producción).

## Pruebas

```bash
pip install pytest && python -m pytest tests -q          # flujos de la app (Supabase simulada)
npm i @electric-sql/pglite && node tests/test_sql.mjs    # esquema SQL contra Postgres real: triggers, RLS, anti-cruce
```

Las pruebas de la app usan una Supabase simulada (no ejercitan RLS); las de SQL usan Postgres real pero no el servicio
de Auth de Supabase. Falta una pasada manual contra tu proyecto real de Supabase.

## Estructura

```
app.py                  arranque, CSRF y páginas de error
supabase_client.py      cliente Supabase (anónimo y como usuario)
enviar_recordatorios.py recordatorios por correo (SMTP), se programa aparte
utilidades.py           roles, validaciones, redirección segura, mensajes de error
disponibilidad.py       franjas libres, fechas válidas, zona horaria America/Bogota
blueprints/             auth · perfil · profesionales · servicios · horarios · citas · notificaciones · admin
templates/  static/     vistas Jinja y estilos
db/schema.sql           esquema completo (tablas, funciones, triggers, RLS)
tests/                  pruebas (pytest y node)
```

## Trazabilidad: requisitos → código

| Requisito | Dónde se cumple |
|---|---|
| RF-01, RN-02 tipos de cuenta | `blueprints/auth.py` (registro), `perfiles.rol` + `crear_perfil()` en `schema.sql` |
| RN-01 correo único | Supabase Auth (el mensaje "ya registrado" se traduce en `utilidades.mensaje_error`) |
| RF-02 inicio de sesión | `blueprints/auth.py` (`login`, `_destino_inicial`) |
| RN-03 acceso según rol | `utilidades.exigir_rol` (app) + RLS y `proteger_perfil()` (base) |
| RF-03 gestión del perfil | `blueprints/perfil.py`, `profesionales.editar_negocio` |
| RF-04, RN-19 datos del proveedor | `blueprints/profesionales.py` (`registro`, `editar_negocio`), `blueprints/horarios.py` |
| RF-05, RN-05/06/07 servicios | `blueprints/servicios.py` (se desactivan, no se borran) |
| RF-06 consultar servicios | `servicios.catalogo` (solo activos de proveedores aprobados) |
| RF-07 consultar proveedor | `profesionales.detalle` (servicios, precios, horario, ubicación, disponibilidad) |
| RN-04 datos obligatorios y válidos | validaciones en cada formulario + `utilidades.py` |
| RN-08 horario de atención | `disponibilidad.generar_franjas_libres` + `validar_cita()` |
| RN-09 solo horas disponibles | `disponibilidad.franjas_por_dia` + función SQL `rangos_ocupados()` |
| RN-10 no duplicidad | restricción `sin_cruces_horario` en `schema.sql` |
| RN-11, RN-12 profesional–servicio–cliente | `validar_cita()` y RLS de `citas` |
| RN-13 estados de la cita | `citas_estado_check` + transiciones en `validar_cita()`; `citas.agenda_estado` |
| RN-14 confirmar/rechazar y avisar | la cita nace `pendiente`; el proveedor confirma o rechaza en `citas.agenda`; `notificar_cita()` (schema.sql) crea los avisos (acuse, confirmación con servicio, profesional, fecha y hora) y `blueprints/notificaciones.py` los muestra |
| Recordatorio de cita (correo) | `citas_para_recordar()` + `recordatorios_correo` (schema.sql, sección 8) y `enviar_recordatorios.py` (SMTP, días antes, una vez por fecha/hora) |
| Recordatorio de cita (en la app) | `generar_recordatorios()` (schema.sql, 24 h antes); lo ejecuta pg_cron y, de respaldo, `notificaciones.generar_recordatorios` al abrir la app |

## Pendiente para próximos sprints

Avisos por WhatsApp y correo de confirmación/cancelación (hoy solo el recordatorio sale por correo), RN-15 (anticipación mínima para cancelar),
RN-16 (calificaciones), RN-17 (festivos y días de cierre), RN-18 (política de datos personales) y el modelo de
establecimiento con varios profesionales.

## Sesión con Supabase (importante)

- El cliente compartido `sb` (`supabase_client.py`) es **solo para lecturas públicas**. Nunca se inicia sesión con él:
  la librería le cambiaría el token a todas las consultas de todos los visitantes. Login y registro usan `cliente_anonimo()`.
- Los tokens los renueva `utilidades.cliente_sesion()` cuando faltan menos de 60 s y guarda los nuevos en la sesión de Flask.
  Si no se pueden renovar, se vuelve al login en vez de mostrar un error 500.
- El rol se lee de `perfiles` al iniciar sesión; si no se puede leer, no se inicia sesión (ya no se asume "cliente").
