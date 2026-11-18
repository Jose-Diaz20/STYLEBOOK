-- Dirección obligatoria al registrarse (cliente, establecimiento y profesional)
alter table public.perfiles add column if not exists direccion text;

create or replace function public.crear_perfil()
returns trigger
language plpgsql security definer
set search_path = public
as $$
declare
  v_tipo text := new.raw_user_meta_data->>'tipo_cuenta';
begin
  insert into public.perfiles (id, nombre, telefono, direccion, rol)
  values (
    new.id,
    coalesce(nullif(trim(new.raw_user_meta_data->>'nombre'), ''), 'Usuario'),
    nullif(trim(new.raw_user_meta_data->>'telefono'), ''),
    nullif(trim(new.raw_user_meta_data->>'direccion'), ''),
    case when v_tipo in ('establecimiento', 'profesional') then v_tipo else 'cliente' end
  );
  return new;
end;
$$;