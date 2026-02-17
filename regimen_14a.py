"""
regimen_14a.py
==============
Estructura preparada para el Régimen 14 A (Semi Integrado / Renta Atribuida).
Lógica tributaria pendiente de desarrollo completo.
"""

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
TASA_IDPC_14A = 0.27   # 27% para grandes empresas


# ---------------------------------------------------------------------------
# Cuentas por defecto (placeholder — se completará en siguiente versión)
# ---------------------------------------------------------------------------
CUENTAS_INGRESOS_DEFAULT_14A = [
    {"codigo": "300101", "nombre": "Ingresos Del Giro Percibido", "signo": "+", "f22": "1600"},
    {"codigo": "311102", "nombre": "Reajuste",                     "signo": "+", "f22": "1588"},
]

CUENTAS_EGRESOS_DEFAULT_14A = [
    {"codigo": "400101", "nombre": "Compras netas existencias",     "signo": "+", "f22": "1409"},
    {"codigo": "410101", "nombre": "Remuneraciones imponibles",     "signo": "+", "f22": ""},
    {"codigo": "410102", "nombre": "Leyes sociales",                "signo": "+", "f22": ""},
    {"codigo": "410110", "nombre": "Remuneraciones no imponibles",  "signo": "+", "f22": ""},
    {"codigo": "410111", "nombre": "Finiquitos",                    "signo": "+", "f22": ""},
    {"codigo": "410106", "nombre": "Honorarios",                    "signo": "+", "f22": "1412"},
    {"codigo": "410105", "nombre": "Arriendos",                     "signo": "+", "f22": "1415"},
    {"codigo": "430101", "nombre": "Impuesto de Primera Categoría", "signo": "+", "f22": "1422"},
    {"codigo": "430102", "nombre": "Multas e Intereses",            "signo": "+", "f22": "1422"},
]


# ---------------------------------------------------------------------------
# Función principal (pendiente de implementación completa)
# ---------------------------------------------------------------------------
def calcular_rli_14a(cuentas_balance: dict, **kwargs) -> dict:
    """
    TODO: Implementar cálculo completo régimen 14 A.
    
    Incluirá:
    - Ajustes por corrección monetaria
    - Gastos rechazados art. 33
    - Rentas exentas y no gravadas
    - Créditos por IDPC
    - FUT / RAI / DDAN
    """
    raise NotImplementedError(
        "El régimen 14 A está en desarrollo. "
        "Por favor seleccione Régimen 14 D N°3."
    )


def render_14a_placeholder():
    """Muestra mensaje de desarrollo en la interfaz Streamlit."""
    import streamlit as st
    st.info(
        "⚙️ **Régimen 14 A** — Módulo en desarrollo.\n\n"
        "Este régimen estará disponible en una próxima versión. "
        "Por ahora, seleccione **Régimen 14 D N°3** para continuar.",
        icon="🏗️",
    )
