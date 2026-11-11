
-- =====================================================================
-- Panel de administrador: ver los servicios de cada proveedor y
-- eliminarlos indicando el motivo.
-- Ejecutar UNA vez en Supabase -> SQL Editor (es idempotente).
-- Requiere haber corrido antes db/schema.sql y migracion_imagenes_servicios.sql.
-- =====================================================================

-- 1. El administrador puede LEER todos los servicios (activos o no, de proveedores
--    aprobados, pendientes o rechazados). Sin esto la RLS solo le deja ver los públicos.
drop policy if exists "servicios lectura admin" on public.servicios;
create policy "servicios lectura admin" on public.servicios
  for select using (public.es_admin());


-- 2. Registro de las eliminaciones: quién, cuándo, qué servicio y por qué.
create table if not exists public.servicios_eliminados (
  id              uuid primary key default gen_random_uuid(),
  servicio_id     uuid not null,
  servicio_nombre text not null,
  profesional_id  uuid references public.profesionales(id) on delete set null,
  resultado       text not null check (resultado in ('eliminado', 'desactivado')),
  motivo          text not null check (char_length(motivo) between 10 and 500),
  admin_id        uuid references public.perfiles(id) on delete set null,
  creado_en       timestamptz not null default now()
);
create index if not exists idx_servicios_eliminados_prof
  on public.servicios_eliminados(profesional_id, creado_en desc);

alter table public.servicios_eliminados enable row level security;
drop policy if exists "servicios eliminados lectura admin" on public.servicios_eliminados;
create policy "servicios eliminados lectura admin" on public.servicios_eliminados
  for select using (public.es_admin());
-- Sin políticas de INSERT/UPDATE/DELETE: solo escribe la función de abajo.


-- 3. Función que ejecuta la eliminación. Solo la puede usar un administrador.
--
--    · Si el servicio NUNCA tuvo citas        -> se borra definitivamente.
--    · Si ya tiene citas (aunque sean viejas) -> la tabla citas lo protege (on delete restrict)
--      para no perder el historial de los clientes, así que se DESACTIVA: desaparece del
--      catálogo y nadie puede reservarlo. Las citas futuras pendientes/confirmadas se cancelan
--      y los clientes reciben el aviso de siempre.
--
--    En ambos casos el profesional recibe una notificación con el motivo.
create or replace function public.admin_retirar_servicio(p_servicio_id uuid, p_motivo text)
returns text
language plpgsql security definer
set search_path = public
as $$
declare
  v_motivo   text := btrim(coalesce(p_motivo, ''));
  v_servicio public.servicios%rowtype;
  v_dueno    uuid;
  v_ahora    timestamp := (now() at time zone 'America/Bogota');
  v_resultado text;
begin
  if auth.uid() is null or not public.es_admin() then
    raise exception 'SB: Solo un administrador puede eliminar servicios.';
  end if;
  if char_length(v_motivo) < 10 then
    raise exception 'SB: Escribe el motivo de la eliminación (mínimo 10 caracteres).';
  end if;
  if char_length(v_motivo) > 500 then
    raise exception 'SB: El motivo es demasiado largo (máximo 500 caracteres).';
  end if;

  select * into v_servicio from public.servicios where id = p_servicio_id for update;
  if not found then
    raise exception 'SB: El servicio no existe o ya fue eliminado.';
  end if;
  select perfil_id into v_dueno from public.profesionales where id = v_servicio.profesional_id;

  if exists (select 1 from public.citas where servicio_id = p_servicio_id) then
    -- Con historial: se desactiva y se cancelan las citas que aún no ocurren.
    update public.citas
       set estado = 'cancelada'
     where servicio_id = p_servicio_id
       and estado in ('pendiente', 'confirmada')
       and (fecha + hora_inicio) >= v_ahora;
    update public.servicios set activo = false where id = p_servicio_id;
    v_resultado := 'desactivado';
  else
    delete from public.servicios where id = p_servicio_id;
    v_resultado := 'eliminado';
  end if;

  insert into public.servicios_eliminados
    (servicio_id, servicio_nombre, profesional_id, resultado, motivo, admin_id)
  values
    (p_servicio_id, v_servicio.nombre, v_servicio.profesional_id, v_resultado, v_motivo, auth.uid());

  if v_dueno is not null then
    insert into public.notificaciones (usuario_id, tipo, mensaje) values (
      v_dueno, 'servicio_eliminado',
      'Un administrador ' ||
      case when v_resultado = 'eliminado' then 'eliminó' else 'retiró del catálogo' end ||
      ' tu servicio "' || v_servicio.nombre || '". Motivo: ' || v_motivo);
  end if;

  return v_resultado;
end;
$$;

revoke execute on function public.admin_retirar_servicio(uuid, text) from public, anon;
grant  execute on function public.admin_retirar_servicio(uuid, text) to authenticated;


-- 4. Storage: el administrador puede borrar la foto de un servicio eliminado.
drop policy if exists "Admin ve imagenes de servicios" on storage.objects;
create policy "Admin ve imagenes de servicios"
  on storage.objects for select to authenticated
  using (bucket_id = 'servicios' and public.es_admin());

drop policy if exists "Admin elimina imagenes de servicios" on storage.objects;
create policy "Admin elimina imagenes de servicios"
  on storage.objects for delete to authenticated
  using (bucket_id = 'servicios' and public.es_admin());
