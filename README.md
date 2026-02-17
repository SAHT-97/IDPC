# 📊 Calculador RLI — Impuesto de Primera Categoría
**Régimen 14 D N°3 | Tasa 12,5%**

Aplicación Streamlit para calcular la Renta Líquida Imponible (RLI) e Impuesto de Primera Categoría a partir de un Balance de 8 Columnas en PDF.

---

## 🗂️ Estructura de archivos

```
rli_app/
├── app.py              ← Interfaz principal Streamlit
├── extractor.py        ← Extracción de datos del Balance PDF
├── regimen_14d3.py     ← Lógica tributaria Régimen 14 D N°3 (completo)
├── regimen_14a.py      ← Estructura Régimen 14 A (preparado, en desarrollo)
├── styles.css          ← Estilos visuales personalizados
├── requirements.txt
└── README.md
```

---

## 🚀 Instalación y uso

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Ejecutar la aplicación
streamlit run app.py
```

---

## 📋 Flujo de uso

1. **Subir PDF** del Balance de 8 Columnas en la barra lateral
2. **Seleccionar régimen**: 14 D N°3 (activo) o 14 A (próximamente)
3. La app extrae automáticamente las cuentas y llena los 3 bloques:
   - **I. Ingresos del Ejercicio** (cuentas 300101, 311102 + extras)
   - **II. Egresos del Ejercicio** (remuneraciones, honorarios, arriendos, etc.)
   - **III. Gastos Rechazados** (430101, 430102)
4. Cada monto es **editable** directamente en pantalla
5. Agregar o eliminar cuentas con los botones `➕` / `🗑️`
6. Elegir modo de cálculo:
   - **❌ Sin Incentivo al Ahorro**: Base = Ingresos − Egresos + GR
   - **✅ Con Incentivo al Ahorro** (Art. 14 E LIR): deduce el menor entre 50% RLI Invertida y 5.000 UF
7. **Exportar a PDF** con el mismo formato visual

---

## 🧮 Fórmulas aplicadas

### Sin incentivo al ahorro
```
Base Imponible = Ingresos − Egresos + Gastos Rechazados
IDPC = Base Imponible × 12,5%
Saldo = IDPC − PPM
```

### Con incentivo al ahorro (Art. 14 letra E LIR)
```
Sub Base = Ingresos − Egresos + Gastos Rechazados
RLI Invertida = Sub Base − Retiros − Multas − IDPC pagado
Deducción = min(50% RLI Invertida, valor $ de 5.000 UF)
IDPC = Deducción × 12,5%
Saldo = IDPC − PPM
```

---

## 📐 Códigos F22 utilizados

| Código F22 | Concepto |
|-----------|----------|
| 1600 | Ingresos del giro percibidos |
| 1588 | Reajustes |
| 1409 | Compras netas existencias |
| 1411 | Remuneraciones pagadas |
| 1412 | Honorarios |
| 1415 | Arriendos |
| 1422 | Impuestos y multas |
| 1431 | Gastos rechazados |
| 1432 | Deducción incentivo ahorro |
| 1729 | Base imponible |
| 18   | IDPC tasa 12,5% |
| 36   | PPM |
| 305  | Saldo a pagar / crédito |

---

## 🔧 Consideraciones técnicas

- **Extracción PDF**: usa `pdfplumber` con detección de columnas por posición X
- **Separador de miles**: punto (`.`) como en el estándar chileno
- **Montos**: almacenados como `int`
- **Edición en línea**: todos los montos son editables vía `number_input`
- **session_state**: mantiene estado entre rerenders
- **Exportación**: `reportlab` genera PDF fiel al formato visual

---

## 📌 Notas

- Si una cuenta no existe en el balance cargado, se muestra con ⚠️ y monto 0 (editable manualmente)
- El valor de UF y la cantidad de UF para el límite de deducción son editables en la pantalla de cálculo
- El módulo 14 A está estructurado pero pendiente de implementación completa
