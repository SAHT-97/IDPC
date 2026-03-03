import io
import streamlit as st

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from regimen_14d3 import (
    construir_lineas_ingresos,
    construir_lineas_egresos,
    construir_lineas_gastos_rechazados,
    CODIGOS_INGRESOS_GIRO,
    CODIGOS_EXISTENCIAS,
    CODIGOS_REMUNERACIONES,
    fmt_monto,
    UF_DEFECTO,
    TASA_IDPC
)

def _monto_editable_key(codigo: str, seccion: str) -> str:
    return f"monto_{seccion}_{codigo}"

def render_export_btn(resultado, modo: str):
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("📄 Exportar cálculo a PDF", key=f"export_pdf_{modo}", type="primary"):
        pdf_bytes = generar_pdf(resultado, modo)
        st.download_button(
            label="⬇️ Descargar PDF",
            data=pdf_bytes,
            file_name="calculo_rli_idpc.pdf",
            mime="application/pdf",
            key=f"dl_pdf_{modo}",
        )

def generar_pdf(resultado, modo: str) -> bytes:
    """Genera PDF con detalle completo de cuentas y resultado del cálculo, filtrando valores en cero."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=1.8*cm, rightMargin=1.8*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []

    emp       = st.session_state.get("empresa", {})
    cuentas   = st.session_state.get("cuentas", {})
    montos_ed = st.session_state.get("montos_editados", {})
    elim_ing  = set(st.session_state.get("eliminadas_ing", []))
    elim_egr  = set(st.session_state.get("eliminadas_egr", []))
    elim_gst  = set(st.session_state.get("eliminadas_gst", []))

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
    giro_bloque = []   # acumula filas de ingresos del giro mientras se procesan
    giro_total  = 0

    idx_i = 0
    while idx_i < len(lineas_ing):
        l = lineas_ing[idx_i]
        
        if l.codigo in elim_ing:
            idx_i += 1
            continue

        if l.codigo in CODIGOS_INGRESOS_GIRO:
            key   = _monto_editable_key(l.codigo + str(idx_i), "ing")
            monto = montos_ed.get(key, l.monto)
            if monto != 0:
                giro_bloque.append([f"  {l.codigo}", f"  └ {l.nombre}", fmt_monto(monto), l.signo, ""])
            if l.signo == "-":
                giro_total -= monto
            else:
                giro_total += monto
            idx_i += 1
        else:
            if giro_bloque or giro_total != 0:
                # Añadir extras ingresos del giro
                for j2, eg in enumerate(st.session_state.get("extras_ingresos_giro", [])):
                    key_g = _monto_editable_key(eg["codigo"] + f"igiro{j2}", "igiro")
                    mv    = montos_ed.get(key_g, eg["monto"])
                    if mv != 0:
                        giro_bloque.append([f"  {eg['codigo']}", f"  └ {eg['nombre']}", fmt_monto(mv), "", ""])
                    giro_total += mv
                # Fila resumen ingresos del giro
                if giro_total != 0 or giro_bloque:
                    filas_ing.append(["", "Ingresos del Giro Percibidos", fmt_monto(giro_total), "+", "1400"])
                    filas_ing.extend(giro_bloque)
                giro_bloque = []
                giro_total  = 0

            key   = _monto_editable_key(l.codigo + str(idx_i), "ing")
            monto = montos_ed.get(key, l.monto)
            if monto != 0:
                filas_ing.append([l.codigo, l.nombre, fmt_monto(monto), l.signo, l.f22])
            idx_i += 1

    # Si termina con bloque giro
    if giro_bloque or giro_total != 0:
        for j2, eg in enumerate(st.session_state.get("extras_ingresos_giro", [])):
            key_g = _monto_editable_key(eg["codigo"] + f"igiro{j2}", "igiro")
            mv    = montos_ed.get(key_g, eg["monto"])
            if mv != 0:
                giro_bloque.append([f"  {eg['codigo']}", f"  └ {eg['nombre']}", fmt_monto(mv), "", ""])
            giro_total += mv
        if giro_total != 0 or giro_bloque:
            filas_ing.append(["", "Ingresos del Giro Percibidos", fmt_monto(giro_total), "+", "1400"])
            filas_ing.extend(giro_bloque)

    story.append(_tabla_detalle(filas_ing, "TOTAL INGRESOS", resultado.total_ingresos))
    story.append(Spacer(1, 0.35*cm))

    # ── II. EGRESOS ─────────────────────────────────────────────────────────
    story.append(Paragraph("II. EGRESOS DEL EJERCICIO", h2))
    lineas_egr = construir_lineas_egresos(cuentas, st.session_state.get("extras_egresos", []))
    filas_egr  = []
    exist_bloque = []
    exist_total  = 0
    rem_bloque = []
    rem_total  = 0

    idx_e = 0
    while idx_e < len(lineas_egr):
        l = lineas_egr[idx_e]

        if l.codigo in elim_egr:
            idx_e += 1
            continue

        if l.codigo in CODIGOS_EXISTENCIAS:
            key   = _monto_editable_key(l.codigo + str(idx_e), "egr")
            monto = montos_ed.get(key, l.monto)
            if monto != 0:
                exist_bloque.append([f"  {l.codigo}", f"  └ {l.nombre}", fmt_monto(monto), l.signo, ""])
            if l.signo == "-":
                exist_total -= monto
            else:
                exist_total += monto
            idx_e += 1

        elif l.codigo in CODIGOS_REMUNERACIONES:
            # Flush existencias if pending
            if exist_bloque or exist_total != 0:
                for j2, es in enumerate(st.session_state.get("extras_existencias_suma", [])):
                    key_s = _monto_editable_key(es["codigo"] + f"exs{j2}", "exs")
                    mv = montos_ed.get(key_s, es["monto"])
                    if mv != 0:
                        exist_bloque.append([f"  {es['codigo']}", f"  └ {es['nombre']}", fmt_monto(mv), "+", ""])
                    exist_total += mv
                for j2, er in enumerate(st.session_state.get("extras_existencias_resta", [])):
                    key_r = _monto_editable_key(er["codigo"] + f"exr{j2}", "exr")
                    mv = montos_ed.get(key_r, er["monto"])
                    if mv != 0:
                        exist_bloque.append([f"  {er['codigo']}", f"  └ {er['nombre']}", fmt_monto(mv), "-", ""])
                    exist_total -= mv
                if exist_total != 0 or exist_bloque:
                    filas_egr.append(["", "Existencias, Insumos y Servicios", fmt_monto(exist_total), "+", "1409"])
                    filas_egr.extend(exist_bloque)
                exist_bloque = []
                exist_total = 0

            key   = _monto_editable_key(l.codigo + str(idx_e), "egr")
            monto = montos_ed.get(key, l.monto)
            if monto != 0:
                rem_bloque.append([f"  {l.codigo}", f"  └ {l.nombre}", fmt_monto(monto), "", ""])
            rem_total += monto
            idx_e += 1
        else:
            # Flush existencias if pending
            if exist_bloque or exist_total != 0:
                for j2, es in enumerate(st.session_state.get("extras_existencias_suma", [])):
                    key_s = _monto_editable_key(es["codigo"] + f"exs{j2}", "exs")
                    mv = montos_ed.get(key_s, es["monto"])
                    if mv != 0:
                        exist_bloque.append([f"  {es['codigo']}", f"  └ {es['nombre']}", fmt_monto(mv), "+", ""])
                    exist_total += mv
                for j2, er in enumerate(st.session_state.get("extras_existencias_resta", [])):
                    key_r = _monto_editable_key(er["codigo"] + f"exr{j2}", "exr")
                    mv = montos_ed.get(key_r, er["monto"])
                    if mv != 0:
                        exist_bloque.append([f"  {er['codigo']}", f"  └ {er['nombre']}", fmt_monto(mv), "-", ""])
                    exist_total -= mv
                if exist_total != 0 or exist_bloque:
                    filas_egr.append(["", "Existencias, Insumos y Servicios", fmt_monto(exist_total), "+", "1409"])
                    filas_egr.extend(exist_bloque)
                exist_bloque = []
                exist_total = 0

            # Flush remuneraciones if pending
            if rem_bloque or rem_total != 0:
                for j2, er in enumerate(st.session_state.get("extras_remuneraciones", [])):
                    key_r = _monto_editable_key(er["codigo"] + f"rem{j2}", "rem")
                    mv    = montos_ed.get(key_r, er["monto"])
                    if mv != 0:
                        rem_bloque.append([f"  {er['codigo']}", f"  └ {er['nombre']}", fmt_monto(mv), "", ""])
                    rem_total += mv
                if rem_total != 0 or rem_bloque:
                    filas_egr.append(["", "Remuneraciones Pagadas", fmt_monto(rem_total), "+", "1411"])
                    filas_egr.extend(rem_bloque)
                rem_bloque = []
                rem_total  = 0

            key   = _monto_editable_key(l.codigo + str(idx_e), "egr")
            monto = montos_ed.get(key, l.monto)
            if monto != 0:
                filas_egr.append([l.codigo, l.nombre, fmt_monto(monto), l.signo, l.f22])
            idx_e += 1

    # Flush remaining existencias
    if exist_bloque or exist_total != 0:
        for j2, es in enumerate(st.session_state.get("extras_existencias_suma", [])):
            key_s = _monto_editable_key(es["codigo"] + f"exs{j2}", "exs")
            mv = montos_ed.get(key_s, es["monto"])
            if mv != 0:
                exist_bloque.append([f"  {es['codigo']}", f"  └ {es['nombre']}", fmt_monto(mv), "+", ""])
            exist_total += mv
        for j2, er in enumerate(st.session_state.get("extras_existencias_resta", [])):
            key_r = _monto_editable_key(er["codigo"] + f"exr{j2}", "exr")
            mv = montos_ed.get(key_r, er["monto"])
            if mv != 0:
                exist_bloque.append([f"  {er['codigo']}", f"  └ {er['nombre']}", fmt_monto(mv), "-", ""])
            exist_total -= mv
        if exist_total != 0 or exist_bloque:
            filas_egr.append(["", "Existencias, Insumos y Servicios", fmt_monto(exist_total), "+", "1409"])
            filas_egr.extend(exist_bloque)

    # Flush remaining rem
    if rem_bloque or rem_total != 0:
        for j2, er in enumerate(st.session_state.get("extras_remuneraciones", [])):
            key_r = _monto_editable_key(er["codigo"] + f"rem{j2}", "rem")
            mv    = montos_ed.get(key_r, er["monto"])
            if mv != 0:
                rem_bloque.append([f"  {er['codigo']}", f"  └ {er['nombre']}", fmt_monto(mv), "", ""])
            rem_total += mv
        if rem_total != 0 or rem_bloque:
            filas_egr.append(["", "Remuneraciones Pagadas", fmt_monto(rem_total), "+", "1411"])
            filas_egr.extend(rem_bloque)

    story.append(_tabla_detalle(filas_egr, "TOTAL EGRESOS", resultado.total_egresos))
    story.append(Spacer(1, 0.35*cm))

    # ── III. GASTOS RECHAZADOS ───────────────────────────────────────────────
    story.append(Paragraph("III. GASTOS RECHAZADOS", h2))
    lineas_gst = construir_lineas_gastos_rechazados(cuentas, st.session_state.get("extras_gastos", []))
    filas_gst  = []
    for idx, l in enumerate(lineas_gst):
        if l.codigo in elim_gst:
            continue
        key   = _monto_editable_key(l.codigo + str(idx), "gst")
        monto = montos_ed.get(key, l.monto)
        if monto != 0:
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
