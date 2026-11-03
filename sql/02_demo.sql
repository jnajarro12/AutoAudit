-- Tabla de demostración. No es requisito auditar esta tabla; sirve para validar el sistema.
CREATE TABLE IF NOT EXISTS public.empleados_demo (
    empleado_id BIGSERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    puesto TEXT NOT NULL,
    salario NUMERIC(10,2) NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE
);

INSERT INTO public.empleados_demo(nombre, puesto, salario)
SELECT 'Carlos Pérez', 'Auxiliar', 3500.00
WHERE NOT EXISTS (SELECT 1 FROM public.empleados_demo WHERE nombre = 'Carlos Pérez');
