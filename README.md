# RutaAmiga API

Base del backend que separa Flutter de Supabase Database, Cloudflare R2, Google
Maps Platform y el Motor de IA existente.

## Alcance actual

- Valida sesiones de Supabase Auth.
- Genera URL firmadas para cargar evidencias directamente a Cloudflare R2.
- Registra evidencias de forma idempotente con `client_evidence_id`.
- Envía la imagen al endpoint `/predict` existente sin cambiar el modelo.
- Calcula un Score Multimodal explicable y versionado (45/20/35).
- Mantiene plausibilidad, cobertura y duplicidad como resultados separados.
- Conserva la evidencia y la envía a revisión humana si la IA no está disponible.
- Incluye una cola administrativa protegida por `app_metadata.role=admin`.
- Expone lugares cercanos desde la RPC actual de Supabase.
- Protege las claves de Google Places y Google Routes detrás del backend.
- Usa Sentinel-2 y DEM como señales complementarias, nunca como rechazo automático.
- Registra muestras GPS espaciadas y genera una prueba de presencia con ventana móvil de 24 horas.
- Sincroniza por usuario favoritos, rutas personales y reseñas, conservando una copia local para uso sin conexión.

## Ejecución local

```bash
cd /ruta/al/turismo_backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
# Crea un archivo .env local con las credenciales entregadas por el responsable
# del proyecto. Los archivos de entorno no se versionan.
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

La documentación interactiva queda en `http://127.0.0.1:8001/docs`. Se usa
el puerto 8001 para evitar conflictos con otros servicios locales y coincidir
con la configuración de desarrollo de Flutter.

Primero ejecuta los scripts `sql/001_*.sql` a `sql/011_*.sql`, en orden, en el
SQL Editor de Supabase. El último crea la auditoría no destructiva de
coordenadas y puntos de acceso. Completa `.env` después. La
`SUPABASE_SERVICE_ROLE_KEY` nunca debe
incluirse en Flutter, Git ni un bundle móvil.

El archivo `.env` de desarrollo está ignorado por Git. En despliegue, sus
valores deben configurarse como secretos del proveedor y nunca copiarse dentro
de la imagen Docker.

## Flujo de una evidencia

1. `POST /api/v1/uploads/presign`.
2. Flutter hace `PUT` de la imagen a la URL recibida.
3. `POST /api/v1/evidences` con la referencia y un UUID generado en el móvil.
4. `POST /api/v1/evidences/{id}/process`.
5. `GET /api/v1/evidences/{id}` hasta recibir el resultado preliminar.

Todos los endpoints, salvo `/health`, requieren `Authorization: Bearer <JWT>`.

## Prueba temporal de presencia

- `POST /api/v1/presence/samples` sincroniza hasta 100 muestras del dispositivo.
- `GET /api/v1/presence/recent` devuelve únicamente muestras aún vigentes.
- Cada punto conserva su fecha original y vence individualmente a las 24 horas.
- Al crear una evidencia, el backend calcula `confirmed`, `partial`,
  `not_confirmed` o `unavailable` usando distancia, precisión y señales de GPS
  simulado.
- Abrir nuevamente la app agrega una muestra; nunca extiende la vigencia de
  una visita anterior.
- El backend elimina puntos con más de 72 horas durante la sincronización. En
  producción debe programarse además la misma limpieza diariamente en Supabase
  Cron para cubrir cuentas que dejen de sincronizar. La evidencia mantiene solo
  el resumen auditable de la constatación.

La presencia demuestra que el dispositivo estuvo aproximadamente cerca, no
que la fotografía se tomó necesariamente en ese momento. Es una señal del
componente de integridad y nunca causa rechazo automático por sí sola.

El adaptador del modelo usa `POST /predict` con `multipart/form-data`
(`file`, `lat`, `lon`, `alt`). El timeout admite un arranque en frío de hasta
cinco minutos; si se excede o falla la conexión, la evidencia se conserva y
pasa a revisión humana en vez de marcarse como perdida.

## Trazabilidad del procesamiento

`processing_events` conserva eventos append-only de recepción, cola, IA visual,
validación geoespacial, decisión y revisión humana. El panel administrativo
muestra fecha, estado, duración, explicación y metadatos de cada etapa; la app
móvil traduce ese historial a cuatro pasos comprensibles para el viajero.

## Revisión administrativa

Los usuarios con `app_metadata.role=admin` pueden consumir:

- `GET /api/v1/admin/reviews`: candidatos y casos dudosos pendientes.
- `GET /api/v1/admin/reviews/{id}`: evidencia completa y fotografía firmada.
- `PATCH /api/v1/admin/reviews/{id}`: validar o rechazar con categoría y motivo.

Cada decisión se agrega a `validation_results` con fuente `manual_review`; no
se sobrescribe el historial emitido por el modelo.

## Conexión con Flutter

La app envía el JWT de Supabase Auth al backend y se configura con:

```bash
flutter run --dart-define-from-file=config/env/production.json
```

Los scripts SQL son incrementales e idempotentes. Deben ejecutarse en orden y
no eliminan evidencias existentes.

La biblioteca personal usa `GET` y `PUT /api/v1/me/travel/state`. Flutter
trabaja primero con la copia local y reintenta la sincronización cuando vuelve
la conexión; los datos siempre quedan aislados por el usuario autenticado.
La migración `010` permite guardar varias rutas personales y agrega reportes
recientes de condición/acceso únicamente a visitas comprobadas por GPS.

## Calidad de coordenadas

La migración `011_coordinate_quality_audit.sql` marca como referenciales los
puntos repetidos del catálogo sin mover la coordenada original. Crea una cola
administrativa separada donde Google Places aporta candidatos, nunca decisiones
automáticas. Un administrador puede aprobar una corrección del atractivo,
guardar únicamente un punto de acceso o mantener el caso como referencial. Las
rutas usan el acceso aprobado cuando existe; el mapa conserva la ubicación
física del atractivo y todo cambio queda trazado en la base de datos.

## Procesamiento asíncrono

La primera versión usa `BackgroundTasks` de FastAPI para validar el contrato de
extremo a extremo. Antes de producción se debe ejecutar `ValidationWorkflow`
desde un worker persistente (por ejemplo, ARQ/Celery) para conservar reintentos
aunque la API se reinicie. La tabla `validation_jobs` ya deja preparado ese
cambio.

## Sentinel y PerúSAT

`SENTINEL_ENABLED=true` consulta el catálogo STAC oficial. Con
`SENTINEL_CLIENT_ID` y `SENTINEL_CLIENT_SECRET` también usa la Statistical API
para calcular NDVI, NDWI, NDSI y BSI, excluyendo nubes y usando una serie
temporal. El DEM Copernicus GLO-90 aporta elevación, relieve y pendiente
estimada. Estas señales pueden confirmar, ser inconclusas o contradecir; una
contradicción deriva a revisión y nunca rechaza automáticamente. PerúSAT queda
como corroboración posterior opcional.

Los pesos y umbrales son heurísticos iniciales configurables mediante
`DECISION_RULE_VERSION`, `CANDIDATE_SCORE_THRESHOLD` y
`MINIMUM_EVIDENCE_COVERAGE`. Deben calibrarse con datos etiquetados.

## Google Maps Platform

El backend requiere una clave de servidor independiente con **Places API
(New)** y **Routes API** habilitadas. Las claves nativas de iOS y Android deben
ser distintas y limitarse a los SDK de mapas y a sus respectivos identificadores
de aplicación.

## Pruebas

```bash
pytest
```

## Despliegue temporal para pruebas

El repositorio incluye `Dockerfile` y `render.yaml`. En Render se crea un Web
Service Docker y se configura `/api/v1/health` como health check. Los secretos
de `.env` se copian en la sección Environment del proveedor; `.env` nunca se
sube al repositorio ni se copia a la imagen.

Después del primer despliegue:

1. Comprueba `https://<servicio>/api/v1/health`.
2. Crea `config/env/production.json` en Flutter usando esa URL con `/api/v1`.
3. Genera el APK con
   `flutter build apk --release --dart-define-from-file=config/env/production.json`.

Para una prueba cerrada el APK puede usar la firma de depuración existente. La
publicación en Play Store requiere cambiar el identificador
`com.example.turismo_app` y crear un keystore de carga propio.

