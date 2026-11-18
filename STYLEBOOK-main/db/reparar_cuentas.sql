-- ============================================================
-- StyleBook · Diagnóstico y reparación de cuentas (ejecutar en Supabase → SQL Editor)
-- Úsalo si alguien inicia sesión y ve el menú o los permisos de otro tipo de cuenta,
-- o si el login dice "No pudimos cargar tu perfil".
-- La app decide el menú y los permisos por `perfiles.rol`, no por lo que se eligió al registrarse.
-- ============================================================

-- 1) Crear el perfil de los usuarios de Auth que no tengan (cuentas creadas antes del trigger).
insert into public.perfiles (id, nombre, telefono, rol)
select u.id,
       coalesce(nullif(trim(u.raw_user_meta_data->>'nombre'), ''), 'Usuario'),
       nullif(trim(u.raw_user_meta_data->>'telefono'), ''),
       case when u.raw_user_meta_data->>'tipo_cuenta' in ('establecimiento', 'profesional')
            then u.raw_user_meta_data->>'tipo_cuenta' else 'cliente' end
  from auth.users u
 where not exists (select 1 from public.perfiles p where p.id = u.id);

-- 2) Diagnóstico: revisa que el rol de cada cuenta sea el que esperas.
select u.email,
       p.rol                                   as rol_en_perfil,
       u.raw_user_meta_data->>'tipo_cuenta'    as tipo_elegido_al_registrarse,
       exists (select 1 from public.profesionales x where x.perfil_id = u.id) as tiene_negocio
  from auth.users u
  left join public.perfiles p on p.id = u.id
 order by u.created_at;

-- 3) Corrección manual de un rol (descomenta, cambia el correo y el rol, y ejecuta).
--    Roles válidos: 'cliente', 'establecimiento', 'profesional', 'admin'.
-- update public.perfiles
--    set rol = 'cliente'
--  where id = (select id from auth.users where email = 'correo@ejemplo.com');
