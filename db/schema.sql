-- ============================================================
-- StyleBook · Esquema COMPLETO del Sprint 1 (script único)
--
-- Cómo usarlo: pegar completo en Supabase → SQL Editor → Run.
-- Es idempotente: sirve tanto para un proyecto nuevo como para
-- uno que ya corrió los scripts anteriores (schema.sql viejo +
-- schema_citas.sql, que ya no existe). Puedes ejecutarlo varias veces.
--
-- Orden: 1 extensiones · 2 tablas · 3 funciones · 4 triggers
--        5 RLS y políticas · 6 permisos
--
-- Trazabilidad (RF/RN → dónde se aplica):
--   RF-01/RN-02  tipos de cuenta ........ perfiles.rol, crear_perfil()
--   RN-03        acceso según rol ....... RLS + proteger_perfil()
--   RF-04        datos del proveedor .... profesionales (nombre_negocio, ubicacion…)
--   RF-05/RN-05  servicios .............. servicios.activo (se desactiva, no se borra)
--   RN-08        horario de atención .... horarios_profesional + validar_cita()
--   RN-09/RN-10  disponibilidad/no cruce  rangos_ocupados() + sin_cruces_horario
--   RN-11/RN-12  cita ↔ servicio/cliente  validar_cita()
--   RN-13        estados de la cita ..... citas_estado_check + validar_cita()
--   RN-14        confirmar/rechazar ..... la cita nace 'pendiente'; notificar_cita() avisa a ambas partes
-- ============================================================

-- ---------- 1. EXTENSIONES ----------
create extension if not exists btree_gist;

-- ---------- 2. TABLAS ----------

-- 2.1 PERFILES: todo usuario (cliente, establecimiento, profesional o admin)
create table if not exists public.perfiles (
  id         uuid primary key references auth.users(id) on delete cascade,
  nombre     text not null,
  telefono   text,
  rol        text not null default 'cliente',
  creado_en  timestamptz not null default now()
);
-- RN-02: tipos de cuenta. 'admin' es interno y solo se asigna desde el SQL Editor.
alter table public.perfiles drop constraint if exists perfiles_rol_check;
alter table public.perfiles add constraint perfiles_rol_check
  check (rol in ('cliente', 'establecimiento', 'profesional', 'admin'));

-- 2.2 PROFESIONALES: proveedores con agenda propia (establecimiento o independiente)
create table if not exists public.profesionales (
  id                uuid primary key default gen_random_uuid(),
  perfil_id         uuid not null unique references public.perfiles(id) on delete cascade,
  especialidad      text not null,
  descripcion       text,
  telefono          text,
  anios_experiencia int default 0,
  foto_url          text,
  estado            text not null default 'pendiente',
  creado_en         timestamptz not null default now()
);
alter table public.profesionales add column if not exists tipo_proveedor text not null default 'independiente';
alter table public.profesionales add column if not exists nombre_negocio text;
alter table public.profesionales add column if not exists ubicacion text;

-- Proyectos que ya tenían filas: el nombre del negocio arranca con el nombre del perfil.
update public.profesionales p
   set nombre_negocio = coalesce((select nombre from public.perfiles where id = p.perfil_id), 'Sin nombre')
 where nombre_negocio is null;
alter table public.profesionales alter column nombre_negocio set not null;

alter table public.profesionales drop constraint if exists profesionales_estado_check;
alter table public.profesionales add constraint profesionales_estado_check
  check (estado in ('pendiente', 'aprobado', 'rechazado'));
alter table public.profesionales drop constraint if exists profesionales_tipo_proveedor_check;
alter table public.profesionales add constraint profesionales_tipo_proveedor_check
  check (tipo_proveedor in ('establecimiento', 'independiente'));

-- 2.3 SERVICIOS (RN-05/06/07: precio y duración obligatorios; se desactivan, no se borran)
create table if not exists public.servicios (
  id             uuid primary key default gen_random_uuid(),
  profesional_id uuid not null references public.profesionales(id) on delete cascade,
  nombre         text not null,
  categoria      text not null default 'general',
  descripcion    text,
  precio         numeric(12,2) not null check (precio >= 0),
  duracion_min   int not null default 30 check (duracion_min between 10 and 480),
  activo         boolean not null default true,
  creado_en      timestamptz not null default now()
);

-- 2.4 HORARIOS de atención (RN-08). dia_semana: 0=Lunes … 6=Domingo
create table if not exists public.horarios_profesional (
  id             uuid primary key default gen_random_uuid(),
  profesional_id uuid not null references public.profesionales(id) on delete cascade,
  dia_semana     smallint not null check (dia_semana between 0 and 6),
  hora_inicio    time not null,
  hora_fin       time not null check (hora_fin > hora_inicio),
  creado_en      timestamptz not null default now()
);

-- 2.5 CITAS (RN-12/13). Estados: pendiente, confirmada, cancelada, completada
create table if not exists public.citas (
  id             uuid primary key default gen_random_uuid(),
  cliente_id     uuid not null references public.perfiles(id) on delete cascade,
  profesional_id uuid not null references public.profesionales(id) on delete cascade,
  servicio_id    uuid not null references public.servicios(id) on delete restrict,
  fecha          date not null,
  hora_inicio    time not null,
  hora_fin       time not null,
  estado         text not null default 'pendiente',
  creado_en      timestamptz not null default now()
);
-- RN-14: toda cita nace 'pendiente' hasta que el proveedor la confirma o la rechaza.
alter table public.citas alter column estado set default 'pendiente';
-- Nombre del cliente al momento de reservar: el proveedor lo ve en su agenda
-- sin tener que leer la tabla de perfiles (que es privada).
alter table public.citas add column if not exists cliente_nombre text;

alter table public.citas drop constraint if exists citas_estado_check;
alter table public.citas add constraint citas_estado_check
  check (estado in ('pendiente', 'confirmada', 'cancelada', 'completada'));
alter table public.citas drop constraint if exists citas_hora_fin_check;
alter table public.citas add constraint citas_hora_fin_check check (hora_fin > hora_inicio);

-- Antes el borrado de un servicio arrastraba (cascade) todas sus citas.
alter table public.citas drop constraint if exists citas_servicio_id_fkey;
alter table public.citas add constraint citas_servicio_id_fkey
  foreign key (servicio_id) references public.servicios(id) on delete restrict;

-- RN-10: un proveedor no puede tener dos citas activas que se superpongan.
alter table public.citas drop constraint if exists sin_cruces_horario;
alter table public.citas add constraint sin_cruces_horario
  exclude using gist (
    profesional_id with =,
    tsrange((fecha + hora_inicio)::timestamp, (fecha + hora_fin)::timestamp, '[)') with &&
  ) where (estado in ('pendiente', 'confirmada'));

-- 2.6 NOTIFICACIONES (RN-14): avisos dentro de la app. Las crea el trigger notificar_cita();
-- cada persona solo lee las suyas y solo puede marcarlas como leídas.
create table if not exists public.notificaciones (
  id          uuid primary key default gen_random_uuid(),
  usuario_id  uuid not null references public.perfiles(id) on delete cascade,
  cita_id     uuid references public.citas(id) on delete cascade,
  tipo        text not null,
  mensaje     text not null,
  leida       boolean not null default false,
  creado_en   timestamptz not null default now()
);
create index if not exists idx_notificaciones_usuario on public.notificaciones(usuario_id, leida, creado_en desc);
-- `clave` evita repetir un aviso (p. ej. el recordatorio de una misma fecha y hora de cita).
alter table public.notificaciones add column if not exists clave text;
create unique index if not exists uq_notificaciones_clave on public.notificaciones(cita_id, tipo, clave) where clave is not null;

create index if not exists idx_servicios_profesional     on public.servicios(profesional_id);
create index if not exists idx_profesionales_especialidad on public.profesionales(especialidad);
create index if not exists idx_horarios_profesional      on public.horarios_profesional(profesional_id, dia_semana);
create index if not exists idx_citas_profesional_fecha   on public.citas(profesional_id, fecha);
create index if not exists idx_citas_cliente             on public.citas(cliente_id);

-- ---------- 3. FUNCIONES ----------

-- ¿El usuario actual es admin? (security definer: evita recursión con la RLS de perfiles)
create or replace function public.es_admin()
returns boolean
language sql stable security definer
set search_path = public
as $$
  select exists (select 1 from public.perfiles where id = auth.uid() and rol = 'admin');
$$;

-- Crea el perfil al registrarse (RF-01). Lee nombre, teléfono y tipo de cuenta que la app
-- manda en sign_up, así funciona igual con o sin confirmación de correo.
-- 'admin' JAMÁS se puede elegir desde el registro.
create or replace function public.crear_perfil()
returns trigger
language plpgsql security definer
set search_path = public
as $$
declare
  v_tipo text := new.raw_user_meta_data->>'tipo_cuenta';
begin
  insert into public.perfiles (id, nombre, telefono, rol)
  values (
    new.id,
    coalesce(nullif(trim(new.raw_user_meta_data->>'nombre'), ''), 'Usuario'),
    nullif(trim(new.raw_user_meta_data->>'telefono'), ''),
    case when v_tipo in ('establecimiento', 'profesional') then v_tipo else 'cliente' end
  );
  return new;
end;
$$;

-- Franjas ocupadas de un proveedor, SIN datos de clientes (RN-09/RN-10).
-- Es security definer para que cualquier visitante pueda calcular disponibilidad real
-- aunque la RLS de citas solo le deje ver las suyas.
create or replace function public.rangos_ocupados(
  p_profesional uuid,
  p_desde       date,
  p_hasta       date,
  p_excluir     uuid default null
)
returns table (fecha date, hora_inicio time, hora_fin time)
language sql stable security definer
set search_path = public
as $$
  select c.fecha, c.hora_inicio, c.hora_fin
    from public.citas c
   where c.profesional_id = p_profesional
     and c.fecha between p_desde and p_hasta
     and c.estado in ('pendiente', 'confirmada')
     and (p_excluir is null or c.id <> p_excluir);
$$;

-- Avisos de una cita (RN-14). Quién recibe qué:
--   nueva solicitud ............ el proveedor (y el cliente recibe el acuse de que quedó registrada)
--   confirmada / rechazada ..... el cliente
--   cancelada por el cliente ... el proveedor;  cancelada por el proveedor ... el cliente
--   completada ................. el cliente
--   reprogramada por el cliente  el proveedor
create or replace function public.notificar_cita()
returns trigger
language plpgsql security definer
set search_path = public
as $$
declare
  v_uid      uuid := auth.uid();
  v_dueno    uuid;
  v_negocio  text;
  v_servicio text;
  v_cuando   text;
begin
  select p.perfil_id, p.nombre_negocio into v_dueno, v_negocio
    from public.profesionales p where p.id = new.profesional_id;
  select s.nombre into v_servicio from public.servicios s where s.id = new.servicio_id;
  v_cuando := to_char(new.fecha, 'DD/MM/YYYY') || ' a las ' || to_char(new.hora_inicio, 'HH24:MI');

  if tg_op = 'INSERT' then
    if new.estado = 'pendiente' then
      insert into public.notificaciones (usuario_id, cita_id, tipo, mensaje) values (
        v_dueno, new.id, 'nueva_solicitud',
        'Nueva solicitud de ' || coalesce(new.cliente_nombre, 'un cliente') || ': ' || v_servicio
        || ' el ' || v_cuando || '. Confírmala o recházala desde Mi agenda.');
      -- el cliente sabe de inmediato que su solicitud quedó registrada
      insert into public.notificaciones (usuario_id, cita_id, tipo, mensaje) values (
        new.cliente_id, new.id, 'solicitud_enviada',
        'Recibimos tu solicitud de ' || v_servicio || ' con ' || v_negocio || ' para el ' || v_cuando
        || '. Queda pendiente hasta que la confirmen.');
    end if;

  elsif new.estado is distinct from old.estado then
    if new.estado = 'confirmada' then
      insert into public.notificaciones (usuario_id, cita_id, tipo, mensaje) values (
        new.cliente_id, new.id, 'cita_confirmada',
        'Tu cita fue confirmada: ' || v_servicio || ' con ' || v_negocio || ', el ' || v_cuando || '.');
    elsif new.estado = 'cancelada' then
      if v_uid is not null and v_uid = new.cliente_id then
        insert into public.notificaciones (usuario_id, cita_id, tipo, mensaje) values (
          v_dueno, new.id, 'cita_cancelada',
          coalesce(new.cliente_nombre, 'El cliente') || ' canceló la cita de ' || v_servicio || ' del ' || v_cuando || '.');
      elsif old.estado = 'pendiente' then
        insert into public.notificaciones (usuario_id, cita_id, tipo, mensaje) values (
          new.cliente_id, new.id, 'cita_rechazada',
          v_negocio || ' no pudo aceptar tu solicitud de ' || v_servicio || ' para el ' || v_cuando || '. Puedes elegir otro horario.');
      else
        insert into public.notificaciones (usuario_id, cita_id, tipo, mensaje) values (
          new.cliente_id, new.id, 'cita_cancelada',
          v_negocio || ' canceló tu cita de ' || v_servicio || ' del ' || v_cuando || '.');
      end if;
    elsif new.estado = 'completada' then
      insert into public.notificaciones (usuario_id, cita_id, tipo, mensaje) values (
        new.cliente_id, new.id, 'cita_completada',
        'Tu cita de ' || v_servicio || ' con ' || v_negocio || ' fue marcada como completada.');
    end if;

  elsif new.estado in ('pendiente', 'confirmada')
        and (new.fecha is distinct from old.fecha or new.hora_inicio is distinct from old.hora_inicio) then
    insert into public.notificaciones (usuario_id, cita_id, tipo, mensaje) values (
      v_dueno, new.id, 'cita_reprogramada',
      coalesce(new.cliente_nombre, 'El cliente') || ' reprogramó su cita de ' || v_servicio || ' para el ' || v_cuando || '.');
  end if;

  return new;
end;
$$;

-- Recordatorios (RN-14): avisa al cliente de sus citas CONFIRMADAS que empiezan dentro de `p_antelacion`
-- (24 h por defecto) y todavía no han empezado. Se avisa una sola vez por cada fecha/hora de la cita
-- (si se reprograma, se avisa de nuevo). No repite el aviso si la cita se confirmó hace menos de una hora.
-- Lo ejecuta pg_cron cada 15 min (sección 7) y, como respaldo, la app lo llama cuando el cliente abre
-- sus notificaciones. Con sesión iniciada solo procesa las citas de quien llama; sin sesión (cron o
-- SQL Editor) procesa todas. Devuelve cuántos recordatorios creó.
create or replace function public.generar_recordatorios(p_antelacion interval default interval '24 hours')
returns integer
language plpgsql security definer
set search_path = public
as $$
declare
  v_ahora timestamp := (now() at time zone 'America/Bogota');
  v_uid   uuid := auth.uid();
  v_total integer;
begin
  with nuevos as (
    insert into public.notificaciones (usuario_id, cita_id, tipo, mensaje, clave)
    select c.cliente_id, c.id, 'recordatorio_cita',
           'Recordatorio: tienes cita de ' || s.nombre || ' con ' || p.nombre_negocio
           || ' el ' || to_char(c.fecha, 'DD/MM/YYYY') || ' a las ' || to_char(c.hora_inicio, 'HH24:MI') || '.',
           to_char(c.fecha, 'YYYY-MM-DD') || ' ' || to_char(c.hora_inicio, 'HH24:MI')
      from public.citas c
      join public.profesionales p on p.id = c.profesional_id
      join public.servicios s on s.id = c.servicio_id
     where c.estado = 'confirmada'
       and (c.fecha + c.hora_inicio) >  v_ahora
       and (c.fecha + c.hora_inicio) <= v_ahora + p_antelacion
       and (v_uid is null or c.cliente_id = v_uid)
       and not exists (select 1 from public.notificaciones n
                        where n.cita_id = c.id and n.tipo = 'cita_confirmada'
                          and n.creado_en > now() - interval '1 hour')
    on conflict (cita_id, tipo, clave) where clave is not null do nothing
    returning 1
  )
  select count(*) into v_total from nuevos;
  return v_total;
end;
$$;

-- Una notificación solo se puede marcar como leída (no reescribir su contenido).
create or replace function public.proteger_notificacion()
returns trigger
language plpgsql security definer
set search_path = public
as $$
begin
  if auth.uid() is not null and (new.usuario_id, new.cita_id, new.tipo, new.mensaje, new.creado_en)
     is distinct from (old.usuario_id, old.cita_id, old.tipo, old.mensaje, old.creado_en) then
    raise exception 'SB: Solo puedes marcar una notificación como leída.';
  end if;
  return new;
end;
$$;

-- ---------- 4. TRIGGERS (reglas que la base garantiza aunque alguien salte la app) ----------

-- 4.0 El perfil se crea solo al registrarse (RF-01)
drop trigger if exists al_crear_usuario on auth.users;
create trigger al_crear_usuario
  after insert on auth.users
  for each row execute function public.crear_perfil();

-- 4.1 Nadie cambia su propio rol (evita volverse admin). Desde el SQL Editor (auth.uid() nulo) sí se puede.
create or replace function public.proteger_perfil()
returns trigger
language plpgsql security definer
set search_path = public
as $$
begin
  if auth.uid() is not null and new.rol is distinct from old.rol then
    raise exception 'SB: No puedes cambiar el tipo de cuenta.';
  end if;
  return new;
end;
$$;

drop trigger if exists proteger_perfil_trg on public.perfiles;
create trigger proteger_perfil_trg
  before update on public.perfiles
  for each row execute function public.proteger_perfil();

-- 4.2 Solo el admin aprueba o rechaza proveedores; todo alta nace 'pendiente'.
create or replace function public.proteger_profesional()
returns trigger
language plpgsql security definer
set search_path = public
as $$
begin
  if auth.uid() is not null and not public.es_admin() then
    if tg_op = 'INSERT' then
      new.estado := 'pendiente';
    else
      if new.estado is distinct from old.estado then
        raise exception 'SB: Solo un administrador puede aprobar o rechazar proveedores.';
      end if;
      if new.perfil_id is distinct from old.perfil_id then
        raise exception 'SB: No se puede cambiar el dueño del negocio.';
      end if;
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists proteger_profesional_trg on public.profesionales;
create trigger proteger_profesional_trg
  before insert or update on public.profesionales
  for each row execute function public.proteger_profesional();

-- 4.3 Validación de citas: RN-08, RN-09, RN-11, RN-12, RN-13 (y no reservar en el pasado).
create or replace function public.validar_cita()
returns trigger
language plpgsql security definer
set search_path = public
as $$
declare
  v_ahora    timestamp := (now() at time zone 'America/Bogota');
  v_uid      uuid := auth.uid();
  v_duracion int;
  v_inicio   timestamp;
  v_horario_ok boolean;
begin
  if tg_op = 'UPDATE' then
    if new.cliente_id is distinct from old.cliente_id
       or new.profesional_id is distinct from old.profesional_id
       or new.servicio_id is distinct from old.servicio_id then
      raise exception 'SB: No se puede cambiar el cliente, el proveedor ni el servicio de una cita.';
    end if;
  end if;

  -- Transiciones de estado permitidas (RN-13)
  if tg_op = 'INSERT' then
    if new.estado not in ('pendiente', 'confirmada') then
      raise exception 'SB: Una cita nueva solo puede quedar pendiente o confirmada.';
    end if;
  elsif new.estado is distinct from old.estado then
    if not (
      (old.estado = 'pendiente'  and new.estado in ('confirmada', 'cancelada')) or
      (old.estado = 'confirmada' and new.estado in ('completada', 'cancelada'))
    ) then
      raise exception 'SB: Cambio de estado no permitido (% → %).', old.estado, new.estado;
    end if;
    -- El cliente solo puede cancelar; confirmar/completar es del proveedor.
    if v_uid is not null and v_uid = old.cliente_id and new.estado <> 'cancelada' then
      raise exception 'SB: Solo puedes cancelar tu cita.';
    end if;
    if new.estado = 'completada' and (new.fecha + new.hora_inicio) > v_ahora then
      raise exception 'SB: No se puede completar una cita que aún no ha empezado.';
    end if;
  end if;

  -- Las validaciones de horario aplican al crear o al mover la cita (no al cancelar/completar).
  if tg_op = 'INSERT'
     or (new.estado in ('pendiente', 'confirmada')
         and (new.fecha is distinct from old.fecha
              or new.hora_inicio is distinct from old.hora_inicio
              or new.hora_fin is distinct from old.hora_fin)) then

    if not exists (select 1 from public.profesionales
                    where id = new.profesional_id and estado = 'aprobado') then
      raise exception 'SB: Este proveedor no está disponible para reservas.';
    end if;

    select s.duracion_min into v_duracion
      from public.servicios s
     where s.id = new.servicio_id and s.profesional_id = new.profesional_id and s.activo;
    if not found then
      raise exception 'SB: El servicio no existe, está inactivo o no lo presta este proveedor.';
    end if;

    if new.hora_fin <> new.hora_inicio + make_interval(mins => v_duracion) then
      raise exception 'SB: La duración de la cita no coincide con la del servicio.';
    end if;

    v_inicio := new.fecha + new.hora_inicio;
    if v_inicio < v_ahora then
      raise exception 'SB: No se pueden agendar citas en fechas u horas pasadas.';
    end if;

    select exists (
      select 1 from public.horarios_profesional h
       where h.profesional_id = new.profesional_id
         and h.dia_semana = extract(isodow from new.fecha)::int - 1
         and h.hora_inicio <= new.hora_inicio
         and h.hora_fin >= new.hora_fin
    ) into v_horario_ok;
    if not v_horario_ok then
      raise exception 'SB: Ese horario está fuera del horario de atención del proveedor.';
    end if;
  end if;

  return new;
end;
$$;

drop trigger if exists validar_cita_trg on public.citas;
create trigger validar_cita_trg
  before insert or update on public.citas
  for each row execute function public.validar_cita();

drop trigger if exists notificar_cita_trg on public.citas;
create trigger notificar_cita_trg
  after insert or update on public.citas
  for each row execute function public.notificar_cita();

drop trigger if exists proteger_notificacion_trg on public.notificaciones;
create trigger proteger_notificacion_trg
  before update on public.notificaciones
  for each row execute function public.proteger_notificacion();

-- ---------- 5. SEGURIDAD (Row Level Security) ----------
alter table public.perfiles              enable row level security;
alter table public.profesionales         enable row level security;
alter table public.servicios             enable row level security;
alter table public.horarios_profesional  enable row level security;
alter table public.citas                 enable row level security;
alter table public.notificaciones        enable row level security;

-- Se borran TODAS las políticas conocidas (viejas y nuevas) y se recrean limpias.
drop policy if exists "perfil propio lectura"          on public.perfiles;
drop policy if exists "perfil propio edicion"          on public.perfiles;
drop policy if exists "profesionales lectura"          on public.profesionales;
drop policy if exists "profesional alta propia"        on public.profesionales;
drop policy if exists "profesional edicion propia"     on public.profesionales;
drop policy if exists "admin gestiona profesionales"   on public.profesionales;
drop policy if exists "servicios lectura"              on public.servicios;
drop policy if exists "servicios alta propia"          on public.servicios;
drop policy if exists "servicios edicion propia"       on public.servicios;
drop policy if exists "servicios baja propia"          on public.servicios;
drop policy if exists "horarios lectura publica"       on public.horarios_profesional;
drop policy if exists "horarios gestion propia"        on public.horarios_profesional;
drop policy if exists "citas propias lectura cliente"  on public.citas;
drop policy if exists "citas propias lectura profesional" on public.citas;
drop policy if exists "citas edicion propia cliente"   on public.citas;
drop policy if exists "citas lectura propia"           on public.citas;
drop policy if exists "citas alta propia"              on public.citas;
drop policy if exists "citas cancelacion propia"       on public.citas;
drop policy if exists "notificaciones lectura propia"  on public.notificaciones;
drop policy if exists "notificaciones marcar leida"    on public.notificaciones;

-- Perfiles: cada quien ve y edita el suyo (el rol lo protege proteger_perfil)
create policy "perfil propio lectura" on public.perfiles
  for select using (auth.uid() = id);
create policy "perfil propio edicion" on public.perfiles
  for update using (auth.uid() = id) with check (auth.uid() = id);

-- Profesionales: el público solo ve los aprobados (RF-07); el dueño y el admin ven el suyo/todos
create policy "profesionales lectura" on public.profesionales
  for select using (estado = 'aprobado' or auth.uid() = perfil_id or public.es_admin());
create policy "profesional alta propia" on public.profesionales
  for insert with check (
    auth.uid() = perfil_id
    and exists (select 1 from public.perfiles p
                 where p.id = auth.uid() and p.rol in ('establecimiento', 'profesional'))
  );
create policy "profesional edicion propia" on public.profesionales
  for update using (auth.uid() = perfil_id) with check (auth.uid() = perfil_id);
create policy "admin gestiona profesionales" on public.profesionales
  for update using (public.es_admin()) with check (public.es_admin());

-- Servicios: el público ve solo servicios activos de proveedores aprobados (RN-05).
-- El dueño ve todos los suyos; el cliente sigue viendo los servicios de sus propias citas.
create policy "servicios lectura" on public.servicios
  for select using (
    (activo and exists (select 1 from public.profesionales p
                         where p.id = profesional_id and p.estado = 'aprobado'))
    or exists (select 1 from public.profesionales p
                where p.id = profesional_id and p.perfil_id = auth.uid())
    or exists (select 1 from public.citas c
                where c.servicio_id = servicios.id and c.cliente_id = auth.uid())
  );
create policy "servicios alta propia" on public.servicios
  for insert with check (
    exists (select 1 from public.profesionales p
             where p.id = profesional_id and p.perfil_id = auth.uid())
  );
create policy "servicios edicion propia" on public.servicios
  for update using (
    exists (select 1 from public.profesionales p
             where p.id = profesional_id and p.perfil_id = auth.uid())
  ) with check (
    exists (select 1 from public.profesionales p
             where p.id = profesional_id and p.perfil_id = auth.uid())
  );
-- Sin política de DELETE: los servicios se desactivan (activo = false), así no se pierde el historial.

-- Horarios: lectura pública (RF-07), gestión solo del dueño
create policy "horarios lectura publica" on public.horarios_profesional
  for select using (true);
create policy "horarios gestion propia" on public.horarios_profesional
  for all using (
    exists (select 1 from public.profesionales p
             where p.id = profesional_id and p.perfil_id = auth.uid())
  ) with check (
    exists (select 1 from public.profesionales p
             where p.id = profesional_id and p.perfil_id = auth.uid())
  );

-- Citas: el cliente ve las suyas; el proveedor, las de su agenda
create policy "citas lectura propia" on public.citas
  for select using (
    cliente_id = auth.uid()
    or exists (select 1 from public.profesionales p
                where p.id = profesional_id and p.perfil_id = auth.uid())
  );
create policy "citas alta propia" on public.citas
  for insert with check (
    cliente_id = auth.uid()
    and exists (select 1 from public.perfiles p where p.id = auth.uid() and p.rol = 'cliente')
  );
create policy "citas cancelacion propia" on public.citas
  for update using (
    cliente_id = auth.uid()
    or exists (select 1 from public.profesionales p
                where p.id = profesional_id and p.perfil_id = auth.uid())
  ) with check (
    cliente_id = auth.uid()
    or exists (select 1 from public.profesionales p
                where p.id = profesional_id and p.perfil_id = auth.uid())
  );

-- Notificaciones: cada quien ve y marca como leídas las suyas; nadie las inserta (lo hace el trigger)
create policy "notificaciones lectura propia" on public.notificaciones
  for select using (usuario_id = auth.uid());
create policy "notificaciones marcar leida" on public.notificaciones
  for update using (usuario_id = auth.uid()) with check (usuario_id = auth.uid());

-- ---------- 6. PERMISOS ----------
grant execute on function public.rangos_ocupados(uuid, date, date, uuid) to anon, authenticated;
-- es_admin() conserva su permiso por defecto: las políticas de profesionales la evalúan también para visitantes.

-- Solo usuarios con sesión pueden pedir sus recordatorios (los visitantes anónimos no).
revoke execute on function public.generar_recordatorios(interval) from public, anon;
grant execute on function public.generar_recordatorios(interval) to authenticated;

-- ---------- 7. RECORDATORIOS PROGRAMADOS (opcional) ----------
-- Si la extensión pg_cron está disponible (Supabase → Database → Extensions), los recordatorios salen
-- cada 15 minutos aunque nadie abra la app. Si no, la app los genera cuando el cliente la abre.
do $$
begin
  create extension if not exists pg_cron;
  perform cron.schedule('recordatorios-citas', '*/15 * * * *', 'select public.generar_recordatorios()');
exception when others then
  raise notice 'pg_cron no disponible (%): los recordatorios se generarán al abrir la app.', sqlerrm;
end
$$;

-- ---------- 8. RECORDATORIOS POR CORREO ----------
-- El envío lo hace `enviar_recordatorios.py` (SMTP) con la clave service_role, programado una vez al día.
-- Esta sección solo le dice qué citas avisar y deja constancia de lo ya enviado.

-- Constancia de cada correo enviado: una vez por fecha/hora de la cita (si se reprograma, se avisa de nuevo).
-- Sin políticas RLS: nadie con sesión de usuario la ve ni la modifica; solo service_role.
create table if not exists public.recordatorios_correo (
  cita_id    uuid not null references public.citas(id) on delete cascade,
  clave      text not null,
  enviado_en timestamptz not null default now(),
  primary key (cita_id, clave)
);
alter table public.recordatorios_correo enable row level security;

-- Citas CONFIRMADAS que empiezan dentro de `p_dias` días, aún no han empezado y no tienen correo enviado.
-- Devuelve el correo con el que el cliente inicia sesión (auth.users), que la app no puede leer.
create or replace function public.citas_para_recordar(p_dias integer default 2)
returns table (
  id_cita uuid, clave_aviso text, correo text, nombre_cliente text,
  nombre_servicio text, nombre_profesional text, dia date, hora time
)
language sql stable security definer
set search_path = public
as $$
  select c.id,
         to_char(c.fecha, 'YYYY-MM-DD') || ' ' || to_char(c.hora_inicio, 'HH24:MI'),
         u.email::text,
         coalesce(c.cliente_nombre, pf.nombre),
         s.nombre,
         p.nombre_negocio,
         c.fecha,
         c.hora_inicio
    from public.citas c
    join auth.users u            on u.id  = c.cliente_id
    join public.perfiles pf      on pf.id = c.cliente_id
    join public.profesionales p  on p.id  = c.profesional_id
    join public.servicios s      on s.id  = c.servicio_id
   where c.estado = 'confirmada'
     and u.email is not null
     and (c.fecha + c.hora_inicio) >  (now() at time zone 'America/Bogota')
     and (c.fecha + c.hora_inicio) <= (now() at time zone 'America/Bogota') + make_interval(days => p_dias)
     and not exists (select 1 from public.recordatorios_correo r
                      where r.cita_id = c.id
                        and r.clave = to_char(c.fecha, 'YYYY-MM-DD') || ' ' || to_char(c.hora_inicio, 'HH24:MI'))
   order by c.fecha, c.hora_inicio;
$$;

-- Expone correos: solo la clave service_role (la del servidor, nunca la de la web) puede llamarla.
revoke execute on function public.citas_para_recordar(integer) from public, anon, authenticated;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    grant execute on function public.citas_para_recordar(integer) to service_role;
    grant select, insert on public.recordatorios_correo to service_role;
  end if;
end
$$;
