import io
from typing import List

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Cuadre de gastos SPRINT", layout="wide")

st.title("Cuadre de gastos - Prototipo inicial")
st.caption("Carga un Excel, selecciona columnas relevantes y genera un reporte rápido de gastos.")


# -----------------------------
# Helpers
# -----------------------------
def normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def convertir_importe(df: pd.DataFrame, col_importe: str) -> pd.DataFrame:
    df = df.copy()
    serie = (
        df[col_importe]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("S/", "", regex=False)
        .str.strip()
    )
    df[col_importe] = pd.to_numeric(serie, errors="coerce")
    return df


def convertir_periodo(df: pd.DataFrame, col_periodo: str) -> pd.DataFrame:
    df = df.copy()
    df[col_periodo] = pd.to_datetime(df[col_periodo], errors="coerce")
    df["periodo_mensual"] = df[col_periodo].dt.to_period("M").astype(str)
    return df


def calcular_variacion(df_resumen: pd.DataFrame, col_total: str = "gasto_total") -> pd.DataFrame:
    df_resumen = df_resumen.sort_values("periodo_mensual").copy()
    df_resumen["variacion_abs"] = df_resumen[col_total].diff()
    df_resumen["variacion_pct"] = df_resumen[col_total].pct_change() * 100
    return df_resumen


def exportar_excel(resumen: pd.DataFrame, detalle: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        resumen.to_excel(writer, index=False, sheet_name="resumen_mensual")
        detalle.to_excel(writer, index=False, sheet_name="detalle_filtrado")
    output.seek(0)
    return output.getvalue()


# -----------------------------
# UI
# -----------------------------
uploaded_file = st.file_uploader("Sube el Excel de SPRINT", type=["xlsx", "xls"])

if uploaded_file is not None:
    try:
        xls = pd.ExcelFile(uploaded_file)
        hoja = st.selectbox("Selecciona la hoja a procesar", xls.sheet_names)
        df_raw = pd.read_excel(uploaded_file, sheet_name=hoja)
        df_raw = normalizar_columnas(df_raw)

        st.subheader("Vista previa de datos")
        st.dataframe(df_raw.head(10), use_container_width=True)

        columnas = list(df_raw.columns)

        st.subheader("Mapeo de columnas")
        col1, col2, col3 = st.columns(3)
        with col1:
            col_periodo = st.selectbox("Columna de fecha/periodo", columnas)
            col_concepto = st.selectbox("Columna de concepto/código", columnas)
        with col2:
            col_importe = st.selectbox("Columna de importe", columnas)
            col_razon_social = st.selectbox("Columna de razón social", columnas)
        with col3:
            col_pagado = st.selectbox("Columna de estado o flag pagado", ["(No usar)"] + columnas)
            col_tipo = st.selectbox("Columna para distinguir gasto/no gasto", ["(No usar)"] + columnas)

        st.subheader("Filtros de negocio")
        conceptos_disponibles = sorted(df_raw[col_concepto].dropna().astype(str).unique().tolist())
        conceptos_objetivo: List[str] = st.multiselect(
            "Selecciona los conceptos/códigos a considerar",
            options=conceptos_disponibles,
            default=conceptos_disponibles[: min(5, len(conceptos_disponibles))],
        )

        razon_sociales = sorted(df_raw[col_razon_social].dropna().astype(str).unique().tolist())
        razones_objetivo = st.multiselect(
            "Selecciona la(s) razón(es) social(es)",
            options=razon_sociales,
            default=[r for r in razon_sociales if "J&V" in r.upper() or "SELVA" in r.upper()] or razon_sociales[:1],
        )

        incluir_esalud = st.checkbox("Incluir ESALUD como gasto asumido por la empresa", value=True)
        solo_pagados = st.checkbox("Considerar solo registros pagados", value=False)
        excluir_no_gasto = st.checkbox("Excluir registros identificados como 'no gasto'", value=False)

        texto_pagado = st.text_input("Valor que identifica un registro pagado", value="PAGADO")
        texto_no_gasto = st.text_input("Valor que identifica un registro como no gasto", value="NO GASTO")

        if st.button("Procesar información", type="primary"):
            df = df_raw.copy()
            df = convertir_importe(df, col_importe)
            df = convertir_periodo(df, col_periodo)

            df[col_concepto] = df[col_concepto].astype(str).str.strip()
            df[col_razon_social] = df[col_razon_social].astype(str).str.strip()

            # Filtrar conceptos/códigos requeridos
            if conceptos_objetivo:
                df = df[df[col_concepto].isin(conceptos_objetivo)]

            # Incluir ESALUD aunque no esté en la lista inicial si se requiere
            if incluir_esalud:
                mask_esalud = df_raw[col_concepto].astype(str).str.upper().str.contains("ESALUD", na=False)
                df_esalud = df_raw[mask_esalud].copy()
                if not df_esalud.empty:
                    df_esalud = convertir_importe(normalizar_columnas(df_esalud), col_importe)
                    df_esalud = convertir_periodo(df_esalud, col_periodo)
                    df_esalud[col_concepto] = df_esalud[col_concepto].astype(str).str.strip()
                    df_esalud[col_razon_social] = df_esalud[col_razon_social].astype(str).str.strip()
                    df = pd.concat([df, df_esalud], ignore_index=True).drop_duplicates()

            # Filtrar por razón social
            if razones_objetivo:
                df = df[df[col_razon_social].isin(razones_objetivo)]

            # Solo pagados
            if solo_pagados and col_pagado != "(No usar)":
                df = df[df[col_pagado].astype(str).str.upper().str.contains(texto_pagado.upper(), na=False)]

            # Excluir 'no gasto'
            if excluir_no_gasto and col_tipo != "(No usar)":
                df = df[~df[col_tipo].astype(str).str.upper().str.contains(texto_no_gasto.upper(), na=False)]

            # Limpiar importes y periodos válidos
            df = df.dropna(subset=[col_importe, "periodo_mensual"])

            resumen_mensual = (
                df.groupby("periodo_mensual", as_index=False)[col_importe]
                .sum()
                .rename(columns={col_importe: "gasto_total"})
            )
            resumen_mensual = calcular_variacion(resumen_mensual)

            st.success("Proceso completado")

            c1, c2, c3 = st.columns(3)
            c1.metric("Registros considerados", len(df))
            c2.metric("Total acumulado", f"S/ {df[col_importe].sum():,.2f}")
            c3.metric("Meses procesados", resumen_mensual['periodo_mensual'].nunique())

            st.subheader("Resumen mensual")
            st.dataframe(resumen_mensual, use_container_width=True)

            st.subheader("Detalle filtrado")
            columnas_finales = [
                col_periodo,
                "periodo_mensual",
                col_razon_social,
                col_concepto,
                col_importe,
            ]
            columnas_finales = [c for c in columnas_finales if c in df.columns]
            if col_pagado != "(No usar)" and col_pagado in df.columns:
                columnas_finales.append(col_pagado)
            if col_tipo != "(No usar)" and col_tipo in df.columns:
                columnas_finales.append(col_tipo)

            detalle_final = df[columnas_finales].sort_values(["periodo_mensual", col_concepto])
            st.dataframe(detalle_final, use_container_width=True)

            excel_bytes = exportar_excel(resumen_mensual, detalle_final)
            st.download_button(
                label="Descargar reporte en Excel",
                data=excel_bytes,
                file_name="reporte_gastos_sprint.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    except Exception as e:
        st.error(f"Ocurrió un error al procesar el archivo: {e}")
else:
    st.info("Aún no se ha cargado un archivo. Cuando lo tengas, podrás mapear columnas y probar la lógica.")


st.divider()
st.markdown(
    """
### Alcance de este prototipo
- Carga de un Excel con estructura variable.
- Selección manual de columnas clave.
- Filtro por código/concepto.
- Inclusión opcional de ESALUD.
- Consolidado por razón social.
- Resumen de gasto mensual y variaciones.
- Descarga de un reporte en Excel.

### Siguiente mejora sugerida
Cuando te entreguen la fuente real, lo ideal será reemplazar el mapeo manual por reglas fijas del archivo SPRINT y añadir validaciones de negocio más precisas.
"""
)