-- INICIO AGREGADO JESUS: configuración de imágenes para servicios.

-- 1. Agregar columna para almacenar la URL de la imagen.
ALTER TABLE public.servicios
ADD COLUMN IF NOT EXISTS imagen_url TEXT;


-- 2. Crear el bucket de almacenamiento.
INSERT INTO storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
VALUES (
    'servicios',
    'servicios',
    TRUE,
    5242880,
    ARRAY[
        'image/jpeg',
        'image/png',
        'image/webp'
    ]
)
ON CONFLICT (id)
DO UPDATE SET
    public = EXCLUDED.public,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;


-- 3. Permitir que cada profesional cargue imágenes
-- únicamente en su propia carpeta.
DROP POLICY IF EXISTS
"Profesionales cargan imagenes de sus servicios"
ON storage.objects;

CREATE POLICY
"Profesionales cargan imagenes de sus servicios"
ON storage.objects
FOR INSERT
TO authenticated
WITH CHECK (
    bucket_id = 'servicios'
    AND (storage.foldername(name))[1] = auth.uid()::TEXT
);


-- 4. Permitir actualizar sus propias imágenes.
DROP POLICY IF EXISTS
"Profesionales actualizan imagenes de sus servicios"
ON storage.objects;

CREATE POLICY
"Profesionales actualizan imagenes de sus servicios"
ON storage.objects
FOR UPDATE
TO authenticated
USING (
    bucket_id = 'servicios'
    AND (storage.foldername(name))[1] = auth.uid()::TEXT
)
WITH CHECK (
    bucket_id = 'servicios'
    AND (storage.foldername(name))[1] = auth.uid()::TEXT
);


-- 5. Permitir eliminar sus propias imágenes.
DROP POLICY IF EXISTS
"Profesionales eliminan imagenes de sus servicios"
ON storage.objects;

CREATE POLICY
"Profesionales eliminan imagenes de sus servicios"
ON storage.objects
FOR DELETE
TO authenticated
USING (
    bucket_id = 'servicios'
    AND (storage.foldername(name))[1] = auth.uid()::TEXT
);

-- FIN AGREGADO JESUS: configuración de imágenes para servicios.