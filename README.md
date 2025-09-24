🩺 App de Pacientes (Carmen)

Aplicación para buscar pacientes, registrar mediciones por cita (% grasa, % músculo, peso y medidas) y abrir la carpeta de fotos en Google Drive.

Interfaz: Streamlit

Local: SQLite (data/patients.db)

Nube: Postgres (Neon/Supabase/Render/Railway)

📁 Estructura del proyecto
tu_app_pacientes/
├─ app.py
├─ init_db.py                # crea BD local (SQLite) solo en modo local
├─ requirements.txt
├─ README.md
├─ .gitignore
└─ (opcional) /data/        # NO subir a Git; aquí vive patients.db (local)


Si trabajas en nube + Postgres, NO necesitas /data/ ni patients.db.

🔧 Requisitos

Python 3.10+

(Local) SQLite ya viene con Python (import sqlite3)

(Nube) Una cuenta en Streamlit Cloud y Neon (o similar)

▶️ Correr en local (SQLite)

Crear entorno e instalar dependencias:

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt


Crear la BD local:

python init_db.py


Ejecutar la app:

streamlit run app.py


Se abre en: http://localhost:8501

☁️ Desplegar en la nube (Streamlit Cloud + Postgres/Neon)
1) Crear Postgres en Neon

Crea proyecto en https://neon.tech

Obtén tu DATABASE_URL (ej.):
postgresql://usuario:password@host.neon.tech/neondb

2) Crear tablas (en la consola SQL de Neon)
CREATE TABLE IF NOT EXISTS pacientes (
  id SERIAL PRIMARY KEY,
  nombre TEXT NOT NULL UNIQUE,
  edad INT,
  telefono TEXT,
  notas TEXT,
  carpeta_drive TEXT
);

CREATE TABLE IF NOT EXISTS mediciones (
  id SERIAL PRIMARY KEY,
  paciente_id INT NOT NULL REFERENCES pacientes(id) ON DELETE CASCADE,
  fecha DATE NOT NULL,
  grasa REAL,
  musculo REAL,
  peso REAL,
  brazo REAL,
  pecho REAL,
  cintura REAL,
  cadera REAL,
  pierna REAL,
  pantorrilla REAL,
  brazo_descanso REAL,
  pecho_descanso REAL,
  notas TEXT,
  UNIQUE(paciente_id, fecha)
);

3) Preparar el repo

Asegúrate de tener en requirements.txt:

streamlit
pandas
openpyxl
psycopg[binary]
python-dotenv


NO subas /data/ ni patients.db (usa el .gitignore).

4) Subir a GitHub
git init
git add .
git commit -m "App de Pacientes - primera versión"
git branch -M main
git remote add origin <URL-de-tu-repo>
git push -u origin main

5) Configurar Streamlit Cloud

Ve a https://share.streamlit.io
 → New app → conecta tu repo → app.py.

En Settings → Secrets agrega:

DATABASE_URL = "postgresql://usuario:password@host.neon.tech/neondb"


Deploy → obtendrás un link público para usar en PC/laptop/tablet.

🧩 Notas de uso

Link de Drive: la tabla usa LinkColumn para que la columna de fotos sea clicable.

Columna de descanso/fuerza: la tabla mediciones incluye brazo, pecho (fuerza) y brazo_descanso, pecho_descanso (descanso).

Confidencialidad: guarda DATABASE_URL solo en Secrets (no en el código).

🔁 Migración de datos locales → Postgres (opcional)

Si tienes datos en data/patients.db y quieres subirlos a la nube, crea un script y ejecuta:

pip install psycopg[binary]
set DATABASE_URL=postgresql://usuario:password@host.neon.tech/neondb  # Windows
# export DATABASE_URL=...                                          # macOS/Linux
python export_local_to_postgres.py


(El script debe leer pacientes y mediciones de SQLite e insertarlos en Postgres con ON CONFLICT.)

🛠️ Troubleshooting

La app corre local pero no en la nube: revisa Settings → Secrets en Streamlit Cloud.

Error de conexión a Postgres: valida que la DATABASE_URL sea la correcta y que tu plan permita conexiones.

Links de Drive no clicables: asegúrate de usar st.column_config.LinkColumn y pasar la URL cruda, no Markdown.

📜 Licencia

Proyecto de uso interno. Ajusta la licencia si planeas compartirlo.