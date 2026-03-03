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
    CODIGOS_INGRESOS_GIRO,
    CODIGOS_EXISTENCIAS,
    CUENTAS_EGRESOS_DEFAULT,
    fmt_monto,
    UF_DEFECTO,
    TASA_IDPC,
)
from regimen_14a import render_14a_placeholder
from export_pdf import render_export_btn

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
        "extras_ingresos_giro": [],
        "extras_existencias_suma": [],
        "extras_existencias_resta": [],
        "eliminadas_egr": [],
        "eliminadas_gst": [],
        "eliminadas_calc": [],
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

    # Inicializar lista de extras_ingresos_giro si no existe
    if "extras_ingresos_giro" not in st.session_state:
        st.session_state["extras_ingresos_giro"] = []

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
    elim_ing = set(st.session_state.get("eliminadas_ing", []))

    # Vamos a iterar con while para poder agrupar ingresos del giro
    i = 0
    n = len(lineas)

    while i < n:
        linea = lineas[i]

        # Detectar inicio de bloque ingresos del giro
        if linea.codigo in CODIGOS_INGRESOS_GIRO:
            # Agrupar todas las líneas consecutivas que sean de ingresos del giro
            grupo_giro = []
            while i < n and lineas[i].codigo in CODIGOS_INGRESOS_GIRO:
                grupo_giro.append((i, lineas[i]))
                i += 1

            # --- Pre-calcular total para mostrarlo ARRIBA ---
            total_giro_display = 0

            # 1. Sumar/restar fijos según signo (manuales leen del widget state)
            for idx_orig, l_giro in grupo_giro:
                if l_giro.codigo in elim_ing:
                    continue
                if l_giro.es_manual:
                    key_m = _monto_editable_key(l_giro.codigo + str(idx_orig), "ing")
                    if key_m in st.session_state:
                        val = st.session_state[key_m]
                    else:
                        val = st.session_state["montos_editados"].get(key_m, l_giro.monto)
                else:
                    val = int(l_giro.monto)
                if l_giro.signo == "-":
                    total_giro_display -= int(val)
                else:
                    total_giro_display += int(val)

            # 2. Sumar extras (Manuales => Usar widget o valor guardado)
            for j, extra_giro in enumerate(st.session_state["extras_ingresos_giro"]):
                key_giro = _monto_editable_key(extra_giro["codigo"] + f"igiro{j}", "igiro")
                if key_giro in st.session_state:
                    val = st.session_state[key_giro]
                else:
                    val = st.session_state["montos_editados"].get(key_giro, extra_giro["monto"])
                total_giro_display += int(val)

            # --- Renderizar Resumen Ingresos del Giro (ARRIBA) ---
            total += total_giro_display

            cg1, cg2, cg3, cg4, cg5, cg6 = st.columns([1.2, 4, 2, 0.6, 1, 1])
            cg1.markdown("")
            cg2.markdown("<strong>Ingresos del Giro Percibidos (Total)</strong>", unsafe_allow_html=True)
            cg3.markdown(f"<strong>{fmt_monto(total_giro_display)}</strong>", unsafe_allow_html=True)
            cg4.markdown("<div class='signo'>+</div>", unsafe_allow_html=True)
            cg5.markdown(_badge_f22("1400"), unsafe_allow_html=True)

            # --- Renderizar bloque colapsable indentado ---
            _col_indent, col_expander = st.columns([0.15, 9.85])
            with col_expander:
                st.markdown(
                    "<div style='border-left: 3px solid #CBD5E0; padding-left: 10px; margin-top:-16px; margin-bottom:4px;'>",
                    unsafe_allow_html=True
                )
                with st.expander("📝 Ver detalle Ingresos del Giro", expanded=False):
                    # 1. Cuentas fijas del grupo
                    for idx_orig, l_giro in grupo_giro:
                        if l_giro.codigo in elim_ing:
                            continue
                        col_cod_r, col_nom_r, col_monto_r, col_sig_r, col_f22_r, col_acc_r = st.columns(
                            [1.2, 4, 2, 0.6, 1, 1]
                        )
                        col_cod_r.markdown(f"<span class='cod'>{l_giro.codigo}</span>", unsafe_allow_html=True)

                        nom = l_giro.nombre
                        if not l_giro.existe_en_balance:
                            nom += " ⚠️"
                        col_nom_r.markdown(nom)

                        key_m = _monto_editable_key(l_giro.codigo + str(idx_orig), "ing")

                        if l_giro.es_manual:
                            # Cuenta manual fija — monto editable
                            monto_val = st.session_state["montos_editados"].get(key_m, l_giro.monto)
                            nuevo_monto = col_monto_r.number_input(
                                "", value=monto_val, min_value=0, step=1000,
                                key=key_m, label_visibility="collapsed"
                            )
                            st.session_state["montos_editados"][key_m] = nuevo_monto
                        else:
                            # Cuenta del balance — texto plano
                            monto_val = l_giro.monto
                            col_monto_r.markdown(f"**{fmt_monto(monto_val)}**", unsafe_allow_html=True)
                            st.session_state["montos_editados"][key_m] = monto_val

                        # Mostrar signo
                        col_sig_r.markdown(f"<div class='signo'>{l_giro.signo}</div>", unsafe_allow_html=True)

                        # Botón eliminar para cuentas extraídas
                        if not l_giro.es_manual:
                            if col_acc_r.button("🗑️", key=f"del_ingfijo_{l_giro.codigo}"):
                                st.session_state.setdefault("eliminadas_ing", []).append(l_giro.codigo)
                                st.rerun()

                    # 2. Extras de ingresos del giro
                    for j, extra_giro in enumerate(st.session_state["extras_ingresos_giro"]):
                        key_giro = _monto_editable_key(extra_giro["codigo"] + f"igiro{j}", "igiro")
                        monto_giro_val = st.session_state["montos_editados"].get(
                            key_giro, extra_giro["monto"]
                        )

                        cr1, cr2, col_m_extra, cr4, cr5, cr6 = st.columns([1.2, 4, 2, 0.6, 1, 1])

                        cr1.markdown(f"<span class='cod'>{extra_giro['codigo']}</span>",
                                     unsafe_allow_html=True)
                        cr2.markdown(extra_giro["nombre"])

                        monto_giro_nuevo = col_m_extra.number_input(
                            "", value=monto_giro_val, min_value=0, step=1000,
                            key=key_giro, label_visibility="collapsed"
                        )
                        st.session_state["montos_editados"][key_giro] = monto_giro_nuevo

                        if cr6.button("🗑️", key=f"del_igiro_{j}"):
                            st.session_state["extras_ingresos_giro"].pop(j)
                            st.rerun()

                    # Botón agregar subcuenta DENTRO del expander
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown("###### Agregar subcuenta a Ingresos del Giro")
                    _render_agregar_cuenta(cuentas, "igiro", "extras_ingresos_giro")

                st.markdown("</div>", unsafe_allow_html=True)

        else:
            # Cuenta eliminada → saltar
            if linea.codigo in elim_ing:
                i += 1
                continue

            # Renderizado normal de otras cuentas
            col_cod_r, col_nom_r, col_monto_r, col_sig_r, col_f22_r, col_acc_r = st.columns(
                [1.2, 4, 2, 0.6, 1, 1]
            )
            col_cod_r.markdown(f"<span class='cod'>{linea.codigo}</span>", unsafe_allow_html=True)

            nombre_display = linea.nombre + (" ⚠️" if not linea.existe_en_balance else "")
            col_nom_r.markdown(nombre_display)

            key_m = _monto_editable_key(linea.codigo + str(i), "ing")

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

            # Botón eliminar — para extraídas y manuales
            if linea.es_manual:
                if col_acc_r.button("🗑️", key=f"del_ing_{i}", help="Eliminar"):
                    idxs_a_eliminar.append(i)
            else:
                if col_acc_r.button("🗑️", key=f"del_ingfijo_{linea.codigo}", help="Eliminar"):
                    st.session_state.setdefault("eliminadas_ing", []).append(linea.codigo)
                    st.rerun()

            i += 1

    # Eliminar extras de ingresos
    from regimen_14d3 import CUENTAS_INGRESOS_DEFAULT
    num_defaults_ing = len(CUENTAS_INGRESOS_DEFAULT)

    for idx in sorted(set(idxs_a_eliminar), reverse=True):
        if idx >= num_defaults_ing:
            extra_idx = idx - num_defaults_ing
            if 0 <= extra_idx < len(st.session_state["extras_ingresos"]):
                st.session_state["extras_ingresos"].pop(extra_idx)
                st.rerun()

    st.markdown("<hr class='sep'>", unsafe_allow_html=True)

    # Agregar cuenta — selector inteligente
    with st.expander("➕ Agregar otra cuenta a Ingresos"):
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

    # Inicializar listas extras si no existen
    if "extras_remuneraciones" not in st.session_state:
        st.session_state["extras_remuneraciones"] = []
    if "extras_existencias_suma" not in st.session_state:
        st.session_state["extras_existencias_suma"] = []
    if "extras_existencias_resta" not in st.session_state:
        st.session_state["extras_existencias_resta"] = []

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
    elim_egr = set(st.session_state.get("eliminadas_egr", []))
    
    # Vamos a iterar usando while para poder agrupar existencias y remuneraciones
    i = 0
    n = len(lineas)
    
    while i < n:
        linea = lineas[i]

        # ================================================================
        # Detectar inicio de bloque EXISTENCIAS
        # ================================================================
        if linea.codigo in CODIGOS_EXISTENCIAS:
            grupo_exist = []
            while i < n and lineas[i].codigo in CODIGOS_EXISTENCIAS:
                grupo_exist.append((i, lineas[i]))
                i += 1

            # --- Pre-calcular total (excluyendo eliminadas) ---
            total_exist_display = 0

            for idx_orig, l_ex in grupo_exist:
                if l_ex.codigo in elim_egr:
                    continue
                if l_ex.es_manual:
                    key_m = _monto_editable_key(l_ex.codigo + str(idx_orig), "egr")
                    if key_m in st.session_state:
                        val = st.session_state[key_m]
                    else:
                        val = st.session_state["montos_editados"].get(key_m, l_ex.monto)
                else:
                    val = int(l_ex.monto)
                if l_ex.signo == "-":
                    total_exist_display -= int(val)
                else:
                    total_exist_display += int(val)

            for j, extra_s in enumerate(st.session_state["extras_existencias_suma"]):
                key_es = _monto_editable_key(extra_s["codigo"] + f"exs{j}", "exs")
                if key_es in st.session_state:
                    val = st.session_state[key_es]
                else:
                    val = st.session_state["montos_editados"].get(key_es, extra_s["monto"])
                total_exist_display += int(val)

            for j, extra_r in enumerate(st.session_state["extras_existencias_resta"]):
                key_er = _monto_editable_key(extra_r["codigo"] + f"exr{j}", "exr")
                if key_er in st.session_state:
                    val = st.session_state[key_er]
                else:
                    val = st.session_state["montos_editados"].get(key_er, extra_r["monto"])
                total_exist_display -= int(val)

            # --- Renderizar Resumen Existencias (ARRIBA) ---
            total += total_exist_display

            ce1, ce2, ce3, ce4, ce5, ce6 = st.columns([1.2, 4, 2, 0.6, 1, 1])
            ce1.markdown("")
            ce2.markdown("<strong>Existencias, Insumos y Servicios del Negocio, Pagados (Total)</strong>", unsafe_allow_html=True)
            ce3.markdown(f"<strong>{fmt_monto(total_exist_display)}</strong>", unsafe_allow_html=True)
            ce4.markdown("<div class='signo'>+</div>", unsafe_allow_html=True)
            ce5.markdown(_badge_f22("1409"), unsafe_allow_html=True)

            # --- Bloque colapsable ---
            _col_indent, col_expander = st.columns([0.15, 9.85])
            with col_expander:
                st.markdown(
                    "<div style='border-left: 3px solid #CBD5E0; padding-left: 10px; margin-top:-16px; margin-bottom:4px;'>",
                    unsafe_allow_html=True
                )
                with st.expander("📝 Ver detalle Existencias, Insumos y Servicios", expanded=False):
                    for idx_orig, l_ex in grupo_exist:
                        if l_ex.codigo in elim_egr:
                            continue
                        col_cod_r, col_nom_r, col_monto_r, col_sig_r, col_f22_r, col_acc_r = st.columns(
                            [1.2, 4, 2, 0.6, 1, 1]
                        )
                        col_cod_r.markdown(f"<span class='cod'>{l_ex.codigo}</span>", unsafe_allow_html=True)
                        nom = l_ex.nombre
                        if not l_ex.existe_en_balance:
                            nom += " ⚠️"
                        col_nom_r.markdown(nom)

                        key_m = _monto_editable_key(l_ex.codigo + str(idx_orig), "egr")

                        if l_ex.es_manual:
                            monto_val = st.session_state["montos_editados"].get(key_m, l_ex.monto)
                            nuevo_monto = col_monto_r.number_input(
                                "", value=monto_val, min_value=0, step=1000,
                                key=key_m, label_visibility="collapsed"
                            )
                            st.session_state["montos_editados"][key_m] = nuevo_monto
                        else:
                            monto_val = l_ex.monto
                            col_monto_r.markdown(f"**{fmt_monto(monto_val)}**", unsafe_allow_html=True)
                            st.session_state["montos_editados"][key_m] = monto_val

                        col_sig_r.markdown(f"<div class='signo'>{l_ex.signo}</div>", unsafe_allow_html=True)

                        # Botón eliminar para cuentas extraídas
                        if not l_ex.es_manual:
                            if col_acc_r.button("🗑️", key=f"del_exfijo_{l_ex.codigo}"):
                                st.session_state["eliminadas_egr"].append(l_ex.codigo)
                                st.rerun()

                    # Extras que SUMAN (+)
                    for j, extra_s in enumerate(st.session_state["extras_existencias_suma"]):
                        key_es = _monto_editable_key(extra_s["codigo"] + f"exs{j}", "exs")
                        monto_es_val = st.session_state["montos_editados"].get(key_es, extra_s["monto"])
                        cr1, cr2, col_m_extra, cr4, cr5, cr6 = st.columns([1.2, 4, 2, 0.6, 1, 1])
                        cr1.markdown(f"<span class='cod'>{extra_s['codigo']}</span>", unsafe_allow_html=True)
                        cr2.markdown(extra_s["nombre"])
                        monto_es_nuevo = col_m_extra.number_input(
                            "", value=monto_es_val, min_value=0, step=1000,
                            key=key_es, label_visibility="collapsed"
                        )
                        st.session_state["montos_editados"][key_es] = monto_es_nuevo
                        cr4.markdown("<div class='signo'>+</div>", unsafe_allow_html=True)
                        if cr6.button("🗑️", key=f"del_exs_{j}"):
                            st.session_state["extras_existencias_suma"].pop(j)
                            st.rerun()

                    # Extras que RESTAN (-)
                    for j, extra_r in enumerate(st.session_state["extras_existencias_resta"]):
                        key_er = _monto_editable_key(extra_r["codigo"] + f"exr{j}", "exr")
                        monto_er_val = st.session_state["montos_editados"].get(key_er, extra_r["monto"])
                        cr1, cr2, col_m_extra, cr4, cr5, cr6 = st.columns([1.2, 4, 2, 0.6, 1, 1])
                        cr1.markdown(f"<span class='cod'>{extra_r['codigo']}</span>", unsafe_allow_html=True)
                        cr2.markdown(extra_r["nombre"])
                        monto_er_nuevo = col_m_extra.number_input(
                            "", value=monto_er_val, min_value=0, step=1000,
                            key=key_er, label_visibility="collapsed"
                        )
                        st.session_state["montos_editados"][key_er] = monto_er_nuevo
                        cr4.markdown("<div class='signo'>-</div>", unsafe_allow_html=True)
                        if cr6.button("🗑️", key=f"del_exr_{j}"):
                            st.session_state["extras_existencias_resta"].pop(j)
                            st.rerun()

                    # Botones agregar subcuenta
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown("###### ➕ Agregar subcuenta que SUMA (+)")
                    _render_agregar_cuenta(cuentas, "exs", "extras_existencias_suma")
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown("###### ➖ Agregar subcuenta que RESTA (-)")
                    _render_agregar_cuenta(cuentas, "exr", "extras_existencias_resta")

                st.markdown("</div>", unsafe_allow_html=True)
        
        # ================================================================
        # Detectar inicio de bloque REMUNERACIONES
        # ================================================================
        elif linea.codigo in CODIGOS_REMUNERACIONES:
            grupo_rem = []
            while i < n and lineas[i].codigo in CODIGOS_REMUNERACIONES:
                grupo_rem.append((i, lineas[i]))
                i += 1
            
            # --- Pre-calcular total (excluyendo eliminadas) ---
            total_rem_display = 0
            for idx_orig, l_rem in grupo_rem:
                if l_rem.codigo in elim_egr:
                    continue
                total_rem_display += int(l_rem.monto)
            
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
                    for idx_orig, l_rem in grupo_rem:
                        if l_rem.codigo in elim_egr:
                            continue
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

                        # Botón eliminar para cuentas extraídas
                        if col_acc_r.button("🗑️", key=f"del_remfijo_{l_rem.codigo}"):
                            st.session_state["eliminadas_egr"].append(l_rem.codigo)
                            st.rerun()

                    # Extras de remuneraciones
                    for j, extra_rem in enumerate(st.session_state["extras_remuneraciones"]):
                        key_rem = _monto_editable_key(extra_rem["codigo"] + f"rem{j}", "rem")
                        monto_rem_val = st.session_state["montos_editados"].get(key_rem, extra_rem["monto"])
                        cr1, cr2, col_m_extra, cr4, cr5, cr6 = st.columns([1.2, 4, 2, 0.6, 1, 1])
                        cr1.markdown(f"<span class='cod'>{extra_rem['codigo']}</span>", unsafe_allow_html=True)
                        cr2.markdown(extra_rem["nombre"])
                        monto_rem_nuevo = col_m_extra.number_input(
                            "", value=monto_rem_val, min_value=0, step=1000,
                            key=key_rem, label_visibility="collapsed"
                        )
                        st.session_state["montos_editados"][key_rem] = monto_rem_nuevo
                        if cr6.button("🗑️", key=f"del_rem_{j}"):
                            st.session_state["extras_remuneraciones"].pop(j)
                            st.rerun()

                    # Botón agregar subcuenta
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown("###### Agregar subcuenta a Remuneraciones")
                    _render_agregar_cuenta(cuentas, "rem", "extras_remuneraciones")
                
                st.markdown("</div>", unsafe_allow_html=True)

        else:
            # Cuenta eliminada → saltar
            if linea.codigo in elim_egr:
                i += 1
                continue

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

            # Botón eliminar — para extraídas y manuales
            if linea.es_manual:
                if col_acc_r.button("🗑️", key=f"del_egr_{i}", help="Eliminar"):
                    idxs_eliminar.append(i)
            else:
                if col_acc_r.button("🗑️", key=f"del_egrfijo_{linea.codigo}", help="Eliminar"):
                    st.session_state["eliminadas_egr"].append(linea.codigo)
                    st.rerun()
            
            i += 1

    # Eliminar extras de egresos
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
    elim_gst = set(st.session_state.get("eliminadas_gst", []))

    for i, linea in enumerate(lineas):
        # Saltar eliminadas
        if linea.codigo in elim_gst and not linea.es_manual:
            continue

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

        # Botón eliminar — para extraídas y manuales
        if linea.es_manual:
            if col_acc_r.button("🗑️", key=f"del_gst_{i}"):
                idxs_eliminar.append(i)
        else:
            if col_acc_r.button("🗑️", key=f"del_gstfijo_{linea.codigo}", help="Eliminar"):
                st.session_state["eliminadas_gst"].append(linea.codigo)
                st.rerun()

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
    elim_calc = set(st.session_state.get("eliminadas_calc", []))
    ppm_balance = get_valor(cuentas, "101090", "activos") or get_valor(cuentas, "105101", "activos")
    key_ppm = "monto_ppm_101090_calc"

    if "101090" not in elim_calc:
        ppm_val = ppm_balance
        st.session_state["montos_editados"][key_ppm] = ppm_val
        col_ppm1, col_ppm2, col_ppm3 = st.columns([3, 2, 1])
        col_ppm1.markdown("**101090 — PPM (Pagos Provisionales Mensuales)**")
        col_ppm2.markdown(f"**{fmt_monto(ppm_val)}**")
        if col_ppm3.button("🗑️", key="del_calc_ppm", help="Eliminar"):
            st.session_state["eliminadas_calc"].append("101090")
            st.rerun()
        ppm_editado = ppm_val
    else:
        ppm_editado = 0
        st.session_state["montos_editados"][key_ppm] = 0

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

    render_export_btn(resultado, modo="sin")


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

    elim_calc = set(st.session_state.get("eliminadas_calc", []))

    # Retiros
    retiros_balance = get_valor(cuentas, "101120", "activos")
    key_ret = "monto_retiros_101120"
    if "101120" not in elim_calc:
        ret_editado = retiros_balance
        st.session_state["montos_editados"][key_ret] = ret_editado
        col_r1, col_r2, col_r3 = st.columns([3, 2, 1])
        col_r1.markdown("**101120 — Retiros del Ejercicio (históricos)**")
        col_r2.markdown(f"**{fmt_monto(ret_editado)}**")
        if col_r3.button("🗑️", key="del_calc_retiros", help="Eliminar"):
            st.session_state["eliminadas_calc"].append("101120")
            st.rerun()
    else:
        ret_editado = 0
        st.session_state["montos_editados"][key_ret] = 0

    # Multas históricas
    multas_bal = get_valor(cuentas, "430102", "perdidas")
    key_mul = "monto_multas_hist_430102"
    if "430102_calc" not in elim_calc:
        mul_editado = multas_bal
        st.session_state["montos_editados"][key_mul] = mul_editado
        col_m1, col_m2, col_m3 = st.columns([3, 2, 1])
        col_m1.markdown("**430102 — Multas e Intereses (históricos)**")
        col_m2.markdown(f"**{fmt_monto(mul_editado)}**")
        if col_m3.button("🗑️", key="del_calc_multas", help="Eliminar"):
            st.session_state["eliminadas_calc"].append("430102_calc")
            st.rerun()
    else:
        mul_editado = 0
        st.session_state["montos_editados"][key_mul] = 0

    # IDPC histórico
    idpc_bal = get_valor(cuentas, "430101", "perdidas")
    key_idpc = "monto_idpc_hist_430101"
    if "430101_calc" not in elim_calc:
        idpc_editado = idpc_bal
        st.session_state["montos_editados"][key_idpc] = idpc_editado
        col_i1, col_i2, col_i3 = st.columns([3, 2, 1])
        col_i1.markdown("**430101 — Pago del IDPC (histórico)**")
        col_i2.markdown(f"**{fmt_monto(idpc_editado)}**")
        if col_i3.button("🗑️", key="del_calc_idpc", help="Eliminar"):
            st.session_state["eliminadas_calc"].append("430101_calc")
            st.rerun()
    else:
        idpc_editado = 0
        st.session_state["montos_editados"][key_idpc] = 0

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

    render_export_btn(resultado, modo="con")


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