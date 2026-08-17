"""Pruebas del Paso 4: Creacion de Marketing (objetivo y brief).

Cubre exclusivamente lo nuevo de este paso -- creacion de proyecto,
cada seccion del brief (objetivo/publico/oferta/accion/presupuesto/
plazo/identidad/informacion adicional), edicion, deteccion de campos
faltantes, confirmacion y aislamiento multiempresa. No depende de
Datos de Meta ni de ANTHROPIC_API_KEY para lo esencial -- la ayuda de
IA (sugerir_completado_con_ia) se prueba solo verificando que responde
el error "no configurado", sin requerir la clave real.
"""

from tests.conftest import iniciar_sesion_de_prueba


def _datos_brief_completo():
    return {
        "objetivo_tipo": "aumentar_ventas",
        "publico": {"ubicacion": "San José", "edad": "25-45"},
        "oferta": {"producto": "Pan artesanal", "beneficio_principal": "Recién horneado cada día"},
        "accion_deseada": "escribir_whatsapp",
        "presupuesto_produccion": 50000,
        "presupuesto_pauta": 100000,
        "fecha_inicio": None,
        "fecha_fin": None,
        "sin_fecha_definida": True,
        "identidad_marca_brief": {"tono": "cercano"},
        "informacion_adicional": "Lanzamiento de temporada",
    }


# --- Creacion de proyecto: solo cliente + nombre --------------------------------------

def test_crear_proyecto_exitoso(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, error = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "Campaña Día de la Madre")
        assert error is None
        assert proyecto.id is not None
        assert proyecto.estado == "borrador"
        assert proyecto.nombre == "Campaña Día de la Madre"
        # brief vacio por defecto, no None (evita errores en el resto del servicio)
        assert proyecto.publico == {}
        assert proyecto.oferta == {}


def test_crear_proyecto_requiere_nombre(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, error = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "   ")
        assert proyecto is None
        assert "nombre" in error.lower()


def test_listar_proyectos_aislado_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.creacion_marketing import crear_proyecto, listar_proyectos_empresa

    with client.application.app_context():
        crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "Proyecto secreto de A")
        assert listar_proyectos_empresa(usuario_b_con_empresa["empresa_id"]) == []


def test_obtener_proyecto_de_otra_empresa_es_none(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.creacion_marketing import crear_proyecto, obtener_proyecto

    with client.application.app_context():
        proyecto, _ = crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "Proyecto A")
        assert obtener_proyecto(usuario_b_con_empresa["empresa_id"], proyecto.id) is None


# --- Brief: cada seccion --------------------------------------------------------------

def test_actualizar_brief_objetivo(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        actualizado, error = actualizar_brief(empresa_id, proyecto.id, {"objetivo_tipo": "conseguir_clientes"})
        assert error is None
        assert actualizado.objetivo_tipo == "conseguir_clientes"


def test_actualizar_brief_objetivo_invalido_rechazado(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        actualizado, error = actualizar_brief(empresa_id, proyecto.id, {"objetivo_tipo": "no_existe"})
        assert actualizado is None
        assert error is not None


def test_actualizar_brief_publico(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        actualizado, error = actualizar_brief(empresa_id, proyecto.id, {
            "publico": {"ubicacion": "Heredia", "edad": "18-30", "clave_invalida": "se descarta"},
        })
        assert error is None
        assert actualizado.publico == {"ubicacion": "Heredia", "edad": "18-30"}


def test_actualizar_brief_oferta(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        actualizado, error = actualizar_brief(empresa_id, proyecto.id, {
            "oferta": {"producto": "Torta de chocolate", "precio": "₡8.000"},
        })
        assert error is None
        assert actualizado.oferta["producto"] == "Torta de chocolate"


def test_actualizar_brief_accion_deseada(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        actualizado, error = actualizar_brief(empresa_id, proyecto.id, {"accion_deseada": "reservar"})
        assert error is None
        assert actualizado.accion_deseada == "reservar"


def test_actualizar_brief_presupuesto_separa_produccion_y_pauta(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        actualizado, error = actualizar_brief(empresa_id, proyecto.id, {
            "presupuesto_produccion": 30000, "presupuesto_pauta": 120000,
        })
        assert error is None
        assert actualizado.presupuesto_produccion == 30000
        assert actualizado.presupuesto_pauta == 120000
        assert actualizado.presupuesto_produccion != actualizado.presupuesto_pauta  # nunca se asumen iguales


def test_actualizar_brief_presupuesto_vacio_queda_por_definir(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import _texto_presupuesto, actualizar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        assert proyecto.presupuesto_produccion is None
        assert _texto_presupuesto(proyecto.presupuesto_produccion, proyecto.moneda) == "Por definir"


def test_actualizar_brief_plazo_con_fechas(client, usuario_a_con_empresa):
    import datetime

    from app.services.creacion_marketing import actualizar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        actualizado, error = actualizar_brief(empresa_id, proyecto.id, {
            "fecha_inicio": datetime.date(2026, 9, 1), "fecha_fin": datetime.date(2026, 9, 30),
        })
        assert error is None
        assert actualizado.fecha_inicio == datetime.date(2026, 9, 1)


def test_actualizar_brief_plazo_sin_fecha_definida(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        actualizado, error = actualizar_brief(empresa_id, proyecto.id, {"sin_fecha_definida": True})
        assert error is None
        assert actualizado.sin_fecha_definida is True


def test_actualizar_brief_identidad_marca(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        actualizado, error = actualizar_brief(empresa_id, proyecto.id, {
            "identidad_marca_brief": {"tono": "divertido", "restricciones": "no usar rojo"},
        })
        assert error is None
        assert actualizado.identidad_marca_brief["tono"] == "divertido"


def test_actualizar_brief_informacion_adicional(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        actualizado, error = actualizar_brief(empresa_id, proyecto.id, {"informacion_adicional": "Ojo con el clima"})
        assert error is None
        assert actualizado.informacion_adicional == "Ojo con el clima"


def test_actualizar_brief_edicion_sobrescribe_valor_previo(client, usuario_a_con_empresa):
    """Edicion (Paso 4, punto 12): responder de nuevo una pregunta ya
    contestada debe reemplazar el valor anterior, no acumularlo."""
    from app.services.creacion_marketing import actualizar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        actualizar_brief(empresa_id, proyecto.id, {"objetivo_tipo": "dar_a_conocer"})
        actualizado, error = actualizar_brief(empresa_id, proyecto.id, {"objetivo_tipo": "aumentar_ventas"})
        assert error is None
        assert actualizado.objetivo_tipo == "aumentar_ventas"


def test_actualizar_brief_de_otra_empresa_rechazado(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, crear_proyecto

    with client.application.app_context():
        proyecto, _ = crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "P")

        actualizado, error = actualizar_brief(usuario_b_con_empresa["empresa_id"], proyecto.id, {"objetivo_tipo": "aumentar_ventas"})
        assert actualizado is None
        assert error is not None


# --- Campos faltantes y confirmacion ---------------------------------------------------

def test_detectar_campos_faltantes_proyecto_vacio(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import crear_proyecto, detectar_campos_faltantes

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        faltantes = detectar_campos_faltantes(proyecto)
        assert len(faltantes) > 0
        assert any("lograr" in f for f in faltantes)
        assert any("acción" in f for f in faltantes)


def test_detectar_campos_faltantes_brief_completo(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, crear_proyecto, detectar_campos_faltantes

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")
        proyecto, _ = actualizar_brief(empresa_id, proyecto.id, _datos_brief_completo())

        assert detectar_campos_faltantes(proyecto) == []


def test_confirmar_brief_incompleto_rechazado(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import confirmar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        confirmado, error = confirmar_brief(empresa_id, proyecto.id)
        assert confirmado is None
        assert "lograr" in error.lower()


def test_confirmar_brief_objetivo_otro_sin_detalle_rechazado(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, confirmar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")
        actualizar_brief(empresa_id, proyecto.id, {"objetivo_tipo": "otro", "accion_deseada": "comprar"})

        confirmado, error = confirmar_brief(empresa_id, proyecto.id)
        assert confirmado is None
        assert "otro" in error.lower()


def test_confirmar_brief_minimo_exitoso(client, usuario_a_con_empresa):
    """Confirmar solo exige objetivo + accion -- el resto puede quedar
    'Por definir' (Paso 4, punto 7 lo permite explicitamente)."""
    from app.services.creacion_marketing import actualizar_brief, confirmar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")
        actualizar_brief(empresa_id, proyecto.id, {"objetivo_tipo": "aumentar_ventas", "accion_deseada": "llamar"})

        confirmado, error = confirmar_brief(empresa_id, proyecto.id)
        assert error is None
        assert confirmado.estado == "confirmado"


def test_confirmar_brief_de_otra_empresa_rechazado(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, confirmar_brief, crear_proyecto

    with client.application.app_context():
        proyecto, _ = crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "P")
        actualizar_brief(usuario_a_con_empresa["empresa_id"], proyecto.id, {"objetivo_tipo": "aumentar_ventas", "accion_deseada": "llamar"})

        confirmado, error = confirmar_brief(usuario_b_con_empresa["empresa_id"], proyecto.id)
        assert confirmado is None
        assert error is not None


def test_editar_brief_despues_de_confirmado_sigue_permitido(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, confirmar_brief, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")
        actualizar_brief(empresa_id, proyecto.id, {"objetivo_tipo": "aumentar_ventas", "accion_deseada": "llamar"})
        confirmar_brief(empresa_id, proyecto.id)

        actualizado, error = actualizar_brief(empresa_id, proyecto.id, {"informacion_adicional": "Nota nueva"})
        assert error is None
        assert actualizado.informacion_adicional == "Nota nueva"
        assert actualizado.estado == "confirmado"  # editar no revierte la confirmacion


# --- Resumen automatico -----------------------------------------------------------------

def test_construir_resumen_incluye_las_secciones(client, usuario_a_con_empresa):
    from app.services.creacion_marketing import actualizar_brief, construir_resumen, crear_proyecto

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")
        proyecto, _ = actualizar_brief(empresa_id, proyecto.id, _datos_brief_completo())

        resumen = construir_resumen(empresa_id, proyecto)
        for clave in ("objetivo", "publico", "oferta", "mensaje_principal", "accion_deseada", "presupuesto", "plazo", "marca", "informacion_adicional"):
            assert clave in resumen
        assert resumen["objetivo"]["etiqueta"] == "Aumentar ventas"
        assert resumen["mensaje_principal"] == "Recién horneado cada día"


def test_construir_resumen_reutiliza_identidad_de_marca_existente(client, usuario_a_con_empresa):
    """Paso 4, punto 9: nunca repetir informacion que ya exista en Publi
    Marketing -- el resumen debe leer IdentidadMarca en vivo."""
    from app.services.creacion_marketing import construir_resumen, crear_proyecto
    from app.services.marca import guardar_identidad

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        guardar_identidad(empresa_id, "Panadería Bendetto", "#FF0000", None, None, None)
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")

        resumen = construir_resumen(empresa_id, proyecto)
        assert resumen["marca"]["nombre_comercial"] == "Panadería Bendetto"
        assert resumen["marca"]["color_principal"] == "#FF0000"


# --- Ayuda de IA (sin inventar, nunca requiere la clave real) --------------------------

def test_sugerir_completado_con_ia_sin_api_key_da_error_amigable(client, usuario_a_con_empresa, monkeypatch):
    from app.extensions import db
    from app.models import Empresa
    from app.services.creacion_marketing import crear_proyecto, sugerir_completado_con_ia

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")
        empresa = db.session.query(Empresa).filter_by(id=empresa_id).first()

        texto, error = sugerir_completado_con_ia(empresa, proyecto)
        assert texto is None
        assert "no está configurado" in error.lower()


def test_sugerir_completado_con_ia_brief_completo_no_llama_a_ia(client, usuario_a_con_empresa):
    """Si ya no falta nada, nunca se llama a Claude -- se responde
    directo, sin gastar tokens ni depender de la API key."""
    from app.extensions import db
    from app.models import Empresa
    from app.services.creacion_marketing import actualizar_brief, crear_proyecto, sugerir_completado_con_ia

    with client.application.app_context():
        empresa_id = usuario_a_con_empresa["empresa_id"]
        proyecto, _ = crear_proyecto(empresa_id, usuario_a_con_empresa["usuario_id"], "P")
        proyecto, _ = actualizar_brief(empresa_id, proyecto.id, _datos_brief_completo())
        empresa = db.session.query(Empresa).filter_by(id=empresa_id).first()

        texto, error = sugerir_completado_con_ia(empresa, proyecto)
        assert error is None
        assert "mínima" in texto or "minima" in texto


# --- Ruta completa: creacion end-to-end -------------------------------------------------

def test_ruta_crear_proyecto_end_to_end(client, usuario_a_con_empresa):
    resp = client.post("/creacion-marketing/crear", json={"nombre": "Campaña Día de la Madre"})
    assert resp.status_code == 201
    datos = resp.get_json()
    assert datos["ok"] is True
    proyecto_id = datos["proyecto_id"]

    resp_detalle = client.get(f"/creacion-marketing/{proyecto_id}")
    assert resp_detalle.status_code == 200
    assert "Campaña Día de la Madre" in resp_detalle.get_data(as_text=True)

    resp_brief = client.post(
        f"/creacion-marketing/{proyecto_id}/brief",
        json={"objetivo_tipo": "aumentar_ventas", "accion_deseada": "llamar", "publico": {"ubicacion": "San José"}},
    )
    assert resp_brief.status_code == 200
    assert resp_brief.get_json()["ok"] is True

    resp_resumen = client.get(f"/creacion-marketing/{proyecto_id}/resumen")
    assert resp_resumen.status_code == 200
    datos_resumen = resp_resumen.get_json()
    assert datos_resumen["ok"] is True
    assert datos_resumen["resumen"]["objetivo"]["etiqueta"] == "Aumentar ventas"

    resp_confirmar = client.post(f"/creacion-marketing/{proyecto_id}/confirmar")
    assert resp_confirmar.status_code == 200
    assert resp_confirmar.get_json()["proyecto"]["estado"] == "confirmado"


def test_ruta_detalle_de_otra_empresa_da_404(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.creacion_marketing import crear_proyecto

    with client.application.app_context():
        proyecto, _ = crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "Proyecto secreto de A")
        proyecto_id = proyecto.id

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get(f"/creacion-marketing/{proyecto_id}")
    assert resp.status_code == 404


def test_ruta_lista_muestra_etiqueta_de_objetivo_ya_definido(client, usuario_a_con_empresa):
    """Regresion: la lista debe renderizar sin error cuando un proyecto
    ya tiene objetivo_tipo definido (evalua etiquetas_objetivos.get())."""
    from app.services.creacion_marketing import actualizar_brief, crear_proyecto

    with client.application.app_context():
        proyecto, _ = crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "P")
        actualizar_brief(usuario_a_con_empresa["empresa_id"], proyecto.id, {"objetivo_tipo": "aumentar_ventas"})

    resp = client.get("/creacion-marketing/")
    assert resp.status_code == 200
    assert "Aumentar ventas" in resp.get_data(as_text=True)


def test_ruta_lista_aislada_por_empresa(client, usuario_a_con_empresa, usuario_b_con_empresa):
    from app.services.creacion_marketing import crear_proyecto

    with client.application.app_context():
        crear_proyecto(usuario_a_con_empresa["empresa_id"], usuario_a_con_empresa["usuario_id"], "Proyecto secreto de A")

    iniciar_sesion_de_prueba(client, usuario_b_con_empresa["usuario_id"], "b@example.com")
    resp = client.get("/creacion-marketing/")
    assert resp.status_code == 200
    assert "Proyecto secreto de A" not in resp.get_data(as_text=True)
