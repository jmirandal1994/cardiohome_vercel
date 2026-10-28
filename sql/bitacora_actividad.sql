-- Bitácora de actividad de la plataforma (ejecutar una sola vez en el SQL Editor de Supabase)
create table if not exists public.bitacora_actividad (
  id            bigint generated always as identity primary key,
  creado_en     timestamptz not null default now(),
  usuario_id    text,
  rol           text,
  nombre        text,
  accion        text not null,
  nomina_id     text,
  estudiante_id text,
  detalle       jsonb,
  ip            text
);

create index if not exists bitacora_actividad_creado_idx  on public.bitacora_actividad (creado_en desc);
create index if not exists bitacora_actividad_usuario_idx on public.bitacora_actividad (usuario_id, creado_en desc);
create index if not exists bitacora_actividad_accion_idx  on public.bitacora_actividad (accion, creado_en desc);

-- Solo el servidor (service role) lee y escribe; la llave pública no tiene acceso.
alter table public.bitacora_actividad enable row level security;
