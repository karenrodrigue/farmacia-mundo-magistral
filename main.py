

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from security import usuario_actual, permitir_roles

app = FastAPI(
    title="Farmacia Mundo Magistral",
    description="Sistema Web de Ventas e Inventario",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://farmacia-mundo-magistral-frontend.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def inicio():
    return {
        "mensaje": "Bienvenido a Farmacia Mundo Magistral",
        "estado": "Backend funcionando correctamente"
    }

from database import engine
from sqlalchemy import text

@app.get("/productos")
def listar_productos(
    usuario=Depends(permitir_roles("ADMINISTRADOR", "ALMACEN", "VENDEDOR"))
):

    with engine.connect() as conexion:
        resultado = conexion.execute(
            text("""
                SELECT id_producto, codigo, nombre,
                       precio_compra, precio_venta,
                       stock_actual, stock_minimo
                FROM public.products
                ORDER BY id_producto
            """)
        )

        productos = [
            dict(fila._mapping)
            for fila in resultado
        ]

        return {
            "total": len(productos),
            "productos": productos
        }

from pydantic import BaseModel, Field
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

class ProductoCrear(BaseModel):
    codigo: str
    nombre: str
    precio_compra: float = Field(ge=0)
    precio_venta: float = Field(ge=0)
    stock_minimo: int = Field(ge=0)

@app.post("/productos", status_code=201)

def crear_producto(
    producto: ProductoCrear,
    usuario=Depends(permitir_roles("ADMINISTRADOR", "ALMACEN"))
):

    try:
        with engine.begin() as conexion:
            resultado = conexion.execute(
                text("""
                    INSERT INTO public.products
                    (codigo, nombre, precio_compra,
                     precio_venta, stock_minimo)
                    VALUES
                    (:codigo, :nombre, :precio_compra,
                     :precio_venta, :stock_minimo)
                    RETURNING id_producto, codigo, nombre
                """),
                producto.model_dump()
            )

            nuevo = dict(resultado.mappings().one())

        return {
            "mensaje": "Producto registrado correctamente",
            "producto": nuevo
        }

    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="El codigo del producto ya existe"
        )

class ProveedorCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    nit: str | None = None
    telefono: str | None = None
    direccion: str | None = None
    correo: str | None = None


@app.get("/proveedores")

def listar_proveedores(
    usuario=Depends(permitir_roles("ADMINISTRADOR", "ALMACEN"))
):

    with engine.connect() as conexion:
        resultado = conexion.execute(
            text("""
                SELECT id_proveedor, nombre, nit,
                       telefono, direccion, correo
                FROM public.suppliers
                ORDER BY id_proveedor
            """)
        )

        proveedores = [
            dict(fila._mapping)
            for fila in resultado
        ]

        return {
            "total": len(proveedores),
            "proveedores": proveedores
        }


@app.post("/proveedores", status_code=201)

def crear_proveedor(
    proveedor: ProveedorCrear,
    usuario=Depends(permitir_roles("ADMINISTRADOR", "ALMACEN"))
):

    try:
        with engine.begin() as conexion:
            resultado = conexion.execute(
                text("""
                    INSERT INTO public.suppliers
                    (nombre, nit, telefono, direccion, correo)
                    VALUES
                    (:nombre, :nit, :telefono, :direccion, :correo)
                    RETURNING id_proveedor, nombre, nit
                """),
                proveedor.model_dump()
            )

            nuevo = dict(resultado.mappings().one())

        return {
            "mensaje": "Proveedor registrado correctamente",
            "proveedor": nuevo
        }

    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Ya existe un proveedor con ese NIT"
        )



from decimal import Decimal
from sqlalchemy.exc import SQLAlchemyError

class CompraCrear(BaseModel):
    id_proveedor: int = Field(gt=0)
    id_producto: int = Field(gt=0)
    cantidad: int = Field(gt=0)
    precio_unitario: Decimal = Field(ge=0, decimal_places=2)
    numero_factura: str | None = None


@app.post("/compras", status_code=201)

def registrar_compra(
    compra: CompraCrear,
    usuario=Depends(permitir_roles("ADMINISTRADOR", "ALMACEN"))
):

    try:
        with engine.begin() as conexion:

            proveedor = conexion.execute(
                text("""
                    SELECT id_proveedor
                    FROM public.suppliers
                    WHERE id_proveedor = :id
                      AND activo = TRUE
                """),
                {"id": compra.id_proveedor}
            ).first()

            if not proveedor:
                raise HTTPException(
                    status_code=404,
                    detail="Proveedor no encontrado"
                )

            producto = conexion.execute(
                text("""
                    SELECT id_producto, stock_actual,
                           precio_compra, costo_promedio
                    FROM public.products
                    WHERE id_producto = :id
                      AND activo = TRUE
                    FOR UPDATE
                """),
                {"id": compra.id_producto}
            ).mappings().first()

            if not producto:
                raise HTTPException(
                    status_code=404,
                    detail="Producto no encontrado"
                )

            stock_anterior = producto["stock_actual"]
            stock_nuevo = stock_anterior + compra.cantidad

            costo_anterior = producto["costo_promedio"]


            if costo_anterior == 0 and stock_anterior > 0:
                costo_anterior = producto["precio_compra"]
            costo_promedio = (
                (costo_anterior * stock_anterior)
                + (compra.precio_unitario * compra.cantidad)
            ) / stock_nuevo

            costo_promedio = costo_promedio.quantize(
                Decimal("0.01")
            )

            total = compra.precio_unitario * compra.cantidad

            resultado = conexion.execute(
                text("""
                    INSERT INTO public.purchases
                    (id_proveedor, numero_factura, total, estado)
                    VALUES
                    (:proveedor, :factura, :total, 'CONFIRMADA')
                    RETURNING id_compra
                """),
                {
                    "proveedor": compra.id_proveedor,
                    "factura": compra.numero_factura,
                    "total": total
                }
            )

            id_compra = resultado.scalar_one()

            conexion.execute(
                text("""
                    INSERT INTO public.purchase_items
                    (id_compra, id_producto, cantidad,
                     precio_unitario)
                    VALUES
                    (:compra, :producto, :cantidad, :precio)
                """),
                {
                    "compra": id_compra,
                    "producto": compra.id_producto,
                    "cantidad": compra.cantidad,
                    "precio": compra.precio_unitario
                }
            )

            conexion.execute(
                text("""
                    UPDATE public.products
                    SET stock_actual = :stock,
                        precio_compra = :costo,
                        costo_promedio = :costo
                    WHERE id_producto = :producto
                """),
                {
                    "stock": stock_nuevo,
                    "costo": costo_promedio,
                    "producto": compra.id_producto
                }
            )

            conexion.execute(
                text("""
                    INSERT INTO public.inventory_movements
                    (id_producto, id_usuario, tipo_movimiento, cantidad,
                     cantidad_previa, cantidad_final,
                     observaciones)
                    VALUES
                    (:producto, :usuario, 'ENTRADA', :cantidad,
                     :anterior, :final, :observaciones)
                """),
                {
                    "producto": compra.id_producto,
                    "usuario": usuario["id_usuario"],
                    "cantidad": compra.cantidad,
                    "anterior": stock_anterior,
                    "final": stock_nuevo,
                    "observaciones": f"Compra Nro. {id_compra}"
                }
            )

        return {
            "mensaje": "Compra registrada correctamente",
            "id_compra": id_compra,
            "stock_anterior": stock_anterior,
            "stock_actual": stock_nuevo,
            "costo_promedio": costo_promedio,
            "total": total
        }

    except HTTPException:
        raise

    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="No se pudo registrar la compra"
        )

class VentaCrear(BaseModel):
    id_producto: int = Field(gt=0)
    cantidad: int = Field(gt=0)
    id_cliente: int | None = None


@app.post("/ventas", status_code=201)

def registrar_venta(
    venta: VentaCrear,
    usuario=Depends(permitir_roles("ADMINISTRADOR", "VENDEDOR"))
):

    try:
        with engine.begin() as conexion:

            if venta.id_cliente is not None:
                cliente = conexion.execute(
                    text("""
                        SELECT id_cliente
                        FROM public.customers
                        WHERE id_cliente = :id
                          AND activo = TRUE
                    """),
                    {"id": venta.id_cliente}
                ).first()

                if not cliente:
                    raise HTTPException(
                        status_code=404,
                        detail="Cliente no encontrado"
                    )

            producto = conexion.execute(
                text("""
                    SELECT id_producto, nombre,
                           stock_actual, precio_venta
                    FROM public.products
                    WHERE id_producto = :id
                      AND activo = TRUE
                    FOR UPDATE
                """),
                {"id": venta.id_producto}
            ).mappings().first()

            if not producto:
                raise HTTPException(
                    status_code=404,
                    detail="Producto no encontrado"
                )

            stock_anterior = producto["stock_actual"]

            if stock_anterior < venta.cantidad:
                raise HTTPException(
                    status_code=400,
                    detail="Stock insuficiente"
                )

            stock_nuevo = stock_anterior - venta.cantidad
            precio = producto["precio_venta"]
            total = precio * venta.cantidad

            resultado = conexion.execute(
                text("""
                    INSERT INTO public.sales
                    (id_cliente, total, estado)
                    VALUES
                    (:cliente, :total, 'CONFIRMADA')
                    RETURNING id_venta
                """),
                {
                    "cliente": venta.id_cliente,
                    "total": total
                }
            )

            id_venta = resultado.scalar_one()

            conexion.execute(
                text("""
                    INSERT INTO public.sale_items
                    (id_venta, id_producto, cantidad,
                     precio_unitario)
                    VALUES
                    (:venta, :producto, :cantidad, :precio)
                """),
                {
                    "venta": id_venta,
                    "producto": venta.id_producto,
                    "cantidad": venta.cantidad,
                    "precio": precio
                }
            )

            conexion.execute(
                text("""
                    UPDATE public.products
                    SET stock_actual = :stock
                    WHERE id_producto = :producto
                """),
                {
                    "stock": stock_nuevo,
                    "producto": venta.id_producto
                }
            )

            conexion.execute(
                text("""
                    INSERT INTO public.inventory_movements
                    (id_producto, id_usuario, tipo_movimiento, cantidad,
                     cantidad_previa, cantidad_final,
                     observaciones)
                    VALUES
                    (:producto, :usuario, 'SALIDA', :cantidad,
                     :anterior, :final, :observaciones)
                """),
                {
                    "producto": venta.id_producto,
                    "usuario": usuario["id_usuario"],
                    "cantidad": venta.cantidad,
                    "anterior": stock_anterior,
                    "final": stock_nuevo,
                    "observaciones": f"Venta Nro. {id_venta}"
                }
            )

        return {
            "mensaje": "Venta registrada correctamente",
            "id_venta": id_venta,
            "producto": producto["nombre"],
            "cantidad": venta.cantidad,
            "stock_anterior": stock_anterior,
            "stock_actual": stock_nuevo,
            "total": total
        }

    except HTTPException:
        raise

    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="No se pudo registrar la venta"
        )

class ClienteCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=150)
    documento_identidad: str | None = None
    telefono: str | None = None
    direccion: str | None = None
    correo: str | None = None


@app.get("/clientes")
def listar_clientes(
    usuario=Depends(permitir_roles("ADMINISTRADOR", "VENDEDOR"))
):

    with engine.connect() as conexion:
        resultado = conexion.execute(
            text("""
                SELECT id_cliente, nombre,
                       documento_identidad,
                       telefono, direccion, correo
                FROM public.customers
                WHERE activo = TRUE
                ORDER BY id_cliente
            """)
        )

        clientes = [
            dict(fila._mapping)
            for fila in resultado
        ]

        return {
            "total": len(clientes),
            "clientes": clientes
        }


@app.post("/clientes", status_code=201)
def crear_cliente(
    cliente: ClienteCrear,
    usuario=Depends(permitir_roles("ADMINISTRADOR", "VENDEDOR"))
):
  
    try:
        with engine.begin() as conexion:
            resultado = conexion.execute(
                text("""
                    INSERT INTO public.customers
                    (nombre, documento_identidad,
                     telefono, direccion, correo)
                    VALUES
                    (:nombre, :documento_identidad,
                     :telefono, :direccion, :correo)
                    RETURNING id_cliente, nombre
                """),
                cliente.model_dump()
            )

            nuevo = dict(resultado.mappings().one())

        return {
            "mensaje": "Cliente registrado correctamente",
            "cliente": nuevo
        }

    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Ya existe un cliente con ese documento"
        )

from datetime import date, timedelta


class LoteCrear(BaseModel):
    id_producto: int = Field(gt=0)
    numero_lote: str = Field(min_length=1, max_length=50)
    fecha_vencimiento: date


@app.get("/lotes")
def listar_lotes(
    usuario=Depends(permitir_roles("ADMINISTRADOR", "ALMACEN", "VENDEDOR"))
):

    with engine.connect() as conexion:
        resultado = conexion.execute(
            text("""
                SELECT b.id_lote, b.id_producto,
                       p.nombre AS producto,
                       b.numero_lote,
                       b.fecha_vencimiento,
                       b.stock_lote
                FROM public.product_batches b
                JOIN public.products p
                  ON p.id_producto = b.id_producto
                ORDER BY b.fecha_vencimiento
            """)
        )

        return [
            dict(fila._mapping)
            for fila in resultado
        ]


@app.post("/lotes", status_code=201)
def crear_lote(
    lote: LoteCrear,
    usuario=Depends(permitir_roles("ADMINISTRADOR", "ALMACEN"))
):

    if lote.fecha_vencimiento <= date.today():
        raise HTTPException(
            status_code=400,
            detail="La fecha de vencimiento debe ser futura"
        )

    try:
        with engine.begin() as conexion:
            producto = conexion.execute(
                text("""
                    SELECT id_producto
                    FROM public.products
                    WHERE id_producto = :id
                      AND activo = TRUE
                """),
                {"id": lote.id_producto}
            ).first()

            if not producto:
                raise HTTPException(
                    status_code=404,
                    detail="Producto no encontrado"
                )

            resultado = conexion.execute(
                text("""
                    INSERT INTO public.product_batches
                    (id_producto, numero_lote,
                     fecha_vencimiento, stock_lote)
                    VALUES
                    (:id_producto, :numero_lote,
                     :fecha_vencimiento, 0)
                    RETURNING id_lote
                """),
                lote.model_dump()
            )

            id_lote = resultado.scalar_one()

        return {
            "mensaje": "Lote registrado correctamente",
            "id_lote": id_lote
        }

    except IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="El numero de lote ya existe para este producto"
        )


@app.get("/lotes/proximos-vencer")
def lotes_proximos_vencer(
    usuario=Depends(permitir_roles("ADMINISTRADOR", "ALMACEN", "VENDEDOR"))
):

    fecha_limite = date.today() + timedelta(days=90)

    with engine.connect() as conexion:
        resultado = conexion.execute(
            text("""
                SELECT b.numero_lote, p.nombre AS producto,
                       b.fecha_vencimiento, b.stock_lote
                FROM public.product_batches b
                JOIN public.products p
                  ON p.id_producto = b.id_producto
                WHERE b.fecha_vencimiento
                      BETWEEN CURRENT_DATE AND :limite
                  AND b.stock_lote > 0
                ORDER BY b.fecha_vencimiento
            """),
            {"limite": fecha_limite}
        )

        return [
            dict(fila._mapping)
            for fila in resultado
        ]



@app.get("/mi-perfil")
def mi_perfil(usuario=Depends(usuario_actual)):
    return {
        "mensaje": "Usuario autenticado correctamente",
        "usuario": usuario
    }


import os
import requests
from dotenv import load_dotenv

load_dotenv()

class LoginDatos(BaseModel):
    correo: str
    password: str


@app.post("/login")
def iniciar_sesion(datos: LoginDatos):
    url = os.getenv("SUPABASE_URL")
    clave = os.getenv("SUPABASE_PUBLISHABLE_KEY")

    if not url or not clave:
        raise HTTPException(
            status_code=500,
            detail="Falta configurar Supabase Auth"
        )

    try:
        respuesta = requests.post(
            f"{url.rstrip('/')}/auth/v1/token",
            params={"grant_type": "password"},
            headers={
                "apikey": clave,
                "Content-Type": "application/json"
            },
            json={
                "email": datos.correo,
                "password": datos.password
            },
            timeout=15
        )
    except requests.RequestException:
        raise HTTPException(
            status_code=503,
            detail="No se pudo contactar con Supabase Auth"
        )

    if respuesta.status_code != 200:
        
        print("Error de Supabase Auth:", respuesta.status_code)
        print("Tipo de error:", respuesta.json().get("error_code", "No especificado"))

        raise HTTPException(
            status_code=401,
            detail="Credenciales incorrectas"
        )

    sesion = respuesta.json()

    return {
        "access_token": sesion["access_token"],
        "token_type": "bearer"
    }



from pathlib import Path
from fastapi import Header
from fastapi.responses import FileResponse


@app.get("/recuperar")
def pagina_recuperacion():
    archivo = Path(__file__).parent / "recuperar.html"
    return FileResponse(archivo)


class NuevaPassword(BaseModel):
    password: str = Field(min_length=12)


@app.post("/auth/recuperar-password")
def recuperar_password(
    datos: NuevaPassword,
    authorization: str = Header()
):
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Token de recuperación requerido"
        )

    token = authorization.removeprefix("Bearer ").strip()

    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    clave = os.getenv("SUPABASE_PUBLISHABLE_KEY")

    if not url or not clave:
        raise HTTPException(
            status_code=500,
            detail="Falta configurar Supabase"
        )

    try:
        respuesta = requests.put(
            f"{url}/auth/v1/user",
            headers={
                "apikey": clave,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            json={"password": datos.password},
            timeout=15
        )
    except requests.RequestException:
        raise HTTPException(
            status_code=503,
            detail="Servicio de autenticación no disponible"
        )

    if respuesta.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail="Sesión inválida o vencida"
        )

    return {
        "mensaje": "Contraseña actualizada correctamente"
    }

class SolicitarRecuperacion(BaseModel):
    correo: str


@app.post("/solicitar-recuperacion")
def solicitar_recuperacion(datos: SolicitarRecuperacion):
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    clave = os.getenv("SUPABASE_PUBLISHABLE_KEY")

    if not url or not clave:
        raise HTTPException(
            status_code=500,
            detail="Falta configurar Supabase Auth"
        )

    try:
        requests.post(
            f"{url}/auth/v1/recover",
            params={
                "redirect_to": "http://127.0.0.1:8000/recuperar"
            },
            headers={
                "apikey": clave,
                "Content-Type": "application/json"
            },
            json={"email": datos.correo},
            timeout=15
        )
    except requests.RequestException:
        pass

    return {
        "mensaje": "Si el correo está registrado, recibirás instrucciones de recuperación."
    }


# Kardex: consulta de movimientos con identificación del responsable.
@app.get("/kardex")
def consultar_kardex(
    id_producto: int | None = None,
    usuario=Depends(permitir_roles("ADMINISTRADOR", "ALMACEN"))
):
    with engine.connect() as conexion:
        movimientos = conexion.execute(
            text("""
                SELECT m.id_movimiento, m.id_producto,
                       p.nombre AS producto, m.id_usuario,
                       u.nombre AS responsable, m.tipo_movimiento,
                       m.cantidad, m.cantidad_previa, m.cantidad_final,
                       m.observaciones, m.fecha_movimiento
                FROM public.inventory_movements AS m
                JOIN public.products AS p ON p.id_producto = m.id_producto
                LEFT JOIN public.users AS u ON u.id_usuario = m.id_usuario
                WHERE (:producto IS NULL OR m.id_producto = :producto)
                ORDER BY m.fecha_movimiento DESC, m.id_movimiento DESC
            """),
            {"producto": id_producto}
        ).mappings().all()
    return {"total": len(movimientos),
            "movimientos": [dict(m) for m in movimientos]}


# Ajuste inventario: fija el stock contado y conserva la trazabilidad.
class AjusteInventario(BaseModel):
    id_producto: int = Field(gt=0)
    stock_contado: int = Field(ge=0)
    motivo: str = Field(min_length=5, max_length=300)


@app.post("/inventario/ajustes", status_code=201)
def ajustar_inventario(
    ajuste: AjusteInventario,
    usuario=Depends(permitir_roles("ADMINISTRADOR", "ALMACEN"))
):
    with engine.begin() as conexion:
        producto = conexion.execute(
            text("""
                SELECT id_producto, nombre, stock_actual
                FROM public.products
                WHERE id_producto = :id AND activo = TRUE
                FOR UPDATE
            """),
            {"id": ajuste.id_producto}
        ).mappings().first()
        if producto is None:
            raise HTTPException(status_code=404, detail="Producto no encontrado")

        stock_anterior = producto["stock_actual"]
        diferencia = ajuste.stock_contado - stock_anterior
        if diferencia == 0:
            raise HTTPException(status_code=400,
                                detail="No hay diferencia de inventario que ajustar")

        conexion.execute(
            text("""
                UPDATE public.products SET stock_actual = :nuevo
                WHERE id_producto = :id
            """),
            {"nuevo": ajuste.stock_contado, "id": ajuste.id_producto}
        )
        movimiento = conexion.execute(
            text("""
                INSERT INTO public.inventory_movements
                (id_producto, id_usuario, tipo_movimiento, cantidad,
                 cantidad_previa, cantidad_final, observaciones)
                VALUES (:producto, :usuario, 'AJUSTE', :cantidad,
                        :anterior, :final, :motivo)
                RETURNING id_movimiento
            """),
            {
                "producto": ajuste.id_producto,
                "usuario": usuario["id_usuario"],
                "cantidad": abs(diferencia),
                "anterior": stock_anterior,
                "final": ajuste.stock_contado,
                "motivo": ajuste.motivo
            }
        ).scalar_one()

    return {
        "mensaje": "Ajuste de inventario registrado",
        "id_movimiento": movimiento,
        "id_producto": ajuste.id_producto,
        "stock_anterior": stock_anterior,
        "stock_actual": ajuste.stock_contado,
        "diferencia": diferencia,
        "responsable": usuario["nombre"]
    }
