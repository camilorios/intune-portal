# Avisos de terceros

## Intune Hydration Kit
Las baselines `grupos-y-filtros-v1`, `identidad-segura-v1` y `moviles-v1` se generaron con
`scripts/import_hydration_kit.py` a partir de las plantillas de
https://github.com/jorgeasaurus/IntuneHydrationKit, adaptadas (prefijo [HK], acceso condicional
en modo solo informe, grupo de emergencia excluido, sin acciones de retirar o bloquear dispositivos).

MIT License — Copyright (c) 2026 Jorge Suarez

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT
OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Ideas de diseño (sin código copiado)
- Micke-K/IntuneManagement (MIT): catálogo de tipos con orden de importación y propiedades a quitar; tabla de migración de grupos entre tenants; modos de importación.
- antoporter/trustm365 (MIT): detección de desviaciones por propiedad y restauración.
- ugurkocde/TenuVault: backups cifrados con AES-256-GCM.
