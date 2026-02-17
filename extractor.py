"""
extractor.py
============
Extracción de datos desde un Balance de 8 columnas en formato PDF.
Retorna diccionario de cuentas y datos de empresa.
"""

import re
import pdfplumber


# ---------------------------------------------------------------------------
# Patrones de encabezado empresa (primera página)
# ---------------------------------------------------------------------------
_MESES = r"(?:ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|SEPTIEMBRE|OCTUBRE|NOVIEMBRE|DICIEMBRE)"
_RUT_PATTERN = re.compile(r"\d{1,2}[\.\d]*\d-[\dkK]")
_PERIODO_PATTERN = re.compile(
    rf"BALANCE\s+DESDE\s+({_MESES}\s+DEL\s+\d{{4}})\s+HASTA\s+({_MESES}\s+DEL\s+\d{{4}})",
    re.IGNORECASE,
)
_CODIGO_PATTERN = re.compile(r"^\d{6}$")


def _fmt_numero(texto: str) -> int:
    """Convierte string con puntos como miles a entero."""
    if not texto:
        return 0
    limpio = re.sub(r"[^\d]", "", texto)
    return int(limpio) if limpio else 0


def _detectar_columnas_x(words: list[dict]) -> dict:
    """
    Detecta las posiciones X aproximadas de cada columna del balance
    a partir de los encabezados de la tabla.
    Retorna dict: {nombre_col: x_centro}
    """
    header_words = [w for w in words if w["text"].upper() in
                    ("CODIGO", "CUENTA", "DEBITOS", "CREDITOS", "DEUDOR", "ACREEDOR",
                     "ACTIVOS", "PASIVOS", "PERDIDAS", "GANANCIAS", "SALDO")]
    if not header_words:
        return {}
    cols = {}
    for w in header_words:
        t = w["text"].upper()
        x = (w["x0"] + w["x1"]) / 2
        if t == "CODIGO":
            cols["codigo"] = x
        elif t == "CUENTA":
            cols["cuenta"] = x
        elif t == "DEBITOS":
            cols["debitos"] = x
        elif t == "CREDITOS":
            cols["creditos"] = x
        elif t == "DEUDOR":
            cols["saldo_deudor"] = x
        elif t == "ACREEDOR":
            cols["saldo_acreedor"] = x
        elif t == "ACTIVOS":
            cols["activos"] = x
        elif t == "PASIVOS":
            cols["pasivos"] = x
        elif t == "PERDIDAS":
            cols["perdidas"] = x
        elif t == "GANANCIAS":
            cols["ganancias"] = x
    return cols


def _asignar_columna(x: float, cols: dict) -> str | None:
    """Devuelve la columna más cercana al valor x dado."""
    if not cols:
        return None
    return min(cols, key=lambda k: abs(cols[k] - x))


def extraer_balance(pdf_path: str) -> tuple[dict, dict]:
    """
    Extrae cuentas y datos de empresa desde un PDF de balance de 8 columnas.

    Returns
    -------
    cuentas : dict
        {
          "300101": {"cuenta": "VENTAS", "ganancias": 222137351},
          "400101": {"cuenta": "COSTO DE VENTAS", "perdidas": 113358745},
          ...
        }
    empresa : dict
        {razon_social, rut, giro, direccion, comuna, periodo}
    """
    cuentas: dict = {}
    empresa = {
        "razon_social": "",
        "rut": "",
        "giro": "",
        "direccion": "",
        "comuna": "",
        "periodo": "",
    }

    with pdfplumber.open(pdf_path) as pdf:
        full_text_p1 = pdf.pages[0].extract_text() or ""
        _extraer_datos_empresa(full_text_p1, empresa)

        for page in pdf.pages:
            _extraer_cuentas_pagina(page, cuentas)

    return cuentas, empresa


# ---------------------------------------------------------------------------
# Extracción de datos de empresa
# ---------------------------------------------------------------------------
def _extraer_datos_empresa(texto: str, empresa: dict):
    """Parsea líneas iniciales del PDF para obtener datos de la empresa."""
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]

    # Buscar RUT en todo el texto
    for linea in lineas[:5]:
        ruts = _RUT_PATTERN.findall(linea)
        if ruts:
            empresa["rut"] = ruts[0]
            # Razón social = todo antes del RUT en la misma línea
            idx = linea.find(empresa["rut"])
            empresa["razon_social"] = linea[:idx].strip()
            # Resto de la línea puede contener giro/dirección/comuna
            resto = linea[idx + len(empresa["rut"]):].strip()
            _parsear_resto_encabezado(resto, empresa)
            break

    # Buscar período
    texto_upper = texto.upper()
    m = _PERIODO_PATTERN.search(texto_upper)
    if m:
        empresa["periodo"] = f"DESDE {m.group(1)} HASTA {m.group(2)}"

    # Si no se encontró razón social, primera línea no vacía
    if not empresa["razon_social"] and lineas:
        empresa["razon_social"] = lineas[0]


def _parsear_resto_encabezado(resto: str, empresa: dict):
    """
    Intenta extraer giro, dirección y comuna del texto restante del encabezado.
    El PDF de ejemplo concatena todo sin separadores claros; usamos heurísticas.
    """
    # Intento con palabras clave de dirección
    m_dir = re.search(r"((?:CALLE|AV\.|AVENIDA|PASAJE|BOULEVARD|[A-Z]+\s+#\s*\d+).+)", resto, re.IGNORECASE)
    if m_dir:
        empresa["giro"] = resto[:m_dir.start()].strip()
        dir_rest = m_dir.group(1)
        # Última "palabra" puede ser comuna
        partes = dir_rest.rsplit(" ", 1)
        if len(partes) == 2 and len(partes[1]) > 3:
            empresa["direccion"] = partes[0].strip()
            empresa["comuna"] = partes[1].strip()
        else:
            empresa["direccion"] = dir_rest.strip()
    else:
        # Sin heurística clara, todo va a giro
        empresa["giro"] = resto


# ---------------------------------------------------------------------------
# Extracción de cuentas
# ---------------------------------------------------------------------------
def _extraer_cuentas_pagina(page, cuentas: dict):
    """
    Extrae cuentas de una página usando posiciones de palabras (words).
    Estrategia:
      1) Detectar posiciones X de columnas numéricas desde encabezado.
      2) Para cada fila con código de 6 dígitos, leer valores en columnas.
    """
    words = page.extract_words(x_tolerance=3, y_tolerance=3)
    if not words:
        return

    # Agrupar palabras por línea (Y aproximado)
    lineas_dict: dict[float, list] = {}
    for w in words:
        y_key = round(w["top"] / 3) * 3
        lineas_dict.setdefault(y_key, []).append(w)

    # Ordenar líneas por Y
    lineas_ordenadas = sorted(lineas_dict.items())

    # Detectar columnas desde encabezados
    cols = _detectar_columnas_x(words)

    # Columnas numéricas en orden esperado (fallback por posición relativa)
    # Estimamos desde la página si no detectamos encabezados
    if len(cols) < 4:
        cols = _estimar_columnas_por_posicion(page, lineas_ordenadas)

    for _, palabras_fila in lineas_ordenadas:
        palabras_fila.sort(key=lambda w: w["x0"])
        textos = [w["text"] for w in palabras_fila]

        # Buscar código de 6 dígitos
        codigo = None
        codigo_idx = -1
        for i, t in enumerate(textos):
            if _CODIGO_PATTERN.match(t):
                codigo = t
                codigo_idx = i
                break

        if not codigo:
            continue

        # Nombre de cuenta = palabras entre código y primer número
        nombre_parts = []
        num_idx = codigo_idx + 1
        while num_idx < len(textos) and not re.match(r"^[\d\.]+$", textos[num_idx]):
            nombre_parts.append(textos[num_idx])
            num_idx += 1
        nombre = " ".join(nombre_parts)

        # Recoger valores numéricos con sus posiciones X
        valores_x: list[tuple[float, int]] = []
        for w in palabras_fila:
            if re.match(r"^[\d\.]+$", w["text"]):
                valores_x.append(((w["x0"] + w["x1"]) / 2, _fmt_numero(w["text"])))

        if not valores_x:
            continue

        # Asignar valores a columnas por proximidad
        registro: dict = {"cuenta": nombre}
        columnas_numericas = ["debitos", "creditos", "saldo_deudor", "saldo_acreedor",
                              "activos", "pasivos", "perdidas", "ganancias"]

        for x_val, valor in valores_x:
            col = _asignar_columna(x_val, {k: cols[k] for k in columnas_numericas if k in cols})
            if col and valor > 0:
                registro[col] = registro.get(col, 0) + valor

        # Solo agregar si tiene saldo en alguna columna relevante
        cols_relevantes = {"activos", "pasivos", "perdidas", "ganancias",
                           "saldo_deudor", "saldo_acreedor"}
        if any(k in registro for k in cols_relevantes):
            if codigo not in cuentas:
                cuentas[codigo] = registro
            else:
                # Acumular si la cuenta aparece en múltiples páginas
                for k, v in registro.items():
                    if k != "cuenta" and isinstance(v, int):
                        cuentas[codigo][k] = cuentas[codigo].get(k, 0) + v


def _estimar_columnas_por_posicion(page, lineas_ordenadas: list) -> dict:
    """
    Estimación de posiciones de columnas cuando no se detectan encabezados.
    Usa el ancho de la página y posiciones típicas de un balance de 8 columnas.
    """
    w = float(page.width)
    # Posiciones relativas aproximadas (calibradas para balance estándar A4/carta)
    return {
        "debitos":        w * 0.33,
        "creditos":       w * 0.42,
        "saldo_deudor":   w * 0.51,
        "saldo_acreedor": w * 0.59,
        "activos":        w * 0.67,
        "pasivos":        w * 0.73,
        "perdidas":       w * 0.82,
        "ganancias":      w * 0.92,
    }


# ---------------------------------------------------------------------------
# Función de consulta
# ---------------------------------------------------------------------------
def get_valor(cuentas: dict, codigo: str, columna: str = None) -> int:
    """
    Obtiene el valor de una cuenta.
    Si columna es None, busca en el orden: ganancias, perdidas, activos, pasivos,
    saldo_acreedor, saldo_deudor.
    Retorna 0 si no existe.
    """
    if codigo not in cuentas:
        return 0
    reg = cuentas[codigo]
    if columna:
        return reg.get(columna, 0)
    for col in ("ganancias", "perdidas", "activos", "pasivos", "saldo_acreedor", "saldo_deudor"):
        if col in reg and reg[col] > 0:
            return reg[col]
    return 0


def get_nombre(cuentas: dict, codigo: str) -> str:
    """Retorna el nombre de la cuenta o string vacío."""
    return cuentas.get(codigo, {}).get("cuenta", "")


def existe_cuenta(cuentas: dict, codigo: str) -> bool:
    return codigo in cuentas
