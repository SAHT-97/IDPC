"""
app.py
======
Aplicación principal Streamlit — Cálculo de RLI e IDPC.
Régimen 14 D N°3 | Impuesto de Primera Categoría 12,5%
"""

import os
import io
import tempfile
import streamlit as st
from pathlib import Path

# Importar módulos propios
from extractor import extraer_balance, get_valor, get_nombre
from regimen_14d3 import (
    construir_lineas_ingresos,
    construir_lineas_egresos,
    construir_lineas_gastos_rechazados,
    calcular_total_ingresos,
    calcular_total_egresos,
    calcular_total_gastos_rechazados,
    calcular_total_remuneraciones,
    calcular_sin_incentivo,
    calcular_con_incentivo,
    CODIGOS_REMUNERACIONES,
    CUENTAS_EGRESOS_DEFAULT,
    fmt_monto,
    UF_DEFECTO,
    TASA_IDPC,
)
from regimen_14a import render_14a_placeholder

# ---------------------------------------------------------------------------
# Config página
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Cálculo RLI — IDPC",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Cargar CSS
css_path = Path(__file__).parent / "styles.css"
if css_path.exists():
    with open(css_path) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Inicializar session_state
# ---------------------------------------------------------------------------
def _init_state():
    defaults = {
        "cuentas": {},
        "empresa": {},
        "extras_ingresos": [],
        "extras_egresos": [],
        "extras_gastos": [],
        "extras_remuneraciones": [],
        "modo_calculo": "sin",          # "sin" | "con"
        "valor_uf": 38000,              # valor $ por UF (editable)
        "uf_cantidad": UF_DEFECTO,
        "montos_editados": {},          # {codigo: monto_editado}
        "regimen": "14 D N°3",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
def render_sidebar():
    with st.sidebar:
        st.markdown("## 📂 Cargar Balance")
        pdf_file = st.file_uploader(
            "Suba el PDF del Balance de 8 columnas",
            type=["pdf"],
            key="pdf_upload",
        )
        if pdf_file is not None:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(pdf_file.read())
                tmp_path = tmp.name
            try:
                with st.spinner("Extrayendo datos del balance..."):
                    cuentas, empresa = extraer_balance(tmp_path)
                st.session_state["cuentas"] = cuentas
                st.session_state["empresa"] = empresa
                st.session_state["montos_editados"] = {}
                st.success(f"✅ Balance cargado — {len(cuentas)} cuentas extraídas")
            except Exception as e:
                st.error(f"❌ Error al procesar el PDF: {e}")
            finally:
                os.unlink(tmp_path)

        st.markdown("---")
        st.markdown("## ⚙️ Régimen Tributario")
        regimen = st.radio(
            "Seleccione régimen",
            options=["14 D N°3", "14 A"],
            index=0 if st.session_state["regimen"] == "14 D N°3" else 1,
            key="regimen_radio",
        )
        st.session_state["regimen"] = regimen


# ---------------------------------------------------------------------------
# HEADER EMPRESA
# ---------------------------------------------------------------------------
def render_empresa_header():
    emp = st.session_state.get("empresa", {})
    if not emp:
        st.info("👆 Suba un PDF de balance en la barra lateral para comenzar.", icon="📄")
        return False

    razon = emp.get("razon_social", "—")
    rut = emp.get("rut", "—")
    giro = emp.get("giro", "—")
    direccion = emp.get("direccion", "")
    comuna = emp.get("comuna", "")
    periodo = emp.get("periodo", "—")
    dir_full = f"{direccion} — {comuna}" if direccion and comuna else (direccion or comuna)

    st.markdown(f"""
    <div class="empresa-header">
        <h2>{razon}</h2>
        <div class="meta">
            <strong>RUT:</strong> {rut} &nbsp;|&nbsp;
            <strong>Giro:</strong> {giro}<br>
            <strong>Dirección:</strong> {dir_full}<br>
            <strong>Período:</strong> {periodo}
        </div>
    </div>
    """, unsafe_allow_html=True)
    return True


# ---------------------------------------------------------------------------
# Helpers para tabla HTML
# ---------------------------------------------------------------------------
def _badge_f22(f22: str) -> str:
    return f'<span class="f22">{f22}</span>' if f22 else ""


def _alerta_cuenta(codigo: str) -> str:
    return f'<span class="alerta-cuenta">⚠ {codigo} no encontrada en balance</span>'


def _monto_editable_key(codigo: str, seccion: str) -> str:
    return f"monto_{seccion}_{codigo}"


def _opciones_cuentas(cuentas: dict, excluir: list[str] = None) -> list[str]:
    """
    Construye lista de opciones para selectbox con formato:
    "CÓDIGO — NOMBRE DE CUENTA"
    Solo incluye cuentas con saldo en activos, pasivos, ganancias o pérdidas.
    """
    excluir_set = set(excluir or [])
    cols_relevantes = {"activos", "pasivos", "ganancias", "perdidas",
                       "saldo_deudor", "saldo_acreedor"}
    opciones = []
    for cod, datos in sorted(cuentas.items()):
        if cod in excluir_set:
            continue
        tiene_saldo = any(
            datos.get(c, 0) > 0 for c in cols_relevantes
        )
        if tiene_saldo:
            nombre = datos.get("cuenta", "")
            opciones.append(f"{cod} — {nombre}")
    return opciones


def _parse_opcion(opcion: str) -> tuple[str, str]:
    """Extrae (codigo, nombre) desde string 'CODIGO — NOMBRE'."""
    if " — " in opcion:
        partes = opcion.split(" — ", 1)
        return partes[0].strip(), partes[1].strip()
    return opcion.strip(), ""


def _monto_desde_balance(cuentas: dict, codigo: str) -> int:
    """
    Retorna el monto más representativo de la cuenta:
    prioriza ganancias → pérdidas → activos → pasivos → saldo_acreedor → saldo_deudor
    """
    reg = cuentas.get(codigo, {})
    for col in ("ganancias", "perdidas", "activos", "pasivos", "saldo_acreedor", "saldo_deudor"):
        val = reg.get(col, 0)
        if val and val > 0:
            return int(val)
    return 0


def _get_monto(linea, seccion: str) -> int:
    """Obtiene monto editado o el original de la línea."""
    key = _monto_editable_key(linea.codigo, seccion)
    if key in st.session_state["montos_editados"]:
        return st.session_state["montos_editados"][key]
    return linea.monto


# ---------------------------------------------------------------------------
# Widget reutilizable — Agregar cuenta desde lista del balance
# ---------------------------------------------------------------------------
def _render_agregar_cuenta(cuentas: dict, prefijo: str, lista_key: str):
    """
    Widget de agregado de cuentas con:
    - Selectbox con todas las cuentas del balance (código — nombre)
    - Nombre y monto se rellenan automáticamente al seleccionar
    - F22 es opcional y de ingreso manual
    
    Usa session_state para trackear la selección anterior y forzar
    la actualización del monto cuando cambia la cuenta seleccionada.
    """
    if not cuentas:
        st.warning("⚠️ Primero cargue un balance PDF para ver las cuentas disponibles.")
        return

    opciones = _opciones_cuentas(cuentas)
    if not opciones:
        st.info("No hay cuentas disponibles en el balance cargado.")
        return

    VACIO = "— Seleccione una cuenta —"
    opciones_con_vacio = [VACIO] + opciones

    key_sel      = f"sel_{prefijo}_cuenta"
    key_prev_cod = f"prev_{prefijo}_cod"      # guarda el último código seleccionado
    key_monto_ov = f"monto_ov_{prefijo}"      # override de monto cuando cambia selección

    seleccion = st.selectbox(
        "🔍 Buscar cuenta (escriba código o nombre para filtrar)",
        options=opciones_con_vacio,
        index=0,
        key=key_sel,
        help="Escriba el código o parte del nombre para filtrar",
    )

    if seleccion == VACIO:
        # Limpiar estado previo al volver a "vacío"
        st.session_state[key_prev_cod] = None
        st.caption("Seleccione una cuenta del balance para continuar.")
        return

    cod_sel, nom_sel = _parse_opcion(seleccion)

    # --- Detectar cambio de selección y actualizar monto automáticamente ---
    prev_cod = st.session_state.get(key_prev_cod)
    if prev_cod != cod_sel:
        # Selección cambió → cargar monto fresco del balance
        st.session_state[key_monto_ov] = _monto_desde_balance(cuentas, cod_sel)
        st.session_state[key_prev_cod] = cod_sel

    monto_actual = st.session_state.get(key_monto_ov, _monto_desde_balance(cuentas, cod_sel))

    # --- Campos editables ---
    st.markdown("<br>", unsafe_allow_html=True)
    col_cod, col_nom, col_monto, col_f22 = st.columns([1.4, 3.2, 2, 1.4])

    col_cod.markdown("**Código**")
    col_cod.markdown(
        f"<div style='padding:8px 0;'><span class='cod' style='font-size:15px;font-weight:700'>"
        f"{cod_sel}</span></div>",
        unsafe_allow_html=True,
    )

    # Keys de los widgets — definidas aquí para poder leerlas en el botón
    key_nom   = f"nom_{prefijo}_edit_{cod_sel}"
    key_monto = f"monto_{prefijo}_edit_{cod_sel}"
    key_f22   = f"f22_{prefijo}_edit_{cod_sel}"

    col_nom.markdown("**Nombre**")
    col_nom.text_input(
        "Nombre cuenta",
        value=nom_sel,
        key=key_nom,
        label_visibility="collapsed",
    )

    col_monto.markdown("**Monto ($)**")
    col_monto.number_input(
        "Monto",
        value=monto_actual,
        min_value=0,
        step=1000,
        key=key_monto,
        label_visibility="collapsed",
    )

    col_f22.markdown("**SC F22** *(opcional)*")
    col_f22.text_input(
        "F22",
        value=st.session_state.get(key_f22, ""),
        placeholder="ej: 1600",
        key=key_f22,
        label_visibility="collapsed",
    )

    # Leer valores actuales directamente desde session_state (siempre frescos)
    nombre_actual  = st.session_state.get(key_nom,   nom_sel)
    monto_captura  = st.session_state.get(key_monto, monto_actual)
    f22_captura    = st.session_state.get(key_f22,   "")

    # Persistir monto en key_monto_ov para siguiente render
    st.session_state[key_monto_ov] = monto_captura

    # Resumen visual
    st.markdown(
        f"<div style='background:#f0fff4;border-left:3px solid #38a169;padding:6px 12px;"
        f"border-radius:4px;font-size:12px;margin:8px 0;'>"
        f"✔ <strong>{cod_sel}</strong> — {nombre_actual} &nbsp;|&nbsp; "
        f"Monto: <strong>{fmt_monto(monto_captura)}</strong>"
        f"{'&nbsp;|&nbsp; F22: <strong>' + f22_captura + '</strong>' if f22_captura else ''}"
        f"</div>",
        unsafe_allow_html=True,
    )

    if st.button("✅ Confirmar y agregar", key=f"btn_add_{prefijo}", type="primary"):
        lista = st.session_state[lista_key]
        codigos_ya = [e["codigo"] for e in lista]
        if cod_sel in codigos_ya:
            st.warning(f"⚠️ La cuenta {cod_sel} ya fue agregada a esta sección.")
        else:
            # Leer NUEVAMENTE desde session_state al momento exacto del click
            monto_final  = st.session_state.get(key_monto, monto_actual)
            nombre_final = st.session_state.get(key_nom,   nom_sel)
            f22_final    = st.session_state.get(key_f22,   "").strip()
            lista.append({
                "codigo": cod_sel,
                "nombre": nombre_final or nom_sel,
                "signo": "+",
                "f22": f22_final,
                "monto": int(monto_final),
                "es_manual": True,
            })
            # Limpiar selectbox y estado previo
            if key_prev_cod in st.session_state:
                del st.session_state[key_prev_cod]
            if key_sel in st.session_state:
                del st.session_state[key_sel]
            st.rerun()


# ---------------------------------------------------------------------------
# Sección I — INGRESOS
# ---------------------------------------------------------------------------
def render_ingresos(cuentas: dict):
    st.markdown('<div class="seccion-bloque">', unsafe_allow_html=True)
    st.markdown('<div class="seccion-titulo">I. INGRESOS DEL EJERCICIO</div>', unsafe_allow_html=True)

    lineas = construir_lineas_ingresos(cuentas, st.session_state["extras_ingresos"])

    # Encabezados tabla
    col_cod, col_nombre, col_monto, col_signo, col_f22, col_acciones = st.columns(
        [1.2, 4, 2, 0.6, 1, 1]
    )
    col_cod.markdown("**Código**")
    col_nombre.markdown("**Cuenta**")
    col_monto.markdown("**Monto**")
    col_signo.markdown("**(**)")
    col_f22.markdown("**SC F22**")
    col_acciones.markdown("**Acción**")

    st.markdown("<hr class='sep'>", unsafe_allow_html=True)

    total = 0
    idxs_a_eliminar = []

    for i, linea in enumerate(lineas):
        col_cod, col_nombre, col_monto, col_signo, col_f22, col_acc = st.columns(
            [1.2, 4, 2, 0.6, 1, 1]
        )
        col_cod.markdown(f"<span class='cod'>{linea.codigo}</span>", unsafe_allow_html=True)

        nombre_display = linea.nombre
        if not linea.existe_en_balance:
            nombre_display += " ⚠️"
        col_nombre.markdown(nombre_display)

        key_m = _monto_editable_key(linea.codigo + str(i), "ing")
        
        if not linea.es_manual:
            # TEXTO PLANO
            monto_val = linea.monto
            col_monto.markdown(f"**{fmt_monto(monto_val)}**", unsafe_allow_html=True)
            st.session_state["montos_editados"][key_m] = monto_val
            nuevo_monto = monto_val
        else:
            # INPUT EDITABLE
            monto_val = st.session_state["montos_editados"].get(key_m, linea.monto)
            nuevo_monto = col_monto.number_input(
                "", value=monto_val, min_value=0, step=1000, key=key_m, label_visibility="collapsed"
            )
            st.session_state["montos_editados"][key_m] = nuevo_monto
        
        total += nuevo_monto

        col_signo.markdown(f"<div class='signo'>{linea.signo}</div>", unsafe_allow_html=True)
        col_f22.markdown(_badge_f22(linea.f22), unsafe_allow_html=True)

        if linea.es_manual:
            if col_acc.button("🗑️", key=f"del_ing_{i}", help="Eliminar cuenta"):
                idxs_a_eliminar.append(i)

    # Eliminar extras marcados
    offset = len(construir_lineas_ingresos(cuentas))  # líneas fijas
    for idx in sorted(set(idxs_a_eliminar), reverse=True):
        extra_idx = idx - offset
        if 0 <= extra_idx < len(st.session_state["extras_ingresos"]):
            st.session_state["extras_ingresos"].pop(extra_idx)
            st.rerun()

    st.markdown("<hr class='sep'>", unsafe_allow_html=True)

    # Agregar cuenta — selector inteligente
    with st.expander("➕ Agregar cuenta a Ingresos"):
        _render_agregar_cuenta(cuentas, "ing", "extras_ingresos")

    # Total
    col1, col2, col3 = st.columns([5.2, 2, 1])
    col1.markdown("**TOTAL DE INGRESOS**")
    col2.markdown(f"**{fmt_monto(total)}**")
    col3.markdown("**(=)**")

    st.markdown('</div>', unsafe_allow_html=True)
    return total


# ---------------------------------------------------------------------------
# Sección II — EGRESOS
# ---------------------------------------------------------------------------
def render_egresos(cuentas: dict):
    st.markdown('<div class="seccion-bloque">', unsafe_allow_html=True)
    st.markdown('<div class="seccion-titulo">II. EGRESOS DEL EJERCICIO</div>', unsafe_allow_html=True)

    # Inicializar lista de extras_remuneraciones si no existe
    if "extras_remuneraciones" not in st.session_state:
        st.session_state["extras_remuneraciones"] = []

    lineas = construir_lineas_egresos(cuentas, st.session_state["extras_egresos"])

    col_cod, col_nombre, col_monto, col_signo, col_f22, col_acc = st.columns([1.2, 4, 2, 0.6, 1, 1])
    col_cod.markdown("**Código**")
    col_nombre.markdown("**Cuenta**")
    col_monto.markdown("**Monto**")
    col_signo.markdown("**(**)")
    col_f22.markdown("**SC F22**")
    col_acc.markdown("**Acción**")

    st.markdown("<hr class='sep'>", unsafe_allow_html=True)

    total = 0
    idxs_eliminar = []
    
    # Vamos a iterar usando while para poder agrupar remuneraciones
    i = 0
    n = len(lineas)
    
    while i < n:
        linea = lineas[i]
        
        # Detectar inicio de bloque remuneraciones
        if linea.codigo in CODIGOS_REMUNERACIONES:
            # Agrupar todas las líneas consecutivas que sean de remuneraciones
            grupo_rem = []
            while i < n and lineas[i].codigo in CODIGOS_REMUNERACIONES:
                grupo_rem.append((i, lineas[i]))
                i += 1
            
            # --- Pre-calcular total para mostrarlo ARRIBA ---
            total_rem_display = 0
            
            # 1. Sumar fijos (Extrados => No editables => Usar valor linea.monto)
            for idx_orig, l_rem in grupo_rem:
                # Al ser fijo/extraído, asumimos no editable
                total_rem_display += int(l_rem.monto)
            
            # 2. Sumar extras (Manuales => Usar widget o valor guardado)
            for j, extra_rem in enumerate(st.session_state["extras_remuneraciones"]):
                key_rem = _monto_editable_key(extra_rem["codigo"] + f"rem{j}", "rem")
                if key_rem in st.session_state:
                    val = st.session_state[key_rem]
                else:
                    val = st.session_state["montos_editados"].get(key_rem, extra_rem["monto"])
                total_rem_display += int(val)

            # --- Renderizar Resumen Remuneraciones (ARRIBA) ---
            total += total_rem_display
            
            crem1, crem2, crem3, crem4, crem5, crem6 = st.columns([1.2, 4, 2, 0.6, 1, 1])
            crem1.markdown("")
            crem2.markdown("<strong>Remuneraciones Pagadas (Total)</strong>", unsafe_allow_html=True)
            crem3.markdown(f"<strong>{fmt_monto(total_rem_display)}</strong>", unsafe_allow_html=True)
            crem4.markdown("<div class='signo'>+</div>", unsafe_allow_html=True)
            crem5.markdown(_badge_f22("1411"), unsafe_allow_html=True)
            

            # --- Renderizar bloque colapsable indentado ---
            _col_indent, col_expander = st.columns([0.15, 9.85])
            with col_expander:
                st.markdown(
                    "<div style='border-left: 3px solid #CBD5E0; padding-left: 10px; margin-top:-16px; margin-bottom:4px;'>",
                    unsafe_allow_html=True
                )
                with st.expander("📝 Ver detalle Remuneraciones", expanded=False):
                    # 1. Cuentas fijas del grupo
                    for idx_orig, l_rem in grupo_rem:
                        col_cod_r, col_nom_r, col_monto_r, col_sig_r, col_f22_r, col_acc_r = st.columns(
                            [1.2, 4, 2, 0.6, 1, 1]
                        )
                        col_cod_r.markdown(f"<span class='cod'>{l_rem.codigo}</span>", unsafe_allow_html=True)
                        
                        nom = l_rem.nombre
                        if not l_rem.existe_en_balance:
                            nom += " ⚠️"
                        col_nom_r.markdown(nom)
                        
                        key_m = _monto_editable_key(l_rem.codigo + str(idx_orig), "egr")
                        monto_val = l_rem.monto
                        col_monto_r.markdown(f"**{fmt_monto(monto_val)}**", unsafe_allow_html=True)
                        st.session_state["montos_editados"][key_m] = monto_val

                    # 2. Extras de remuneraciones
                    for j, extra_rem in enumerate(st.session_state["extras_remuneraciones"]):
                        key_rem = _monto_editable_key(extra_rem["codigo"] + f"rem{j}", "rem")
                        monto_rem_val = st.session_state["montos_editados"].get(
                            key_rem, extra_rem["monto"]
                        )
                        
                        cr1, cr2, col_m_extra, cr4, cr5, cr6 = st.columns([1.2, 4, 2, 0.6, 1, 1])
                        
                        cr1.markdown(f"<span class='cod'>{extra_rem['codigo']}</span>",
                                     unsafe_allow_html=True)
                        cr2.markdown(extra_rem["nombre"])
                        
                        monto_rem_nuevo = col_m_extra.number_input(
                            "", value=monto_rem_val, min_value=0, step=1000,
                            key=key_rem, label_visibility="collapsed"
                        )
                        st.session_state["montos_editados"][key_rem] = monto_rem_nuevo
                        
                        if cr6.button("🗑️", key=f"del_rem_{j}"):
                            st.session_state["extras_remuneraciones"].pop(j)
                            st.rerun()

                    # Botón agregar subcuenta DENTRO del expander
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown("###### Agregar subcuenta a Remuneraciones")
                    _render_agregar_cuenta(cuentas, "rem", "extras_remuneraciones")
                
                st.markdown("</div>", unsafe_allow_html=True)

        else:
            # Renderizado normal de otras cuentas
            col_cod_r, col_nom_r, col_monto_r, col_sig_r, col_f22_r, col_acc_r = st.columns(
                [1.2, 4, 2, 0.6, 1, 1]
            )
            col_cod_r.markdown(f"<span class='cod'>{linea.codigo}</span>", unsafe_allow_html=True)
            
            nombre_display = linea.nombre + (" ⚠️" if not linea.existe_en_balance else "")
            col_nom_r.markdown(nombre_display)

            key_m = _monto_editable_key(linea.codigo + str(i), "egr")
            
            if not linea.es_manual:
                monto_val = linea.monto
                col_monto_r.markdown(f"**{fmt_monto(monto_val)}**", unsafe_allow_html=True)
                st.session_state["montos_editados"][key_m] = monto_val
                nuevo_monto = monto_val
            else:
                monto_val = st.session_state["montos_editados"].get(key_m, linea.monto)
                nuevo_monto = col_monto_r.number_input(
                    "", value=monto_val, min_value=0, step=1000, key=key_m, label_visibility="collapsed"
                )
                st.session_state["montos_editados"][key_m] = nuevo_monto

            total += nuevo_monto

            col_sig_r.markdown("<div class='signo'>+</div>", unsafe_allow_html=True)
            col_f22_r.markdown(_badge_f22(linea.f22), unsafe_allow_html=True)

            if linea.es_manual:
                if col_acc_r.button("🗑️", key=f"del_egr_{i}", help="Eliminar"):
                    idxs_eliminar.append(i)
            
            i += 1

    # Eliminar extras de egresos
    # Re-implementar borrado robusto
    # Los extras están al final de la lista 'lineas'.
    # Cuantos defaults hay?
    num_defaults = len(CUENTAS_EGRESOS_DEFAULT)
    
    for idx in sorted(set(idxs_eliminar), reverse=True):
        if idx >= num_defaults:
            extra_idx = idx - num_defaults
            if 0 <= extra_idx < len(st.session_state["extras_egresos"]):
                st.session_state["extras_egresos"].pop(extra_idx)
                st.rerun()
    st.markdown("<hr class='sep'>", unsafe_allow_html=True)

    # Agregar cuenta — selector inteligente
    with st.expander("➕ Agregar otra cuenta a Egresos"):
        _render_agregar_cuenta(cuentas, "egr", "extras_egresos")

    # Total
    col1, col2, col3 = st.columns([5.2, 2, 1])
    col1.markdown("**TOTAL DE EGRESOS**")
    col2.markdown(f"**{fmt_monto(total)}**")
    col3.markdown("**(=)**")

    st.markdown('</div>', unsafe_allow_html=True)
    return total


# ---------------------------------------------------------------------------
# Sección III — GASTOS RECHAZADOS
# ---------------------------------------------------------------------------
def render_gastos_rechazados(cuentas: dict):
    st.markdown('<div class="seccion-bloque">', unsafe_allow_html=True)
    st.markdown('<div class="seccion-titulo">III. GASTOS RECHAZADOS</div>', unsafe_allow_html=True)

    lineas = construir_lineas_gastos_rechazados(cuentas, st.session_state["extras_gastos"])

    col_cod, col_nombre, col_monto, col_signo, col_f22, col_acc = st.columns([1.2, 4, 2, 0.6, 1, 1])
    col_cod.markdown("**Código**")
    col_nombre.markdown("**Cuenta**")
    col_monto.markdown("**Monto**")
    col_signo.markdown("**(**)")
    col_f22.markdown("**SC F22**")
    col_acc.markdown("**Acción**")
    st.markdown("<hr class='sep'>", unsafe_allow_html=True)

    total = 0
    idxs_eliminar = []
    lineas_fijas_len = 2

    for i, linea in enumerate(lineas):
        col_cod_r, col_nom_r, col_monto_r, col_sig_r, col_f22_r, col_acc_r = st.columns([1.2, 4, 2, 0.6, 1, 1])
        col_cod_r.markdown(f"<span class='cod'>{linea.codigo}</span>", unsafe_allow_html=True)
        nombre_display = linea.nombre + (" ⚠️" if not linea.existe_en_balance else "")
        col_nom_r.markdown(nombre_display)

        key_m = _monto_editable_key(linea.codigo + str(i), "gst")
        
        if not linea.es_manual:
             # TEXTO PLANO
            monto_val = linea.monto
            col_monto_r.markdown(f"**{fmt_monto(monto_val)}**", unsafe_allow_html=True)
            st.session_state["montos_editados"][key_m] = monto_val
            nuevo_monto = monto_val
        else:
             # INPUT EDITABLE
            monto_val = st.session_state["montos_editados"].get(key_m, linea.monto)
            nuevo_monto = col_monto_r.number_input("", value=monto_val, min_value=0, step=1000,
                                                key=key_m, label_visibility="collapsed")
            st.session_state["montos_editados"][key_m] = nuevo_monto

        total += nuevo_monto

        col_sig_r.markdown(f"<div class='signo'>{linea.signo}</div>", unsafe_allow_html=True)
        col_f22_r.markdown(_badge_f22(linea.f22), unsafe_allow_html=True)

        if linea.es_manual:
            if col_acc_r.button("🗑️", key=f"del_gst_{i}"):
                idxs_eliminar.append(i)

    for idx in sorted(set(idxs_eliminar), reverse=True):
        extra_idx = idx - lineas_fijas_len
        if 0 <= extra_idx < len(st.session_state["extras_gastos"]):
            st.session_state["extras_gastos"].pop(extra_idx)
            st.rerun()

    st.markdown("<hr class='sep'>", unsafe_allow_html=True)

    with st.expander("➕ Agregar cuenta a Gastos Rechazados"):
        _render_agregar_cuenta(cuentas, "gst", "extras_gastos")

    col1, col2, col3, col4 = st.columns([5.2, 2, 0.6, 1])
    col1.markdown("**TOTAL GASTOS RECHAZADOS**")
    col2.markdown(f"**{fmt_monto(total)}**")
    col3.markdown("**(+)**")
    col4.markdown(_badge_f22("1431"), unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)
    return total


# ---------------------------------------------------------------------------
# Sección IV — CÁLCULO
# ---------------------------------------------------------------------------
def render_calculo(cuentas: dict, total_ing: int, total_egr: int, total_gst: int):
    st.markdown("---")
    st.markdown("### IV. CÁLCULO IMPUESTO DE PRIMERA CATEGORÍA")

    # Selector de modo
    col_btn1, col_btn2, _ = st.columns([2, 2, 4])
    if col_btn1.button("❌ SIN incentivo al ahorro", type="secondary",
                       use_container_width=True):
        st.session_state["modo_calculo"] = "sin"
    if col_btn2.button("✅ CON incentivo al ahorro", type="primary",
                       use_container_width=True):
        st.session_state["modo_calculo"] = "con"

    modo = st.session_state["modo_calculo"]

    # PPM
    ppm_balance = get_valor(cuentas, "101090", "activos") or get_valor(cuentas, "105101", "activos")
    key_ppm = "monto_ppm_101090_calc"
    ppm_val = st.session_state["montos_editados"].get(key_ppm, ppm_balance)

    col_ppm1, col_ppm2 = st.columns([3, 2])
    col_ppm1.markdown("**101090 — PPM (Pagos Provisionales Mensuales)**")
    ppm_editado = col_ppm2.number_input("PPM $", value=ppm_val, min_value=0, step=1000,
                                        key=key_ppm, label_visibility="collapsed")
    st.session_state["montos_editados"][key_ppm] = ppm_editado

    st.markdown("<br>", unsafe_allow_html=True)

    # -----------------------------------------------------------------------
    if modo == "sin":
        _render_sin_incentivo(total_ing, total_egr, total_gst, ppm_editado)
    else:
        _render_con_incentivo(cuentas, total_ing, total_egr, total_gst, ppm_editado)


def _render_sin_incentivo(total_ing, total_egr, total_gst, ppm):
    resultado = calcular_sin_incentivo(total_ing, total_egr, total_gst, ppm)

    st.markdown("""
    <div class="resultado-bloque">
        <h4>❌ Sin Incentivo al Ahorro</h4>
    """, unsafe_allow_html=True)

    _fila_resultado("Total Ingresos del Ejercicio", resultado.total_ingresos, "(=)", "1600", destacado=False)
    _fila_resultado("Total Egresos del Ejercicio",  resultado.total_egresos,  "(-)", "")
    _fila_resultado("Total Gastos Rechazados",       resultado.total_gastos_rechazados, "(+)", "1431")
    st.markdown("<hr class='sep'>", unsafe_allow_html=True)
    _fila_resultado("BASE IMPONIBLE", resultado.base_imponible, "(=)", "1729", destacado=True)
    _fila_resultado(f"IDPC Tasa {TASA_IDPC*100:.1f}%", resultado.idpc_sin_incentivo, "(=)", "18",
                    clase_extra="idpc")
    _fila_resultado("101090 PPM", resultado.ppm, "(-)", "36")
    st.markdown("<hr class='sep'>", unsafe_allow_html=True)

    saldo_clase = "saldo-positivo" if resultado.saldo_sin_incentivo >= 0 else "saldo-negativo"
    _fila_resultado("SALDO", resultado.saldo_sin_incentivo, "(=)", "305",
                    destacado=True, clase_extra=saldo_clase)

    st.markdown("</div>", unsafe_allow_html=True)

    _render_export_btn(resultado, modo="sin")


def _render_con_incentivo(cuentas, total_ing, total_egr, total_gst, ppm):
    st.markdown("""
    <div class="resultado-bloque">
        <h4>✅ Con Incentivo al Ahorro (Art. 14 letra E) LIR)</h4>
    """, unsafe_allow_html=True)

    # Parámetros incentivo
    col_uf1, col_uf2 = st.columns([3, 2])
    col_uf1.markdown("**Valor UF (en pesos)**")
    valor_uf = col_uf2.number_input("UF $", value=st.session_state["valor_uf"], min_value=1,
                                    step=100, key="inp_valor_uf", label_visibility="collapsed")
    st.session_state["valor_uf"] = valor_uf

    col_uf_c1, col_uf_c2 = st.columns([3, 2])
    col_uf_c1.markdown("**Cantidad UF límite deducción**")
    uf_cant = col_uf_c2.number_input("UF cantidad", value=float(st.session_state["uf_cantidad"]),
                                     min_value=0.0, step=100.0, key="inp_uf_cant",
                                     label_visibility="collapsed")
    st.session_state["uf_cantidad"] = uf_cant
    uf_pesos = int(uf_cant * valor_uf)

    # Retiros
    retiros_balance = get_valor(cuentas, "101120", "activos")
    key_ret = "monto_retiros_101120"
    ret_val = st.session_state["montos_editados"].get(key_ret, retiros_balance)
    col_r1, col_r2 = st.columns([3, 2])
    col_r1.markdown("**101120 — Retiros del Ejercicio (históricos)**")
    ret_editado = col_r2.number_input("Retiros $", value=ret_val, min_value=0, step=1000,
                                      key=key_ret, label_visibility="collapsed")
    st.session_state["montos_editados"][key_ret] = ret_editado

    # Multas históricas
    multas_bal = get_valor(cuentas, "430102", "perdidas")
    key_mul = "monto_multas_hist_430102"
    mul_val = st.session_state["montos_editados"].get(key_mul, multas_bal)
    col_m1, col_m2 = st.columns([3, 2])
    col_m1.markdown("**430102 — Multas e Intereses (históricos)**")
    mul_editado = col_m2.number_input("Multas $", value=mul_val, min_value=0, step=100,
                                      key=key_mul, label_visibility="collapsed")
    st.session_state["montos_editados"][key_mul] = mul_editado

    # IDPC histórico
    idpc_bal = get_valor(cuentas, "430101", "perdidas")
    key_idpc = "monto_idpc_hist_430101"
    idpc_val = st.session_state["montos_editados"].get(key_idpc, idpc_bal)
    col_i1, col_i2 = st.columns([3, 2])
    col_i1.markdown("**430101 — Pago del IDPC (histórico)**")
    idpc_editado = col_i2.number_input("IDPC hist $", value=idpc_val, min_value=0, step=1000,
                                       key=key_idpc, label_visibility="collapsed")
    st.session_state["montos_editados"][key_idpc] = idpc_editado

    st.markdown("<hr class='sep'>", unsafe_allow_html=True)

    resultado = calcular_con_incentivo(
        total_ing, total_egr, total_gst, ppm,
        ret_editado, mul_editado, idpc_editado, uf_pesos
    )

    _fila_resultado("Sub Total Base Imponible",      resultado.sub_total_base,  "(=)", "")
    _fila_resultado("101120 Retiros del Ejercicio",  resultado.retiros_ejercicio, "(-)", "")
    _fila_resultado("430102 Multas e Intereses",     resultado.multas_intereses_hist, "(-)", "")
    _fila_resultado("430101 Pago del IDPC",          resultado.idpc_hist,        "(-)", "")
    st.markdown("<hr class='sep'>", unsafe_allow_html=True)
    _fila_resultado("RLI INVERTIDA",                 resultado.rli_invertida,    "(=)", "", destacado=True)
    st.markdown("<hr class='sep'>", unsafe_allow_html=True)

    col_d1, col_d2, col_d3, col_d4 = st.columns([5.2, 2, 0.6, 1])
    col_d1.markdown(
        f"Deducción incentivo al ahorro art. 14 letra E) LIR  "
        f"*(cantidad menor entre 50% RLI Invertida o {int(uf_cant):,} UF)*"
    )
    col_d2.markdown(f"**{fmt_monto(resultado.deduccion_incentivo)}**")
    col_d3.markdown("")
    col_d4.markdown(_badge_f22("1432"), unsafe_allow_html=True)

    col_e1, col_e2 = st.columns([6, 2])
    col_e1.caption(f"  → 50% RLI Invertida = {fmt_monto(resultado.porcentaje_rli)}  |  "
                   f"  Límite {int(uf_cant):,} UF = {fmt_monto(uf_pesos)}")

    st.markdown("<hr class='sep'>", unsafe_allow_html=True)
    _fila_resultado(f"IDPC Tasa {TASA_IDPC*100:.1f}%", resultado.idpc_con_incentivo, "(=)", "18",
                    clase_extra="idpc")
    _fila_resultado("101090 PPM",                    resultado.ppm,               "(-)", "36")
    st.markdown("<hr class='sep'>", unsafe_allow_html=True)

    saldo_clase = "saldo-positivo" if resultado.saldo_con_incentivo >= 0 else "saldo-negativo"
    _fila_resultado("SALDO", resultado.saldo_con_incentivo, "(=)", "305",
                    destacado=True, clase_extra=saldo_clase)

    st.markdown("</div>", unsafe_allow_html=True)

    _render_export_btn(resultado, modo="con")


def _fila_resultado(label: str, valor: int, signo: str, f22: str,
                    destacado: bool = False, clase_extra: str = ""):
    cls = "resultado-fila"
    if destacado:
        cls += " destacado"
    if clase_extra:
        cls += f" {clase_extra}"

    col1, col2, col3, col4 = st.columns([5.2, 2, 0.6, 1])
    peso = "**" if destacado else ""
    col1.markdown(f"{peso}{label}{peso}")
    col2.markdown(f"{peso}{fmt_monto(valor)}{peso}")
    col3.markdown(f"**{signo}**" if destacado else signo)
    col4.markdown(_badge_f22(f22), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Exportar a PDF
# ---------------------------------------------------------------------------
def _render_export_btn(resultado, modo: str):
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("📄 Exportar cálculo a PDF", key=f"export_pdf_{modo}", type="primary"):
        pdf_bytes = _generar_pdf(resultado, modo)
        st.download_button(
            label="⬇️ Descargar PDF",
            data=pdf_bytes,
            file_name="calculo_rli_idpc.pdf",
            mime="application/pdf",
            key=f"dl_pdf_{modo}",
        )


def _generar_pdf(resultado, modo: str) -> bytes:
    """Genera PDF con detalle completo de cuentas y resultado del cálculo."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.8*cm, rightMargin=1.8*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    emp       = st.session_state.get("empresa", {})
    cuentas   = st.session_state.get("cuentas", {})
    montos_ed = st.session_state.get("montos_editados", {})

    azul       = colors.HexColor("#2c5282")
    azul_claro = colors.HexColor("#dbeafe")
    gris_fila  = colors.HexColor("#f7fafc")
    gris_linea = colors.HexColor("#e2e8f0")

    h1   = ParagraphStyle("h1",   parent=styles["Heading1"], textColor=azul, fontSize=13, spaceAfter=2)
    h2   = ParagraphStyle("h2",   parent=styles["Heading2"], textColor=azul, fontSize=10, spaceBefore=8, spaceAfter=2)
    small= ParagraphStyle("small",parent=styles["Normal"],   fontSize=8,  textColor=colors.HexColor("#4a5568"))

    # ── Encabezado empresa ──────────────────────────────────────────────────
    story.append(Paragraph(emp.get("razon_social", ""), h1))
    dir_full = " | ".join(filter(None, [emp.get("direccion",""), emp.get("comuna","")]))
    story.append(Paragraph(f"RUT: {emp.get('rut','—')}  |  Giro: {emp.get('giro','—')}", small))
    if dir_full:
        story.append(Paragraph(f"Dirección: {dir_full}", small))
    story.append(Paragraph(f"Período: {emp.get('periodo','—')}", small))
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=azul))
    story.append(Paragraph(
        f"Determinación RLI — Régimen 14 D N°3 | {'Sin' if modo=='sin' else 'Con'} Incentivo al Ahorro",
        h2
    ))
    story.append(Spacer(1, 0.2*cm))

    # ── Helper tabla de detalle ─────────────────────────────────────────────
    COL_DET = [1.5*cm, 6.2*cm, 3*cm, 1.2*cm, 1.6*cm]

    def _tabla_detalle(filas_data, total_label, total_val):
        header = [["Código", "Cuenta", "Monto", "Sign.", "SC F22"]]
        body   = header + filas_data + [["", total_label, fmt_monto(total_val), "(=)", ""]]
        ts_det = TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), azul),
            ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("ALIGN",         (2, 0), (-1, -1), "RIGHT"),
            ("ALIGN",         (3, 0), (3, -1), "CENTER"),
            ("ROWBACKGROUNDS",(0, 1), (-1, -2), [colors.white, gris_fila]),
            ("GRID",          (0, 0), (-1, -1), 0.3, gris_linea),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("BACKGROUND",    (0, -1), (-1, -1), azul_claro),
            ("FONTNAME",      (0, -1), (-1, -1), "Helvetica-Bold"),
        ])
        t = Table(body, colWidths=COL_DET, repeatRows=1)
        t.setStyle(ts_det)
        return t

    # ── I. INGRESOS ─────────────────────────────────────────────────────────
    story.append(Paragraph("I. INGRESOS DEL EJERCICIO", h2))
    lineas_ing = construir_lineas_ingresos(cuentas, st.session_state.get("extras_ingresos", []))
    filas_ing = []
    for idx, l in enumerate(lineas_ing):
        key   = _monto_editable_key(l.codigo + str(idx), "ing")
        monto = montos_ed.get(key, l.monto)
        filas_ing.append([l.codigo, l.nombre, fmt_monto(monto), l.signo, l.f22])
    story.append(_tabla_detalle(filas_ing, "TOTAL INGRESOS", resultado.total_ingresos))
    story.append(Spacer(1, 0.35*cm))

    # ── II. EGRESOS ─────────────────────────────────────────────────────────
    story.append(Paragraph("II. EGRESOS DEL EJERCICIO", h2))
    lineas_egr = construir_lineas_egresos(cuentas, st.session_state.get("extras_egresos", []))
    filas_egr  = []
    rem_bloque = []   # acumula filas de remuneraciones mientras se procesan
    rem_total  = 0

    idx_e = 0
    while idx_e < len(lineas_egr):
        l = lineas_egr[idx_e]
        if l.codigo in CODIGOS_REMUNERACIONES:
            key   = _monto_editable_key(l.codigo + str(idx_e), "egr")
            monto = montos_ed.get(key, l.monto)
            rem_bloque.append([f"  {l.codigo}", f"  └ {l.nombre}", fmt_monto(monto), "", ""])
            rem_total += monto
            idx_e += 1
        else:
            if rem_bloque:
                # Añadir extras remuneraciones
                for j2, er in enumerate(st.session_state.get("extras_remuneraciones", [])):
                    key_r = _monto_editable_key(er["codigo"] + f"rem{j2}", "rem")
                    mv    = montos_ed.get(key_r, er["monto"])
                    rem_bloque.append([f"  {er['codigo']}", f"  └ {er['nombre']}", fmt_monto(mv), "", ""])
                    rem_total += mv
                # Fila resumen remuneraciones
                filas_egr.append(["", "Remuneraciones Pagadas", fmt_monto(rem_total), "+", "1411"])
                filas_egr.extend(rem_bloque)
                rem_bloque = []
                rem_total  = 0

            key   = _monto_editable_key(l.codigo + str(idx_e), "egr")
            monto = montos_ed.get(key, l.monto)
            filas_egr.append([l.codigo, l.nombre, fmt_monto(monto), l.signo, l.f22])
            idx_e += 1

    # Si termina con bloque rem
    if rem_bloque:
        for j2, er in enumerate(st.session_state.get("extras_remuneraciones", [])):
            key_r = _monto_editable_key(er["codigo"] + f"rem{j2}", "rem")
            mv    = montos_ed.get(key_r, er["monto"])
            rem_bloque.append([f"  {er['codigo']}", f"  └ {er['nombre']}", fmt_monto(mv), "", ""])
            rem_total += mv
        filas_egr.append(["", "Remuneraciones Pagadas", fmt_monto(rem_total), "+", "1411"])
        filas_egr.extend(rem_bloque)

    story.append(_tabla_detalle(filas_egr, "TOTAL EGRESOS", resultado.total_egresos))
    story.append(Spacer(1, 0.35*cm))

    # ── III. GASTOS RECHAZADOS ───────────────────────────────────────────────
    story.append(Paragraph("III. GASTOS RECHAZADOS", h2))
    lineas_gst = construir_lineas_gastos_rechazados(cuentas, st.session_state.get("extras_gastos", []))
    filas_gst  = []
    for idx, l in enumerate(lineas_gst):
        key   = _monto_editable_key(l.codigo + str(idx), "gst")
        monto = montos_ed.get(key, l.monto)
        filas_gst.append([l.codigo, l.nombre, fmt_monto(monto), l.signo, l.f22])
    story.append(_tabla_detalle(filas_gst, "TOTAL GASTOS RECHAZADOS", resultado.total_gastos_rechazados))
    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=gris_linea))
    story.append(Spacer(1, 0.1*cm))

    # ── IV. CÁLCULO RLI / IDPC ──────────────────────────────────────────────
    story.append(Paragraph(
        f"IV. CÁLCULO {'SIN' if modo=='sin' else 'CON'} INCENTIVO AL AHORRO", h2
    ))

    col_calc = [8.5*cm, 3.5*cm, 1.5*cm, 2*cm]

    def fc(etiqueta, valor, signo="", f22=""):
        return [etiqueta, fmt_monto(valor), signo, f22]

    if modo == "sin":
        data_calc = [
            ["Concepto", "Monto", "Sign.", "SC F22"],
            fc("Total Ingresos del Ejercicio",    resultado.total_ingresos,          "(=)", "1600"),
            fc("Total Egresos del Ejercicio",     resultado.total_egresos,           "(-)", ""),
            fc("Total Gastos Rechazados",         resultado.total_gastos_rechazados, "(+)", "1431"),
            ["", "", "", ""],
            fc("BASE IMPONIBLE",                  resultado.base_imponible,          "(=)", "1729"),
            fc(f"IDPC Tasa {TASA_IDPC*100:.1f}%",resultado.idpc_sin_incentivo,      "(=)", "18"),
            fc("101090 PPM",                      resultado.ppm,                     "(-)", "36"),
            ["", "", "", ""],
            fc("SALDO",                           resultado.saldo_sin_incentivo,     "(=)", "305"),
        ]
        destacadas = {5, 9}
    else:
        uf_pesos = st.session_state.get("valor_uf", 38000) * st.session_state.get("uf_cantidad", UF_DEFECTO)
        uf_cant  = int(st.session_state.get("uf_cantidad", UF_DEFECTO))
        data_calc = [
            ["Concepto", "Monto", "Sign.", "SC F22"],
            fc("Total Ingresos del Ejercicio",    resultado.total_ingresos,          "(=)", "1600"),
            fc("Total Egresos del Ejercicio",     resultado.total_egresos,           "(-)", ""),
            fc("Total Gastos Rechazados",         resultado.total_gastos_rechazados, "(+)", "1431"),
            ["", "", "", ""],
            fc("Sub Total Base Imponible",        resultado.sub_total_base,          "(=)", ""),
            fc("101120 Retiros del Ejercicio",    resultado.retiros_ejercicio,       "(-)", ""),
            fc("430102 Multas e Intereses",       resultado.multas_intereses_hist,   "(-)", ""),
            fc("430101 Pago del IDPC",            resultado.idpc_hist,               "(-)", ""),
            ["", "", "", ""],
            fc("RLI INVERTIDA",                   resultado.rli_invertida,           "(=)", ""),
            fc(
                f"Deducción incentivo art. 14 E) LIR  "
                f"[50% RLI = {fmt_monto(resultado.porcentaje_rli)}  |  "
                f"Límite {uf_cant:,} UF = {fmt_monto(uf_pesos)}]",
                resultado.deduccion_incentivo, "", "1432"
            ),
            ["", "", "", ""],
            fc(f"IDPC Tasa {TASA_IDPC*100:.1f}%", resultado.idpc_con_incentivo,    "(=)", "18"),
            fc("101090 PPM",                       resultado.ppm,                    "(-)", "36"),
            ["", "", "", ""],
            fc("SALDO",                            resultado.saldo_con_incentivo,    "(=)", "305"),
        ]
        destacadas = {5, 10, 16}

    ts_calc = TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), azul),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("ALIGN",         (1, 0), (1, -1), "RIGHT"),
        ("ALIGN",         (2, 0), (3, -1), "CENTER"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, gris_fila]),
        ("GRID",          (0, 0), (-1, -1), 0.4, gris_linea),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])
    for row_idx in destacadas:
        if row_idx < len(data_calc):
            ts_calc.add("FONTNAME",   (0, row_idx), (-1, row_idx), "Helvetica-Bold")
            ts_calc.add("BACKGROUND", (0, row_idx), (-1, row_idx), azul_claro)
            ts_calc.add("FONTSIZE",   (0, row_idx), (-1, row_idx), 10)

    t_calc = Table(data_calc, colWidths=col_calc, repeatRows=1)
    t_calc.setStyle(ts_calc)
    story.append(t_calc)

    doc.build(story)
    return buf.getvalue()




# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    render_sidebar()

    st.markdown("# 📊 Determinación RLI — Impuesto Primera Categoría")
    st.caption("Régimen 14 D N°3 | Tasa IDPC: 12,5%")
    st.markdown("---")

    empresa_ok = render_empresa_header()
    if not empresa_ok:
        return

    regimen = st.session_state.get("regimen", "14 D N°3")

    if regimen == "14 A":
        render_14a_placeholder()
        return

    # --- Régimen 14 D N°3 ---
    cuentas = st.session_state["cuentas"]

    total_ing = render_ingresos(cuentas)
    st.markdown("<br>", unsafe_allow_html=True)
    total_egr = render_egresos(cuentas)
    st.markdown("<br>", unsafe_allow_html=True)
    total_gst = render_gastos_rechazados(cuentas)

    render_calculo(cuentas, total_ing, total_egr, total_gst)


if __name__ == "__main__":
    main()