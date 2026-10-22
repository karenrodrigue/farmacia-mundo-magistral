
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

load_dotenv()

database_url = URL.create(
    drivername="postgresql+psycopg2",
    username=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", "5432")),
    database=os.getenv("DB_NAME", "postgres"),
    query={"sslmode": "require"}
)

engine = create_engine(database_url, pool_pre_ping=True)

def probar_conexion():
    try:
        with engine.connect() as conexion:
            resultado = conexion.execute(
                text("SELECT current_database()")
            )
            print("Conexion exitosa con Supabase")
            print("Base de datos:", resultado.scalar())
    except Exception as error:
        print("Error al conectar con Supabase")
        print(type(error).__name__)

def verificar_tablas():
    with engine.connect() as conexion:
        resultado = conexion.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """))

        print("TABLAS DE FARMACIA MUNDO MAGISTRAL:")
        for fila in resultado:
            print("-", fila[0])
