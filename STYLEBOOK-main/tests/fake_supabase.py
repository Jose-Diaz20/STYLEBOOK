"""
Supabase simulada en memoria para probar los flujos de la app sin red.
Emula: encadenado de filtros, embeds (tabla(...) y tabla!inner(...)), rpc rangos_ocupados,
horas en formato 'HH:MM:SS' (como devuelve Postgres) y la restricción sin_cruces_horario.
Emula de los triggers solo lo imprescindible (proteger_profesional, validar_calificacion y el promedio
de calificaciones); NO emula la RLS: eso se prueba con tests/test_sql.mjs contra Postgres real.
"""
import re
import uuid
from datetime import datetime, timezone

from postgrest.exceptions import APIError

ACTIVAS = ("pendiente", "confirmada")
EMBEDS = {
    ("citas", "profesionales"): ("profesional_id", "profesionales"),
    ("citas", "servicios"): ("servicio_id", "servicios"),
    ("servicios", "profesionales"): ("profesional_id", "profesionales"),
}
COLUMNAS_HORA = ("hora_inicio", "hora_fin")


class Resp:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class FakeDB:
    def __init__(self):
        self.tablas = {n: [] for n in ("perfiles", "profesionales", "servicios",
                                       "horarios_profesional", "citas", "notificaciones",
                                       "calificaciones")}
        self.usuarios = []
        self.exigir_confirmacion = False

    def agregar_usuario(self, email, password, nombre, rol="cliente"):
        uid = str(uuid.uuid4())
        self.usuarios.append({"id": uid, "email": email, "password": password,
                              "meta": {"nombre": nombre}})
        self.tablas["perfiles"].append({"id": uid, "nombre": nombre, "telefono": None, "rol": rol})
        return uid

    def insertar(self, tabla, **campos):
        if tabla == "profesionales":
            campos.setdefault("activo", True)   # default de la columna (HU-10)
        fila = {"id": str(uuid.uuid4()), **campos}
        self.tablas[tabla].append(_normalizar(fila))
        return fila["id"]


def _normalizar(fila):
    for c in COLUMNAS_HORA:
        if c in fila and isinstance(fila[c], str) and len(fila[c]) == 5:
            fila[c] += ":00"
    return fila


def _t(v):
    return datetime.strptime(v[:5], "%H:%M").time()


class Q:
    def __init__(self, db, tabla):
        self.db, self.tabla = db, tabla
        self.op, self.payload, self.cols, self.pedir_conteo = "select", None, "*", False
        self.filtros, self.orden, self.tope = [], [], None

    def select(self, cols="*", count=None):
        self.op, self.cols, self.pedir_conteo = "select", cols, bool(count)
        return self

    def insert(self, d): self.op, self.payload = "insert", d; return self
    def update(self, d): self.op, self.payload = "update", d; return self
    def delete(self): self.op = "delete"; return self
    def eq(self, c, v): self.filtros.append((c, "eq", v)); return self
    def neq(self, c, v): self.filtros.append((c, "neq", v)); return self
    def in_(self, c, v): self.filtros.append((c, "in", v)); return self
    def order(self, c, desc=False): self.orden.append((c, desc)); return self
    def limit(self, n): self.tope = n; return self

    # -- helpers --
    def _coincide(self, fila, filtros):
        for c, op, v in filtros:
            x = fila.get(c)
            if op == "eq" and str(x) != str(v): return False
            if op == "neq" and str(x) == str(v): return False
            if op == "in" and x not in v: return False
        return True

    def _embeber(self, filas):
        salida = []
        for f in filas:
            f = dict(f)
            drop = False
            for nombre, inner in re.findall(r"(\w+)(!inner)?\(", self.cols):
                clave = EMBEDS.get((self.tabla, nombre))
                if not clave: continue
                fk, destino = clave
                rel = next((r for r in self.db.tablas[destino] if r["id"] == f.get(fk)), None)
                if rel is not None:
                    dot = [(c.split(".", 1)[1], op, v) for c, op, v in self.filtros if c.startswith(nombre + ".")]
                    if not self._coincide(rel, dot):
                        rel = None
                f[nombre] = dict(rel) if rel else None
                if inner and rel is None: drop = True
            if not drop: salida.append(f)
        return salida

    def _cruce(self, fila, ignorar_id=None):
        if fila.get("estado", "confirmada") not in ACTIVAS: return
        for o in self.db.tablas["citas"]:
            if o["id"] == ignorar_id or o["estado"] not in ACTIVAS: continue
            if o["profesional_id"] == fila["profesional_id"] and o["fecha"] == fila["fecha"] \
               and _t(fila["hora_inicio"]) < _t(o["hora_fin"]) and _t(fila["hora_fin"]) > _t(o["hora_inicio"]):
                raise APIError({"message": 'conflicting key value violates exclusion constraint "sin_cruces_horario"',
                                "code": "23P01", "details": None, "hint": None})

    def _calificar(self, fila):
        """Emula validar_calificacion() + actualizar_promedio_proveedor() + las restricciones de la tabla."""
        def error(msg, codigo="P0001"):
            return APIError({"message": msg, "code": codigo, "details": None, "hint": None})

        if not isinstance(fila.get("puntuacion"), int) or not 1 <= fila["puntuacion"] <= 5:
            raise error('new row violates check constraint "calificaciones_puntuacion_check"', "23514")
        if fila.get("comentario") and len(fila["comentario"]) > 1000:
            raise error('new row violates check constraint "calificaciones_comentario_check"', "23514")
        cita = next((c for c in self.db.tablas["citas"] if c["id"] == fila.get("cita_id")), None)
        if cita is None:
            raise error("SB: La cita no existe.")
        if fila.get("cliente_id") != cita["cliente_id"]:
            raise error("SB: Solo puedes calificar tus propias citas.")
        if cita["estado"] != "completada":
            raise error("SB: Solo puedes calificar citas completadas.")
        if any(k["cita_id"] == cita["id"] for k in self.db.tablas["calificaciones"]):
            raise error('duplicate key value violates unique constraint "calificaciones_una_por_cita"', "23505")

        perfil = next((p for p in self.db.tablas["perfiles"] if p["id"] == cita["cliente_id"]), {})
        partes = (perfil.get("nombre") or "").split()
        fila["cliente_nombre"] = ("Cliente" if not partes else partes[0] if len(partes) == 1
                                  else f"{partes[0]} {partes[1][0].upper()}.")
        servicio = next((x for x in self.db.tablas["servicios"] if x["id"] == cita["servicio_id"]), {})
        fila["servicio_nombre"] = servicio.get("nombre")
        fila["profesional_id"] = cita["profesional_id"]
        fila["comentario"] = (fila.get("comentario") or "").strip() or None
        if fila.get("creado_en") in (None, "now"):
            fila["creado_en"] = datetime.now(timezone.utc).isoformat()
        # el promedio se recalcula con la nueva fila incluida (trigger AFTER INSERT)
        puntos = [k["puntuacion"] for k in self.db.tablas["calificaciones"]
                  if k["profesional_id"] == fila["profesional_id"]] + [fila["puntuacion"]]
        for pro in self.db.tablas["profesionales"]:
            if pro["id"] == fila["profesional_id"]:
                pro["calificacion_promedio"] = round(sum(puntos) / len(puntos), 2)
                pro["total_calificaciones"] = len(puntos)

    def execute(self):
        tabla = self.db.tablas[self.tabla]
        simples = [f for f in self.filtros if "." not in f[0]]
        if self.op == "insert":
            fila = {"id": str(uuid.uuid4()), "creado_en": "now", **self.payload}
            if self.tabla == "citas": fila.setdefault("estado", "pendiente"); self._cruce(_normalizar(fila))
            if self.tabla == "notificaciones": fila.setdefault("leida", False)
            if self.tabla == "servicios": fila.setdefault("activo", True)
            if self.tabla == "profesionales": fila["estado"] = "pendiente"; fila.setdefault("activo", True)   # trigger proteger_profesional + default de activo
            if self.tabla == "calificaciones": self._calificar(fila)
            tabla.append(_normalizar(fila))
            return Resp([dict(fila)])
        filas = [f for f in tabla if self._coincide(f, simples)]
        if self.op == "update":
            for f in filas:
                nuevo = _normalizar({**f, **self.payload})
                if self.tabla == "citas": self._cruce(nuevo, ignorar_id=f["id"])
                f.update(_normalizar(dict(self.payload)))
            return Resp([dict(f) for f in filas])
        if self.op == "delete":
            for f in filas: tabla.remove(f)
            return Resp([dict(f) for f in filas])
        filas = self._embeber(filas)
        for c, desc in reversed(self.orden):
            filas.sort(key=lambda f: str(f.get(c)), reverse=desc)
        total = len(filas)
        if self.tope is not None: filas = filas[: self.tope]
        return Resp(filas, total if self.pedir_conteo else None)


class RPC:
    def __init__(self, db, params): self.db, self.p = db, params
    def execute(self):
        p = self.p
        filas = [
            {"fecha": c["fecha"], "hora_inicio": c["hora_inicio"], "hora_fin": c["hora_fin"]}
            for c in self.db.tablas["citas"]
            if c["profesional_id"] == p["p_profesional"] and p["p_desde"] <= c["fecha"] <= p["p_hasta"]
            and c["estado"] in ACTIVAS and c["id"] != p.get("p_excluir")
        ]
        return Resp(filas)


class _Auth:
    def __init__(self, db): self.db = db

    @staticmethod
    def _obj(u, con_sesion=True):
        user = type("U", (), {"id": u["id"], "user_metadata": u["meta"]})()
        sesion = type("S", (), {"access_token": f"tok:{u['id']}", "refresh_token": "r"})() if con_sesion else None
        return type("R", (), {"user": user, "session": sesion})()

    def sign_up(self, datos):
        if any(u["email"] == datos["email"] for u in self.db.usuarios):
            raise Exception("User already registered")
        meta = datos["options"]["data"]
        uid = str(uuid.uuid4())
        u = {"id": uid, "email": datos["email"], "password": datos["password"], "meta": meta}
        self.db.usuarios.append(u)
        tipo = meta.get("tipo_cuenta")   # trigger crear_perfil()
        self.db.tablas["perfiles"].append({
            "id": uid, "nombre": meta.get("nombre") or "Usuario", "telefono": meta.get("telefono") or None,
            "rol": tipo if tipo in ("establecimiento", "profesional") else "cliente"})
        return self._obj(u, con_sesion=not self.db.exigir_confirmacion)

    def sign_in_with_password(self, datos):
        u = next((u for u in self.db.usuarios
                  if u["email"] == datos["email"] and u["password"] == datos["password"]), None)
        if not u: raise Exception("Invalid login credentials")
        return self._obj(u)


class FakeClient:
    def __init__(self, db): self.db, self.auth = db, _Auth(db)
    def table(self, nombre): return Q(self.db, nombre)
    def rpc(self, nombre, params): return RPC(self.db, params)