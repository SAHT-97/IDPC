"""
regimen_14d3.py
===============
Lógica tributaria completa para el Régimen 14 D N°3 (ProPyme Transparente).
Calcula la Renta Líquida Imponible (RLI) e Impuesto de Primera Categoría (12,5%).
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
TASA_IDPC = 0.125  # 12.5%
UF_DEFECTO = 5000  # UF para deducción incentivo ahorro (editable)


# ---------------------------------------------------------------------------
# Estructuras de datos
# ---------------------------------------------------------------------------
@dataclass
class CuentaLinea:
    """Representa una línea de cuenta en el cálculo."""
    codigo: str
    nombre: str
    monto: int
    signo: str        # "+" o "-"
    f22: str = ""
    es_manual: bool = False
    existe_en_balance: bool = True


@dataclass
class ResultadoRLI:
    """Resultado completo del cálculo RLI."""
    # Totales intermedios
    total_ingresos: int = 0
    total_egresos: int = 0
    total_gastos_rechazados: int = 0

    # Sin incentivo al ahorro
    base_imponible: int = 0
    idpc_sin_incentivo: int = 0
    ppm: int = 0
    saldo_sin_incentivo: int = 0

    # Con incentivo al ahorro
    sub_total_base: int = 0
    retiros_ejercicio: int = 0
    multas_intereses_hist: int = 0
    idpc_hist: int = 0
    rli_invertida: int = 0
    deduccion_incentivo: int = 0
    porcentaje_rli: int = 0       # 50% RLI
    uf_limite: int = 0            # valor en $ de 5.000 UF
    idpc_con_incentivo: int = 0
    saldo_con_incentivo: int = 0


# ---------------------------------------------------------------------------
# Cuentas por defecto del régimen
# ---------------------------------------------------------------------------
CUENTAS_INGRESOS_DEFAULT = [
    {"codigo": "300101", "nombre": "Ingresos Del Giro Percibido", "signo": "+", "f22": "1600"},
    {"codigo": "311102", "nombre": "Reajuste",                     "signo": "+", "f22": "1588"},
]

CUENTAS_EGRESOS_DEFAULT = [
    {"codigo": "400101", "nombre": "Compras netas existencias",         "signo": "+", "f22": "1409"},
    # Remuneraciones (grupo compuesto)
    {"codigo": "410101", "nombre": "Remuneraciones imponibles",         "signo": "+", "f22": ""},
    {"codigo": "410102", "nombre": "Leyes sociales",                    "signo": "+", "f22": ""},
    {"codigo": "410110", "nombre": "Remuneraciones no imponibles",      "signo": "+", "f22": ""},
    {"codigo": "410111", "nombre": "Finiquitos",                        "signo": "+", "f22": ""},
    # fin grupo remuneraciones → f22 1411
    {"codigo": "410106", "nombre": "Honorarios",                        "signo": "+", "f22": "1412"},
    {"codigo": "410105", "nombre": "Arriendos",                         "signo": "+", "f22": "1415"},
    {"codigo": "430101", "nombre": "Impuesto de Primera Categoría",     "signo": "+", "f22": "1422"},
    {"codigo": "430102", "nombre": "Multas e Intereses",                "signo": "+", "f22": "1422"},
]

CUENTAS_GASTOS_RECHAZADOS_DEFAULT = [
    {"codigo": "430101", "nombre": "Impuesto de Primera Categoría", "signo": "+", "f22": "1431"},
    {"codigo": "430102", "nombre": "Multas e Intereses",            "signo": "+", "f22": "1431"},
]

# Grupo remuneraciones (subcuentas que se suman)
CODIGOS_REMUNERACIONES = {"410101", "410102", "410110", "410111"}


# ---------------------------------------------------------------------------
# Funciones principales
# ---------------------------------------------------------------------------
def construir_lineas_ingresos(cuentas_balance: dict, extras: list[dict] = None) -> list[CuentaLinea]:
    """Construye lista de líneas para la sección I. INGRESOS."""
    from extractor import get_valor, get_nombre, existe_cuenta

    lineas = []
    for d in CUENTAS_INGRESOS_DEFAULT:
        monto = get_valor(cuentas_balance, d["codigo"], "ganancias")
        lineas.append(CuentaLinea(
            codigo=d["codigo"],
            nombre=get_nombre(cuentas_balance, d["codigo"]) or d["nombre"],
            monto=monto,
            signo=d["signo"],
            f22=d["f22"],
            existe_en_balance=existe_cuenta(cuentas_balance, d["codigo"]),
        ))
    for e in (extras or []):
        monto = get_valor(cuentas_balance, e["codigo"], "ganancias") if not e.get("es_manual") else e["monto"]
        lineas.append(CuentaLinea(
            codigo=e["codigo"],
            nombre=get_nombre(cuentas_balance, e["codigo"]) or e.get("nombre", ""),
            monto=monto,
            signo=e.get("signo", "+"),
            f22=e.get("f22", ""),
            es_manual=e.get("es_manual", False),
            existe_en_balance=existe_cuenta(cuentas_balance, e["codigo"]),
        ))
    return lineas


def construir_lineas_egresos(cuentas_balance: dict, extras: list[dict] = None) -> list[CuentaLinea]:
    """Construye lista de líneas para la sección II. EGRESOS."""
    from extractor import get_valor, get_nombre, existe_cuenta

    lineas = []
    for d in CUENTAS_EGRESOS_DEFAULT:
        # Para remuneraciones, la columna es perdidas
        col = "activos" if d["codigo"] == "101090" else "perdidas"
        monto = get_valor(cuentas_balance, d["codigo"], col)
        lineas.append(CuentaLinea(
            codigo=d["codigo"],
            nombre=get_nombre(cuentas_balance, d["codigo"]) or d["nombre"],
            monto=monto,
            signo=d["signo"],
            f22=d["f22"],
            existe_en_balance=existe_cuenta(cuentas_balance, d["codigo"]),
        ))
    for e in (extras or []):
        monto = get_valor(cuentas_balance, e["codigo"], "perdidas") if not e.get("es_manual") else e["monto"]
        lineas.append(CuentaLinea(
            codigo=e["codigo"],
            nombre=get_nombre(cuentas_balance, e["codigo"]) or e.get("nombre", ""),
            monto=monto,
            signo=e.get("signo", "+"),
            f22=e.get("f22", ""),
            es_manual=e.get("es_manual", False),
            existe_en_balance=existe_cuenta(cuentas_balance, e["codigo"]),
        ))
    return lineas


def construir_lineas_gastos_rechazados(cuentas_balance: dict, extras: list[dict] = None) -> list[CuentaLinea]:
    """Construye lista de líneas para la sección III. GASTOS RECHAZADOS."""
    from extractor import get_valor, get_nombre, existe_cuenta

    lineas = []
    for d in CUENTAS_GASTOS_RECHAZADOS_DEFAULT:
        monto = get_valor(cuentas_balance, d["codigo"], "perdidas")
        lineas.append(CuentaLinea(
            codigo=d["codigo"],
            nombre=get_nombre(cuentas_balance, d["codigo"]) or d["nombre"],
            monto=monto,
            signo=d["signo"],
            f22=d["f22"],
            existe_en_balance=existe_cuenta(cuentas_balance, d["codigo"]),
        ))
    for e in (extras or []):
        monto = get_valor(cuentas_balance, e["codigo"], "perdidas") if not e.get("es_manual") else e["monto"]
        lineas.append(CuentaLinea(
            codigo=e["codigo"],
            nombre=get_nombre(cuentas_balance, e["codigo"]) or e.get("nombre", ""),
            monto=monto,
            signo=e.get("signo", "+"),
            f22=e.get("f22", ""),
            es_manual=e.get("es_manual", False),
            existe_en_balance=existe_cuenta(cuentas_balance, e["codigo"]),
        ))
    return lineas


def calcular_total_remuneraciones(lineas_egresos: list[CuentaLinea]) -> int:
    """Suma las subcuentas de remuneraciones."""
    return sum(l.monto for l in lineas_egresos if l.codigo in CODIGOS_REMUNERACIONES)


def calcular_total_ingresos(lineas: list[CuentaLinea]) -> int:
    return sum(l.monto for l in lineas)


def calcular_total_egresos(lineas: list[CuentaLinea]) -> int:
    return sum(l.monto for l in lineas)


def calcular_total_gastos_rechazados(lineas: list[CuentaLinea]) -> int:
    return sum(l.monto for l in lineas)


# ---------------------------------------------------------------------------
# Cálculo SIN incentivo al ahorro
# ---------------------------------------------------------------------------
def calcular_sin_incentivo(
    total_ingresos: int,
    total_egresos: int,
    total_gastos_rechazados: int,
    ppm: int,
) -> ResultadoRLI:
    """
    Fórmula:
        Base Imponible = Ingresos - Egresos + Gastos Rechazados
        IDPC = Base Imponible * 12,5%
        Saldo = IDPC - PPM
    """
    r = ResultadoRLI()
    r.total_ingresos = total_ingresos
    r.total_egresos = total_egresos
    r.total_gastos_rechazados = total_gastos_rechazados
    r.ppm = ppm

    r.base_imponible = total_ingresos - total_egresos + total_gastos_rechazados
    r.idpc_sin_incentivo = int(r.base_imponible * TASA_IDPC)
    r.saldo_sin_incentivo = r.idpc_sin_incentivo - ppm
    return r


# ---------------------------------------------------------------------------
# Cálculo CON incentivo al ahorro
# ---------------------------------------------------------------------------
def calcular_con_incentivo(
    total_ingresos: int,
    total_egresos: int,
    total_gastos_rechazados: int,
    ppm: int,
    retiros_ejercicio: int,
    multas_hist: int,
    idpc_hist: int,
    uf_valor_pesos: int,
) -> ResultadoRLI:
    """
    Paso 1: Sub Base = Ingresos - Egresos + Gastos Rechazados
    Paso 2: RLI Invertida = Sub Base - Retiros - Multas - IDPC
    Paso 3: Deducción = min(50% RLI Invertida, valor_5000UF)
    Paso 4: IDPC = Deducción * 12,5%
             Saldo = IDPC - PPM
    """
    r = ResultadoRLI()
    r.total_ingresos = total_ingresos
    r.total_egresos = total_egresos
    r.total_gastos_rechazados = total_gastos_rechazados
    r.ppm = ppm
    r.retiros_ejercicio = retiros_ejercicio
    r.multas_intereses_hist = multas_hist
    r.idpc_hist = idpc_hist

    r.sub_total_base = total_ingresos - total_egresos + total_gastos_rechazados
    r.rli_invertida = r.sub_total_base - retiros_ejercicio - multas_hist - idpc_hist

    r.porcentaje_rli = int(r.rli_invertida * 0.50)
    r.uf_limite = uf_valor_pesos

    r.deduccion_incentivo = min(r.porcentaje_rli, uf_valor_pesos)
    if r.deduccion_incentivo < 0:
        r.deduccion_incentivo = 0

    r.idpc_con_incentivo = int(r.deduccion_incentivo * TASA_IDPC)
    r.saldo_con_incentivo = r.idpc_con_incentivo - ppm
    return r


# ---------------------------------------------------------------------------
# Formateo
# ---------------------------------------------------------------------------
def fmt_monto(valor: int) -> str:
    """Formatea número como $ 1.234.567"""
    if valor is None:
        return "$ 0"
    return f"$ {valor:,.0f}".replace(",", ".")
