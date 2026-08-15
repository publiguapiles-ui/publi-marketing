"""Pruebas del importador manual de CSV de Meta Ads Manager (alternativa
mientras la sincronizacion automatica esta limitada por el codigo 17).

Cubre: guardado con fuente="meta_csv" (nunca se confunde con "meta"),
campanas no reconocidas nunca se inventan, fechas invalidas se omiten
y se reportan, aviso honesto cuando ya existen datos reales de la API
para el mismo dia (nunca se suman en silencio), formatos de columna en
espanol/ingles, numeros con simbolos de moneda, aislamiento
multiempresa, y la ruta HTTP con un archivo real."""

import io

from app.models import EntidadPublicitaria
from tests.conftest import iniciar_sesion_de_prueba


def _preparar_cuenta_con_campana(empresa_id, usuario_id, nombre_campana="Campaña Verano"):
    from app.extensions import db
    from app.services.meta.conexiones import crear_conexion
    from app.services.meta.cuentas_service import vincular_activos

    crear_conexion(empresa_id, usuario_id, "111", "A", "token-a")
    vincular_activos(empresa_id, [
        {"tipo": "cuenta_publicitaria", "id_externo": "act_123", "nombre": "Cuenta", "atributos": {"moneda": "USD"}},
    ])
    from app.services.meta.cuentas_service import listar_entidades_empresa
    cuenta = listar_entidades_empresa(empresa_id, tipo="cuenta_publicitaria")[0]

    campana = EntidadPublicitaria(
        empresa_id=empresa_id, fuente="meta", tipo="campana",
        id_externo="c1", nombre=nombre_campana, entidad_padre_id=cuenta.id,
    )
    db.session.add(campana)
    db.session.commit()
    return cuenta, campana


def _csv(filas, encabezados="Campaign name,Day,Amount spent (USD),Impressions,Link clicks"):
    return (encabezados + "\n" + "\n".join(filas)).encode("utf-8")


def test_procesar_csv_guarda_metricas_con_fuente_meta_csv(client, usuario_a_con_empresa):
    from app.services.meta.importador_csv import FUENTE_CSV, procesar_csv_meta
    from app.services.metricas import consultar_metricas

    with client.application.app_context():
        cuenta, campana = _preparar_cuenta_con_campana(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])
        contenido = _csv(["Campaña Verano,2026-08-01,100.50,5000,120"])

        resumen, error = procesar_csv_meta(usuario_a_con_empresa["empresa_id"], cuenta.id, contenido)
        assert error is None
        assert resumen["filas_guardadas"] == 1
        assert resumen["filas_omitidas"] == 0

        filas = consultar_metricas(usuario_a_con_empresa["empresa_id"], entidad_id=campana.id, metrica_nombre="spend")
        assert len(filas) == 1
        assert filas[0].valor == 100.50
        assert filas[0].fuente == FUENTE_CSV
        assert filas[0].fuente != "meta"  # nunca se confunde con una sincronizacion real


def test_procesar_csv_omite_campana_no_reconocida_sin_inventarla(client, usuario_a_con_empresa):
    from app.extensions import db
    from app.models import EntidadPublicitaria
    from app.services.meta.importador_csv import procesar_csv_meta

    with client.application.app_context():
        cuenta, _campana = _preparar_cuenta_con_campana(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])
        contenido = _csv(["Campaña Que No Existe,2026-08-01,50.0,1000,10"])

        antes = db.session.query(EntidadPublicitaria).filter_by(empresa_id=usuario_a_con_empresa["empresa_id"], tipo="campana").count()
        resumen, error = procesar_csv_meta(usuario_a_con_empresa["empresa_id"], cuenta.id, contenido)
        despues = db.session.query(EntidadPublicitaria).filter_by(empresa_id=usuario_a_con_empresa["empresa_id"], tipo="campana").count()

        assert error is None
        assert resumen["filas_guardadas"] == 0
        assert resumen["filas_omitidas"] == 1
        assert "no coincide" in resumen["advertencias"][0]
        assert antes == despues  # nunca se crea una campana nueva a partir del CSV


def test_procesar_csv_omite_fecha_invalida(client, usuario_a_con_empresa):
    from app.services.meta.importador_csv import procesar_csv_meta

    with client.application.app_context():
        cuenta, _campana = _preparar_cuenta_con_campana(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])
        contenido = _csv(["Campaña Verano,fecha-invalida,50.0,1000,10"])

        resumen, error = procesar_csv_meta(usuario_a_con_empresa["empresa_id"], cuenta.id, contenido)
        assert error is None
        assert resumen["filas_omitidas"] == 1
        assert "fecha" in resumen["advertencias"][0].lower()


def test_procesar_csv_advierte_pero_no_bloquea_si_ya_hay_datos_de_api(client, usuario_a_con_empresa):
    """Punto 11 (reconciliacion): nunca se acepta en silencio una
    posible duplicacion -- se avisa, pero la fila SI se guarda (la
    decision de que hacer con el aviso es del usuario)."""
    from app.services.meta.importador_csv import procesar_csv_meta
    from app.services.metricas import consultar_metricas, registrar_metrica
    import datetime

    with client.application.app_context():
        cuenta, campana = _preparar_cuenta_con_campana(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])
        registrar_metrica(usuario_a_con_empresa["empresa_id"], "spend", 30.0, datetime.date(2026, 8, 1), entidad_id=campana.id, entidad_tipo="campana", fuente="meta")

        contenido = _csv(["Campaña Verano,2026-08-01,100.50,5000,120"])
        resumen, error = procesar_csv_meta(usuario_a_con_empresa["empresa_id"], cuenta.id, contenido)

        assert error is None
        assert resumen["filas_guardadas"] == 1
        assert any("ya tiene datos sincronizados por API" in a for a in resumen["advertencias"])

        # Ambas fuentes coexisten -- ninguna se borro ni se fusiono en silencio.
        todas = consultar_metricas(usuario_a_con_empresa["empresa_id"], entidad_id=campana.id, metrica_nombre="spend")
        fuentes = sorted(f.fuente for f in todas)
        assert fuentes == ["meta", "meta_csv"]


def test_procesar_csv_sin_campanas_sincronizadas_da_error_honesto(client, usuario_a_con_empresa):
    from app.services.meta.conexiones import crear_conexion
    from app.services.meta.cuentas_service import listar_entidades_empresa, vincular_activos
    from app.services.meta.importador_csv import procesar_csv_meta

    with client.application.app_context():
        crear_conexion(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "111", "A", "token-a")
        vincular_activos(usuario_a_con_empresa["empresa_id"], [
            {"tipo": "cuenta_publicitaria", "id_externo": "act_123", "nombre": "Cuenta", "atributos": {}},
        ])
        cuenta = listar_entidades_empresa(usuario_a_con_empresa["empresa_id"], tipo="cuenta_publicitaria")[0]

        resumen, error = procesar_csv_meta(usuario_a_con_empresa["empresa_id"], cuenta.id, _csv(["X,2026-08-01,1,1,1"]))
        assert resumen is None
        assert error is not None
        assert "sincronizada" in error.lower()


def test_procesar_csv_reconoce_encabezados_en_espanol(client, usuario_a_con_empresa):
    from app.services.meta.importador_csv import procesar_csv_meta
    from app.services.metricas import consultar_metricas

    with client.application.app_context():
        cuenta, campana = _preparar_cuenta_con_campana(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])
        contenido = _csv(
            ["Campaña Verano,01/08/2026,\"1,234.56\",5000,120"],
            encabezados="Nombre de la campaña,Día,Importe gastado (USD),Impresiones,Clics en el enlace",
        )

        resumen, error = procesar_csv_meta(usuario_a_con_empresa["empresa_id"], cuenta.id, contenido)
        assert error is None
        assert resumen["filas_guardadas"] == 1

        filas = consultar_metricas(usuario_a_con_empresa["empresa_id"], entidad_id=campana.id, metrica_nombre="spend")
        assert filas[0].valor == 1234.56  # simbolos de moneda y comas de miles se limpian correctamente


def test_procesar_csv_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    """La cuenta_id de la empresa A nunca debe poder usarse para
    importar datos si se llama con el empresa_id de B."""
    from app.services.meta.importador_csv import procesar_csv_meta

    with client.application.app_context():
        cuenta_a, _campana = _preparar_cuenta_con_campana(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])

        resumen, error = procesar_csv_meta(usuario_b_con_empresa["empresa_id"], cuenta_a.id, _csv(["Campaña Verano,2026-08-01,1,1,1"]))
        assert resumen is None
        assert error is not None


def test_ruta_importar_csv_guarda_metricas_reales(client, usuario_a_con_empresa):
    with client.application.app_context():
        cuenta, campana = _preparar_cuenta_con_campana(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])
        cuenta_id = cuenta.id
        campana_id = campana.id

    archivo = io.BytesIO(_csv(["Campaña Verano,2026-08-01,75.0,2000,40"]))
    resp = client.post(
        "/datos-meta/conexiones/importar-csv",
        data={"cuenta_id": str(cuenta_id), "archivo": (archivo, "reporte.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    cuerpo = resp.get_json()
    assert cuerpo["ok"] is True
    assert cuerpo["filas_guardadas"] == 1

    with client.application.app_context():
        from app.services.metricas import consultar_metricas

        filas = consultar_metricas(usuario_a_con_empresa["empresa_id"], entidad_id=campana_id, metrica_nombre="spend")
        assert len(filas) == 1


def test_ruta_importar_csv_rechaza_extension_incorrecta(client, usuario_a_con_empresa):
    with client.application.app_context():
        cuenta, _campana = _preparar_cuenta_con_campana(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"])
        cuenta_id = cuenta.id

    archivo = io.BytesIO(b"no es un csv")
    resp = client.post(
        "/datos-meta/conexiones/importar-csv",
        data={"cuenta_id": str(cuenta_id), "archivo": (archivo, "reporte.txt")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_ruta_importar_csv_formulario_requiere_sesion(client):
    resp = client.get("/datos-meta/conexiones/importar-csv")
    assert resp.status_code in (302, 401)
