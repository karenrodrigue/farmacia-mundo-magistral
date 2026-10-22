import os
import jwt

from dotenv import load_dotenv
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt import PyJWKClient
from sqlalchemy import text

from database import engine

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")

if not SUPABASE_URL:
    raise RuntimeError("Falta SUPABASE_URL en el archivo .env")

jwks_client = PyJWKClient(
    f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
)

bearer = HTTPBearer()


def usuario_actual(
    credenciales: HTTPAuthorizationCredentials = Depends(bearer)
):
    token = credenciales.credentials

    try:
        clave = jwks_client.get_signing_key_from_jwt(token)

        datos = jwt.decode(
            token,
            clave.key,
            algorithms=["RS256", "ES256"],
            audience="authenticated",
            issuer=f"{SUPABASE_URL}/auth/v1",
            options={"require": ["exp", "sub", "iss", "aud"]}
        )

        with engine.connect() as conexion:
            usuario = conexion.execute(
                text("""
                    SELECT id_usuario, nombre, rol
                    FROM public.users
                    WHERE auth_user_id = :uid
                      AND activo = TRUE
                """),
                {"uid": datos["sub"]}
            ).mappings().first()

        if not usuario:
            raise HTTPException(
                status_code=403,
                detail="Usuario sin permisos"
            )

        return dict(usuario)

    except HTTPException:
        raise

    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401,
            detail="Token invalido o vencido"
        )


def permitir_roles(*roles):
    def verificar(usuario=Depends(usuario_actual)):
        if usuario["rol"] not in roles:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para esta operacion"
            )
        return usuario

    return verificar
