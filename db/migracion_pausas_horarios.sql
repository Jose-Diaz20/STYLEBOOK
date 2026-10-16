-- StyleBook: pausas/almuerzo en el horario semanal.
-- Ejecutar una sola vez (o repetir con seguridad) en Supabase SQL Editor.
alter table public.horarios_profesional
  add column if not exists pausa_inicio time,
  add column if not exists pausa_fin time;

-- Las dos columnas deben estar vacías o ambas definidas.
alter table public.horarios_profesional
  drop constraint if exists horarios_profesional_pausa_check;

alter table public.horarios_profesional
  add constraint horarios_profesional_pausa_check
  check (
    (pausa_inicio is null and pausa_fin is null)
    or
    (pausa_inicio is not null and pausa_fin is not null
      and pausa_fin > pausa_inicio
      and pausa_inicio > hora_inicio
      and pausa_fin < hora_fin)
  );
