-- StyleBook · HU-14/HU-15: promedio de calificaciones por servicio.
-- Ejecutar en Supabase SQL Editor DESPUÉS de db/schema.sql.
-- Idempotente: puede volver a ejecutarse para actualizar una instalación existente.
-- El comentario de la reseña continúa siendo opcional.

-- La reseña sigue ligada a su cita; este FK agrega y permite consultar opiniones por servicio.
alter table public.calificaciones
  add column if not exists servicio_id uuid;

update public.calificaciones r
   set servicio_id = c.servicio_id
  from public.citas c
 where c.id = r.cita_id
   and r.servicio_id is null;

alter table public.calificaciones
  alter column servicio_id set not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint
     where conname = 'calificaciones_servicio_id_fkey'
       and conrelid = 'public.calificaciones'::regclass
  ) then
    alter table public.calificaciones
      add constraint calificaciones_servicio_id_fkey
      foreign key (servicio_id) references public.servicios(id) on delete cascade;
  end if;
end
$$;

create index if not exists idx_calificaciones_servicio
  on public.calificaciones(servicio_id, creado_en desc);

alter table public.servicios
  add column if not exists calificacion_promedio numeric(3,2),
  add column if not exists total_calificaciones integer not null default 0;

-- Inicializa los agregados para reseñas existentes.
update public.servicios s set
  calificacion_promedio = r.promedio,
  total_calificaciones = r.total
from (
  select servicio_id, round(avg(puntuacion)::numeric, 2) as promedio, count(*)::integer as total
    from public.calificaciones
   group by servicio_id
) r
where r.servicio_id = s.id;

update public.servicios s set
  calificacion_promedio = null,
  total_calificaciones = 0
where not exists (
  select 1 from public.calificaciones r where r.servicio_id = s.id
);

-- Recalcula promedios del proveedor y del servicio tras cambios en reseñas.
create or replace function public.actualizar_promedio_proveedor()
returns trigger
language plpgsql security definer
set search_path = public
as $$
begin
  if tg_op = 'DELETE' then
    update public.profesionales p set
      calificacion_promedio = (select round(avg(c.puntuacion)::numeric, 2)
                                 from public.calificaciones c where c.profesional_id = old.profesional_id),
      total_calificaciones = (select count(*)::integer
                                from public.calificaciones c where c.profesional_id = old.profesional_id)
    where p.id = old.profesional_id;
    update public.servicios s set
      calificacion_promedio = (select round(avg(c.puntuacion)::numeric, 2)
                                 from public.calificaciones c where c.servicio_id = old.servicio_id),
      total_calificaciones = (select count(*)::integer
                                from public.calificaciones c where c.servicio_id = old.servicio_id)
    where s.id = old.servicio_id;
    return old;
  end if;

  update public.profesionales p set
    calificacion_promedio = (select round(avg(c.puntuacion)::numeric, 2)
                               from public.calificaciones c where c.profesional_id = new.profesional_id),
    total_calificaciones = (select count(*)::integer
                              from public.calificaciones c where c.profesional_id = new.profesional_id)
  where p.id = new.profesional_id;
  update public.servicios s set
    calificacion_promedio = (select round(avg(c.puntuacion)::numeric, 2)
                               from public.calificaciones c where c.servicio_id = new.servicio_id),
    total_calificaciones = (select count(*)::integer
                              from public.calificaciones c where c.servicio_id = new.servicio_id)
  where s.id = new.servicio_id;

  if tg_op = 'UPDATE' and (old.servicio_id is distinct from new.servicio_id
                           or old.profesional_id is distinct from new.profesional_id) then
    update public.servicios s set
      calificacion_promedio = (select round(avg(c.puntuacion)::numeric, 2)
                                 from public.calificaciones c where c.servicio_id = old.servicio_id),
      total_calificaciones = (select count(*)::integer
                                from public.calificaciones c where c.servicio_id = old.servicio_id)
    where s.id = old.servicio_id;
    update public.profesionales p set
      calificacion_promedio = (select round(avg(c.puntuacion)::numeric, 2)
                                 from public.calificaciones c where c.profesional_id = old.profesional_id),
      total_calificaciones = (select count(*)::integer
                                from public.calificaciones c where c.profesional_id = old.profesional_id)
    where p.id = old.profesional_id;
  end if;
  return new;
end;
$$;

drop trigger if exists actualizar_promedio_trg on public.calificaciones;
create trigger actualizar_promedio_trg
after insert or update or delete on public.calificaciones
for each row execute function public.actualizar_promedio_proveedor();

-- El servicio calificado se deriva de la cita, no de un valor enviado por el navegador.
create or replace function public.validar_calificacion()
returns trigger
language plpgsql security definer
set search_path = public
as $$
declare
  v_cita public.citas%rowtype;
  v_nombre text;
  v_servicio text;
begin
  select * into v_cita from public.citas where id = new.cita_id;
  if not found then
    raise exception 'SB: La cita no existe.';
  end if;
  if auth.uid() is not null and auth.uid() <> v_cita.cliente_id then
    raise exception 'SB: Solo puedes calificar tus propias citas.';
  end if;
  if v_cita.estado <> 'completada' then
    raise exception 'SB: Solo puedes calificar citas completadas.';
  end if;

  select nombre into v_nombre from public.perfiles where id = v_cita.cliente_id;
  select nombre into v_servicio from public.servicios where id = v_cita.servicio_id;
  v_nombre := btrim(coalesce(v_nombre, ''));

  new.cliente_id := v_cita.cliente_id;
  new.profesional_id := v_cita.profesional_id;
  new.servicio_id := v_cita.servicio_id;
  new.servicio_nombre := v_servicio;
  new.cliente_nombre := case
    when v_nombre = '' then 'Cliente'
    when position(' ' in v_nombre) = 0 then v_nombre
    else split_part(v_nombre, ' ', 1) || ' '
         || upper(left(btrim(substr(v_nombre, position(' ' in v_nombre))), 1)) || '.'
  end;
  new.comentario := nullif(btrim(coalesce(new.comentario, '')), '');
  return new;
end;
$$;
