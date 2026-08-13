"""Capa de integracion con Meta (Paso 1 de Datos de Meta).

Regla de arquitectura: ningun otro modulo de Publi Marketing (Campañas,
Analítica, Informes, o cualquier ruta fuera de app/modules/datos_meta)
debe importar nada de aqui directamente ni saber que la fuente de
datos es "Meta". Todo consumo pasa por servicios internos
source-agnostic (app/services/metricas.py para leer metricas ya
guardadas; app/services/meta/conexiones.py es la UNICA puerta de
entrada, y solo la usan las rutas de app/modules/datos_meta).

Submodulos:
  client.py            MetaClient -- HTTP puro contra la Graph API, sin saber nada de nuestra base de datos.
  auth_service.py       MetaAuthService -- flujo OAuth (URL de autorizacion, intercambio de codigo, token de larga duracion).
  conexiones.py          Servicio interno: CRUD de MetaConexion, cifrado/descifrado de tokens, aislamiento por empresa.
  cuentas_service.py     Descubre cuentas publicitarias/paginas/Instagram de una conexion y las guarda como EntidadPublicitaria.
"""
