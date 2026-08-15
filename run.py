# Punto de entrada de gunicorn en produccion (ver Procfile: "gunicorn
# --timeout 300 --workers 2 run:app"). El Procfile pasa de 1 a 2
# workers desde el Paso 16.1 -- causa raiz real del 503 intermitente
# reportado en el Paso 15 al descargar un PDF: con un UNICO worker
# sincrono, cualquier otra peticion en curso en ese mismo proceso
# (trafico real de la app, no solo las pruebas) deja la descarga en
# cola; si el borde/proxy de Railway responde antes de que el worker
# quede libre, el navegador recibe 503 aunque el PDF se hubiera
# generado bien segundos despues. Se confirmo descartando, en orden,
# datos obsoletos, concurrencia propia (peticiones espaciadas 3-5s
# seguian fallando) y el subsistema reportlab.graphics (eliminado por
# completo en el Paso 15 sin resolver el problema) -- ninguno de los
# tres explicaba fallos con datos frescos y peticiones no concurrentes
# de este lado. Con 2 workers el analisis de codigo no cambia
# (Flask-SQLAlchemy usa sesiones con scope por hilo/proceso, cada
# worker es un proceso independiente), asi que no hay riesgo de estado
# compartido incorrecto entre workers.
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
