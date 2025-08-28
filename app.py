# app.py
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import date
from pathlib import Path

# Prophet é opcional (se existir previsao_atendimento_2025.csv, ele usa; senão treina Prophet)
try:
    from prophet import Prophet
    HAS_PROPHET = True
except Exception:
    HAS_PROPHET = False

# =========================
# CONFIG E ESTILO
# =========================
st.set_page_config(page_title="Previsão de Atendimento", layout="wide")

st.markdown(
    """
    <style>
      .card {padding:16px;border-radius:14px;border:1px solid #e9ecef;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,0.04)}
      .kpi-title{font-size:13px;color:#6c757d;margin-bottom:6px}
      .kpi-value{font-size:36px;font-weight:800;margin:0;color:#111}
      .status-pill{display:inline-block;padding:6px 12px;border-radius:999px;font-size:14px;font-weight:700}
      .s-ok{background:#e8f5e9;color:#2e7d32}
      .s-warn{background:#fff3cd;color:#8d6e00}
      .s-alert{background:#fde2e4;color:#b00020}
      .section-title{font-size:20px;font-weight:700;margin:8px 0 4px 0}
      .section-sub{font-size:13px;color:#6c757d;margin-bottom:10px}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Previsão de Atendimento Presencial – Equatorial")
st.caption("Visual executivo com uso de todos os dados: histórico diário, feriados, satisfação, forecast e staff.")

DATA = Path("data")
CAP_POR_ATENDENTE = 36  # capacidade/dia por atendente (parâmetro simples para dimensionamento)


# =========================
# HELPERS DE LEITURA/normalização
# =========================
def read_csv_resilient(p: Path) -> pd.DataFrame | None:
    if not p.exists():
        return None
    if p.suffix.lower() not in [".csv", ".txt"]:
        return None
    seps = [",", ";", "\t", "|"]
    encs = ["utf-8", "utf-8-sig", "latin1"]
    for e in encs:
        for s in seps:
            try:
                df = pd.read_csv(p, sep=s, encoding=e, engine="python", on_bad_lines="skip")
                if not df.empty:
                    return df
            except Exception:
                continue
    try:
        return pd.read_csv(p, engine="python", on_bad_lines="skip")
    except Exception:
        return None


def normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df = df.drop(columns=[c for c in df.columns if str(c).startswith("Unnamed")], errors="ignore")
    df.columns = [str(c).strip().lower().replace("\n", " ").replace(" ", "_") for c in df.columns]
    return df


def find_col(df: pd.DataFrame, candidates) -> str | None:
    if df is None:
        return None
    cols = {c.lower().strip(): c for c in df.columns}
    for c in candidates:
        k = c.lower().strip()
        if k in cols:
            return cols[k]
    for k in cols:
        if any(k.startswith(c.lower().strip()) for c in candidates):
            return cols[k]
    return None


def month_from_name(s: pd.Series) -> pd.Series:
    mapa = {"jan": 1, "janeiro": 1, "fev": 2, "fevereiro": 2, "mar": 3, "marco": 3, "março": 3,
            "abr": 4, "abril": 4, "mai": 5, "maio": 5, "jun": 6, "junho": 6, "jul": 7, "julho": 7,
            "ago": 8, "agosto": 8, "set": 9, "setembro": 9, "out": 10, "outubro": 10,
            "nov": 11, "novembro": 11, "dez": 12, "dezembro": 12}
    s2 = (s.astype(str).str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii")
          .str.lower().str.strip())
    num = pd.to_numeric(s2, errors="coerce")
    return num.fillna(s2.map(mapa))


def ensure_date(df: pd.DataFrame) -> pd.DataFrame:
    """Cria/garante coluna 'data' a partir de data completa OU (ano,mes[,dia]) OU competência."""
    if df is None or df.empty:
        return df
    if "data" in df.columns:
        df["data"] = pd.to_datetime(df["data"], errors="coerce")
        return df
    ano = find_col(df, ["ano", "year"])
    mes = find_col(df, ["mês", "mes", "mes_nome", "mês_nome"])
    dia = find_col(df, ["dia", "day"])
    comp = find_col(df, ["competencia", "competência", "referencia", "referência"])
    if ano and mes:
        mvals = df[mes]
        mnum = month_from_name(mvals) if "nome" in mes else pd.to_numeric(mvals, errors="coerce")
        if dia:
            dnum = pd.to_numeric(df[dia], errors="coerce").fillna(1).astype(int)
        else:
            dnum = 1
        df["data"] = pd.to_datetime(
            df[ano].astype(str) + "-" + mnum.astype("Int64").astype(str) + "-" + pd.Series(dnum).astype(str),
            errors="coerce",
        )
    elif comp:
        df["data"] = pd.to_datetime(df[comp], errors="coerce")
    return df


def read_feriados() -> pd.DataFrame:
    df = read_csv_resilient(DATA / "feriados_sao_luis_MA_2025.csv")
    if df is None or df.empty:
        st.error("Arquivo de feriados não encontrado em ./data.")
        st.stop()
    df = normalize_headers(df)
    d = find_col(df, ["data", "ds"])
    n = find_col(df, ["nome", "holiday"])
    df = df.rename(columns={d: "ds", n: "holiday"})[["ds", "holiday"]]
    df["ds"] = pd.to_datetime(df["ds"], errors="coerce")
    df = df.dropna(subset=["ds"]).sort_values("ds")
    return df


def try_extract_from_xlsx_if_needed(base_df, senhas_df):
    """Se CSVs base/senhas estiverem vazios, tenta extrair do XLSX de fallback."""
    xlsx = DATA / "1.MA_Resumo_Atendimento_Presencial.xlsx"
    if (base_df is not None and not base_df.dropna(how="all").empty) and \
       (senhas_df is not None and not senhas_df.dropna(how="all").empty):
        return base_df, senhas_df
    if not xlsx.exists():
        return base_df, senhas_df
    try:
        import openpyxl
        xl = pd.ExcelFile(xlsx, engine="openpyxl")
        # heurísticas de abas
        def pick(sheet_keys):
            names = {s.lower(): s for s in xl.sheet_names}
            for k in sheet_keys:
                if k in names:
                    return names[k]
            return None
        base_sheet = pick(["base", "consolidado", "resumo", "apuração", "apuracao"]) or xl.sheet_names[0]
        senh_sheet = pick(["senhas testes", "senhas_testes", "senhas", "operacional"]) or xl.sheet_names[-1]

        if base_df is None or base_df.dropna(how="all").empty:
            base_df = pd.read_excel(xl, sheet_name=base_sheet)
            base_df = normalize_headers(base_df)
            base_df = ensure_date(base_df)
        if senhas_df is None or senhas_df.dropna(how="all").empty:
            senhas_df = pd.read_excel(xl, sheet_name=senh_sheet)
            senhas_df = normalize_headers(senhas_df)
            senhas_df = ensure_date(senhas_df)
    except Exception as e:
        st.warning(f"Falha ao extrair do XLSX: {e}")
    return base_df, senhas_df


# =========================
# CARGA DE TODOS OS DADOS (corrigido)
# =========================
@st.cache_data(show_spinner=False)
def load_all():
    feriados = read_feriados()

    # Base e Senhas
    base = read_csv_resilient(DATA / "base_MA_Resumo.csv")
    senhas = read_csv_resilient(DATA / "senhas_testes_MA_Resumo.csv")

    base = normalize_headers(base) if base is not None else None
    senhas = normalize_headers(senhas) if senhas is not None else None
    base = ensure_date(base) if base is not None else None
    senhas = ensure_date(senhas) if senhas is not None else None

    # Fallback: extrai do XLSX se CSVs estiverem vazios/ausentes
    base, senhas = try_extract_from_xlsx_if_needed(base, senhas)

    # -------- Satisfação: origens (motivos)
    origens = read_csv_resilient(DATA / "satisfacao_origens.csv")
    if origens is None:
        origens = pd.DataFrame()
    else:
        origens = normalize_headers(origens)
        if not origens.empty:
            o = find_col(origens, ["origem", "motivo"])
            c = find_col(origens, ["contagem", "qtd"])
            if o is not None and c is not None:
                origens = origens.rename(columns={o: "origem", c: "contagem"})[["origem", "contagem"]]
                origens["contagem"] = pd.to_numeric(origens["contagem"], errors="coerce").fillna(0).astype(int)
            else:
                origens = pd.DataFrame()

    # -------- Satisfação: scores (CSAT)
    score = read_csv_resilient(DATA / "satisfacao_score.csv")
    if score is None:
        score = pd.DataFrame()
    else:
        score = normalize_headers(score)
        if not score.empty:
            d = find_col(score, ["data", "ds"])
            s = find_col(score, ["score", "csat"])
            if d is not None and s is not None:
                score = score.rename(columns={d: "data", s: "score"})[["data", "score"]]
                score["data"] = pd.to_datetime(score["data"], errors="coerce")
                score["score"] = pd.to_numeric(score["score"], errors="coerce").clip(0, 100)
                score = score.dropna(subset=["data", "score"])
            else:
                score = pd.DataFrame()

    # -------- Previsão pronta (opcional)
    prev_ready = read_csv_resilient(DATA / "previsao_atendimento_2025.csv")
    if prev_ready is None:
        prev_ready = pd.DataFrame()
    else:
        prev_ready = normalize_headers(prev_ready)
        if not prev_ready.empty:
            d = find_col(prev_ready, ["data", "ds"])
            y = find_col(prev_ready, ["yhat", "demanda_prevista", "y"])
            if d is not None and y is not None:
                prev_ready = prev_ready.rename(columns={d: "ds", y: "yhat"})[["ds", "yhat"]]
                prev_ready["ds"] = pd.to_datetime(prev_ready["ds"], errors="coerce")
                prev_ready["yhat"] = pd.to_numeric(prev_ready["yhat"], errors="coerce").clip(lower=0)
                prev_ready = prev_ready.dropna(subset=["ds", "yhat"])
            else:
                prev_ready = pd.DataFrame()

    return base, senhas, feriados, origens, score, prev_ready


base, senhas, feriados, sat_origens, sat_scores, prev_ready = load_all()


# =========================
# Construção do histórico diário (usa seus dados)
# =========================
def build_daily_history(base: pd.DataFrame, senhas: pd.DataFrame) -> pd.DataFrame:
    """
    Preferência:
      1) 'senhas' com coluna 'data' -> conta atendimentos/dia (ou soma 'volume_atendido' se existir).
      2) Caso contrário, usa 'base' mensal e reparte em dias úteis (exclui fins de semana e feriados) por mês.
    """
    fer_set = set(pd.to_datetime(feriados["ds"]).dt.date.tolist())

    # 1) granular de senhas
    if senhas is not None and not senhas.empty and "data" in senhas.columns:
        ycol = find_col(senhas, ["volume_atendido", "volume", "qtd", "atendimentos"])
        if ycol:
            df = senhas.groupby(pd.to_datetime(senhas["data"]).dt.date)[ycol].sum().reset_index(name="y")
        else:
            df = senhas.groupby(pd.to_datetime(senhas["data"]).dt.date).size().reset_index(name="y")
        df.rename(columns={"data": "ds"}, inplace=True)
        df["ds"] = pd.to_datetime(df["ds"], errors="coerce")
        df = df.dropna()
        return df.sort_values("ds")

    # 2) reparte a partir de base mensal
    if base is None or base.empty:
        return pd.DataFrame()

    vcol = find_col(base, ["volume_atendido", "volume", "qtd", "atendimentos"])
    if vcol is None:
        return pd.DataFrame()

    tmp = base.copy()
    if "data" not in tmp.columns:
        tmp = ensure_date(tmp)
    if "data" not in tmp.columns:
        return pd.DataFrame()

    tmp["ano"] = tmp["data"].dt.year
    tmp["mes"] = tmp["data"].dt.month
    mensal = tmp.groupby(["ano", "mes"], as_index=False)[vcol].sum().rename(columns={vcol: "vol_mes"})

    rows = []
    for _, r in mensal.iterrows():
        ano, mes, vol = int(r["ano"]), int(r["mes"]), float(r["vol_mes"])
        # dias úteis do mês (seg–sex), excluindo feriados
        rng = pd.bdate_range(f"{ano}-{mes:02d}-01", periods=32)
        rng = rng[rng.month == mes]
        rng = [d for d in rng if d.date() not in fer_set]
        n = max(len(rng), 1)
        val = vol / n
        for d in rng:
            rows.append({"ds": pd.Timestamp(d), "y": val})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("ds")


daily_hist = build_daily_history(base, senhas)


# =========================
# Sidebar – controles
# =========================
with st.sidebar:
    st.header("Filtros")
    data_sel = st.date_input("Data de análise", value=date(2025, 12, 25))
    aplicar_feriados = st.toggle("Aplicar efeito de feriados", value=True)
    fonte_csat = st.selectbox("Fonte da satisfação (CSAT)", ["Auto", "Estimado", "CSV"])


# =========================
# Forecast: usa arquivo pronto OU treina Prophet
# =========================
def status_do_dia(ts: pd.Timestamp, fer_set: set) -> str:
    d = ts.date()
    if d in fer_set:
        return "Feriado"
    if ts.strftime("%m-%d") == "12-26":
        return "Pós-feriado"
    return "Dia útil"


def cor_por_status(status: str) -> str:
    return {"Feriado": "crimson", "Pós-feriado": "orange", "Dia útil": "steelblue"}.get(status, "steelblue")


fer_set = set(pd.to_datetime(feriados["ds"]).dt.date.tolist())


def build_forecast() -> pd.DataFrame:
    # 0) se houver previsão pronta, use-a
    if not prev_ready.empty:
        fc = prev_ready.copy().sort_values("ds")
        fc["yhat_raw"] = fc["yhat"].astype(float)
    else:
        # 1) se não tiver diário suficiente e Prophet não estiver disponível, aborta
        if (daily_hist is None or daily_hist.empty) and not HAS_PROPHET:
            st.error("Sem histórico diário suficiente e Prophet não instalado; não dá para gerar forecast.")
            st.stop()

        if not daily_hist.empty and HAS_PROPHET:
            df_p = daily_hist.rename(columns={"ds": "ds", "y": "y"}).copy()
        else:
            # fallback: histórico sintético (caso extremo)
            dias = pd.date_range("2024-01-01", "2024-12-31", freq="D")
            rng = np.random.default_rng(42)
            y = 220 + rng.integers(-20, 21, size=len(dias))
            y = y.astype(float)
            dow = dias.weekday
            y[dow == 0] *= 1.15
            y[dow == 4] *= 1.05
            df_p = pd.DataFrame({"ds": dias, "y": y})

        # Prophet
        fer = feriados[["ds", "holiday"]].copy()
        fer["lower_window"] = 0
        fer["upper_window"] = 1
        m = Prophet(holidays=fer, daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=True)
        m.fit(df_p)
        future = m.make_future_dataframe(periods=365, freq="D")
        fc = m.predict(future)[["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()
        fc["yhat_raw"] = fc["yhat"].astype(float)

    # Aplicar (ou não) o efeito de feriados
    if aplicar_feriados:
        fc["yhat"] = fc["yhat_raw"]
        mask_fer = fc["ds"].dt.date.isin(fer_set)
        fc.loc[mask_fer, "yhat"] = fc.loc[mask_fer, "yhat_raw"] * 0.25
        mask_26 = fc["ds"] == pd.to_datetime("2025-12-26")
        fc.loc[mask_26, "yhat"] = fc.loc[mask_26, "yhat_raw"] * 2.0
    else:
        fc["yhat"] = fc["yhat_raw"]

    fc["yhat"] = fc["yhat"].clip(lower=0)
    fc["atendentes"] = np.ceil(fc["yhat"] / CAP_POR_ATENDENTE).astype(int)
    return fc


fc = build_forecast()


# =========================
# CSAT
# =========================
def csat_estimado_por_status(status_ref: str) -> int:
    return 72 if status_ref == "Feriado" else (78 if status_ref == "Pós-feriado" else 82)


def load_csat(mode: str, status_ref: str, ref_date=None) -> int:
    """
    Auto: usa CSV se existir; senão estimado por status.
    Estimado: sempre estimado por status.
    CSV (se existir): tenta CSV e, se não houver, volta ao estimado (com aviso).
    Quando CSV existe, pega o score do dia mais próximo da data selecionada.
    """
    p = DATA / "satisfacao_score.csv"
    if mode == "Estimado":
        return csat_estimado_por_status(status_ref)

    if mode in ("Auto", "CSV (se existir)") and p.exists():
        df = pd.read_csv(p)
        df.columns = [c.lower().strip() for c in df.columns]
        d = "data" if "data" in df.columns else list(df.columns)[0]
        s = "score" if "score" in df.columns else list(df.columns)[1]
        df = df.rename(columns={d: "data", s: "score"})
        df["data"] = pd.to_datetime(df["data"], errors="coerce")
        df["score"] = pd.to_numeric(df["score"], errors="coerce").clip(0, 100)
        df = df.dropna(subset=["data", "score"])
        if not df.empty and ref_date is not None:
            idx = (df["data"] - pd.to_datetime(ref_date)).abs().idxmin()
            return int(round(df.loc[idx, "score"]))
        elif not df.empty:
            return int(round(df["score"].mean()))
        if mode == "CSV (se existir)":
            st.warning("CSV de CSAT não possui dados válidos; usando estimado por status.")
    if mode == "CSV (se existir)":
        st.warning("CSV de CSAT não encontrado; usando estimado por status.")
    return csat_estimado_por_status(status_ref)


# =========================
# KPIs do dia
# =========================
st.markdown('<div class="section-title">Dia selecionado</div>', unsafe_allow_html=True)
st.markdown('<div class="section-sub">Valores finais — após efeito de calendário (conforme seletor).</div>', unsafe_allow_html=True)

data_sel_ts = pd.to_datetime(data_sel)
linha = fc.loc[fc["ds"] == data_sel_ts]
if linha.empty:
    idx = (fc["ds"] - data_sel_ts).abs().idxmin()
    linha = fc.loc[[idx]]

demanda = int(round(linha["yhat"].iloc[0]))
equipe = int(linha["atendentes"].iloc[0])
status = status_do_dia(linha["ds"].iloc[0], fer_set)
cap_total = max(equipe * CAP_POR_ATENDENTE, 1)
ocupacao = round(100 * demanda / cap_total, 1)

c1, c2, c3, c4 = st.columns([1, 1, 1, 1.2])
with c1:
    st.markdown(f"""
    <div class="card">
      <div class="kpi-title">Demanda prevista</div>
      <div class="kpi-value">{demanda}</div>
      <div class="kpi-title">Data: {linha['ds'].dt.date.iloc[0]}</div>
    </div>
    """, unsafe_allow_html=True)
with c2:
    st.markdown(f"""
    <div class="card">
      <div class="kpi-title">Atendentes necessários</div>
      <div class="kpi-value">{equipe}</div>
      <div class="kpi-title">Cap. por atendente (interna): {CAP_POR_ATENDENTE}/dia</div>
    </div>
    """, unsafe_allow_html=True)
with c3:
    css = "s-alert" if status == "Feriado" else ("s-warn" if status == "Pós-feriado" else "s-ok")
    st.markdown(f"""
    <div class="card" style="text-align:center;">
      <div class="kpi-title">Status do dia</div>
      <div><span class="status-pill {css}">{status}</span></div>
      <div class="kpi-title" style="margin-top:6px;">Efeito de feriados: {"Ligado" if aplicar_feriados else "Desligado"}</div>
    </div>
    """, unsafe_allow_html=True)
with c4:
    gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=ocupacao,
        number={"suffix": "%"},
        title={"text": "Ocupação da equipe"},
        gauge={
            "axis": {"range": [0, 120]},
            "bar": {"color": "steelblue"},
            "steps": [
                {"range": [0, 85], "color": "#e8f5e9"},
                {"range": [85, 100], "color": "#fff3cd"},
                {"range": [100, 120], "color": "#fde2e4"},
            ],
            "threshold": {"line": {"color": "red", "width": 3}, "thickness": 0.75, "value": 100}
        }
    ))
    gauge.update_layout(template="plotly_white", height=220, margin=dict(t=40, b=10, l=20, r=20))
    st.plotly_chart(gauge, use_container_width=True)

st.divider()

# =========================
# Composição da previsão (Waterfall executivo)
# =========================
st.markdown('<div class="section-title">Composição da previsão</div>', unsafe_allow_html=True)
st.markdown('<div class="section-sub">Base estatística + efeito de calendário (feriados) = previsão final.</div>', unsafe_allow_html=True)

r = fc.loc[fc["ds"] == linha["ds"].iloc[0]].iloc[0]
base_val = float(r["yhat_raw"])
efeito_cal = float(r["yhat"] - r["yhat_raw"])
final_val = float(r["yhat"])

fig_wf = go.Figure(go.Waterfall(
    orientation="v",
    measure=["absolute", "relative", "total"],
    x=["Base estatística", "Efeito calendário (feriados)", "Previsão final"],
    y=[base_val, efeito_cal, final_val],
    text=[f"{base_val:.0f}", f"{efeito_cal:+.0f}", f"{final_val:.0f}"],
    textposition="outside",
    connector={"line": {"color": "#bbb"}}
))
fig_wf.update_layout(template="plotly_white", yaxis_title="Clientes", hovermode="x unified")
st.plotly_chart(fig_wf, use_container_width=True)

st.divider()

# =========================
# Satisfação (CSAT + Motivos)
# =========================
st.markdown('<div class="section-title">Satisfação do cliente</div>', unsafe_allow_html=True)
st.markdown('<div class="section-sub">CSAT do dia e principais motivos de procura.</div>', unsafe_allow_html=True)

csat = load_csat(mode=fonte_csat, status_ref=status, ref_date=data_sel)
fig_donut = go.Figure(data=[go.Pie(
    labels=["Satisfeitos", "Outros"], values=[csat, 100 - csat],
    hole=.6, marker=dict(colors=["#2e7d32", "#e0e0e0"])
)])
fig_donut.update_layout(
    title=f"CSAT ({fonte_csat})",
    showlegend=False, annotations=[dict(text=f"{csat}%", font_size=22, showarrow=False)],
    template="plotly_white"
)

colS1, colS2 = st.columns([1, 1])
colS1.plotly_chart(fig_donut, use_container_width=True)

if not sat_origens.empty:
    fig_origens = px.bar(
        sat_origens.sort_values("contagem"),
        x="contagem", y="origem", orientation="h",
        text="contagem", labels={"contagem": "Volume", "origem": "Motivo"},
        title="Motivos de procura"
    )
    fig_origens.update_traces(textposition="outside")
    fig_origens.update_layout(template="plotly_white", xaxis_title="Volume", yaxis_title="")
    colS2.plotly_chart(fig_origens, use_container_width=True)
else:
    colS2.info("Coloque 'satisfacao_origens.csv' em ./data para ver os motivos de procura.")

st.divider()

# =========================
# Próximos 30 dias — Demanda (barras) + Equipe (linha)
# =========================
st.markdown('<div class="section-title">Próximos 30 dias</div>', unsafe_allow_html=True)
st.markdown('<div class="section-sub">Demanda diária (barras por status) e equipe necessária (linha).</div>', unsafe_allow_html=True)

hoje_lim = pd.Timestamp(daily_hist["ds"].max()) if not daily_hist.empty else pd.Timestamp.today().normalize()
prox = fc[fc["ds"] > hoje_lim].copy()
prox30 = prox.head(30)

if prox30.empty:
    st.info("A janela de previsão está curta ou não há dias posteriores ao histórico.")
else:
    prox30["status"] = prox30["ds"].apply(lambda x: status_do_dia(x, fer_set))
    prox30["cor"] = prox30["status"].map(cor_por_status)

    fig_30 = go.Figure()
    fig_30.add_trace(go.Bar(
        x=prox30["ds"], y=prox30["yhat"],
        marker_color=prox30["cor"],
        name="Demanda prevista (barras)",
        hovertemplate="%{x|%d/%m}: %{y:.0f} clientes<extra></extra>"
    ))
    fig_30.add_trace(go.Scatter(
        x=prox30["ds"], y=prox30["atendentes"],
        name="Atendentes necessários (linha)",
        mode="lines+markers", line=dict(color="black"), marker=dict(size=7),
        hovertemplate="%{x|%d/%m}: %{y} atendentes<extra></extra>"
    ))
    fig_30.update_layout(
        template="plotly_white", xaxis_title="Data", yaxis_title="Clientes / Atendentes",
        legend_title_text="Série", hovermode="x unified"
    )
    st.plotly_chart(fig_30, use_container_width=True)

st.divider()

# =========================
# Visão anual — Barras mensais + MM7
# =========================
st.markdown('<div class="section-title">Visão anual</div>', unsafe_allow_html=True)
st.markdown('<div class="section-sub">Totais por mês (barras) e tendência de 7 dias (linha).</div>', unsafe_allow_html=True)

annual = fc.copy()
annual["mm7"] = annual["yhat"].rolling(7, min_periods=1).mean()

mensal = annual.groupby(annual["ds"].dt.to_period("M")).agg(
    demanda=("yhat", "sum"),
    equipe=("atendentes", "sum")
).reset_index()
mensal["mes"] = mensal["ds"].dt.to_timestamp()

fig_year = go.Figure()
fig_year.add_trace(go.Bar(
    x=mensal["mes"], y=mensal["demanda"],
    name="Demanda mensal", marker_color="steelblue",
    hovertemplate="%{x|%b/%Y}: %{y:.0f} clientes<extra></extra>"
))
fig_year.add_trace(go.Scatter(
    x=annual["ds"], y=annual["mm7"], mode="lines",
    name="Média móvel 7 dias", line=dict(color="navy", width=2),
    hovertemplate="%{x|%d/%m/%Y}: %{y:.0f}<extra></extra>"
))
fig_year.update_layout(template="plotly_white", xaxis_title="Data", yaxis_title="Volume", hovermode="x unified")
st.plotly_chart(fig_year, use_container_width=True)

st.divider()

# =========================
# Exploratório operacional (a partir de SENHAS)
# =========================
st.markdown('<div class="section-title">Exploratório operacional (a partir de senhas)</div>', unsafe_allow_html=True)
st.markdown('<div class="section-sub">Top unidades, atendentes e serviços medidos nos dados históricos.</div>', unsafe_allow_html=True)

if senhas is not None and not senhas.empty:
    if "data" in senhas.columns:
        senhas["data"] = pd.to_datetime(senhas["data"], errors="coerce")

    # Unidades
    if "unidade" in senhas.columns:
        df_u = senhas.groupby("unidade").size().reset_index(name="atendimentos")
        df_u = df_u.sort_values("atendimentos", ascending=False).head(15)
        fig_u = px.bar(df_u, x="unidade", y="atendimentos", title="Top unidades (histórico)")
        fig_u.update_layout(template="plotly_white", xaxis_title="", yaxis_title="Atendimentos")
        st.plotly_chart(fig_u, use_container_width=True)

    # Atendentes
    if "nome" in senhas.columns:
        df_a = senhas.groupby("nome").size().reset_index(name="atendimentos")
        df_a = df_a.sort_values("atendimentos", ascending=False).head(15)
        fig_a = px.bar(df_a, x="nome", y="atendimentos", title="Top atendentes (histórico)")
        fig_a.update_layout(template="plotly_white", xaxis_title="", yaxis_title="Atendimentos")
        st.plotly_chart(fig_a, use_container_width=True)

    # Serviços
    if "servicos" in senhas.columns:
        df_s = senhas.groupby("servicos").size().reset_index(name="atendimentos")
        df_s = df_s.sort_values("atendimentos", ascending=False).head(20)
        fig_s = px.bar(df_s, x="servicos", y="atendimentos", title="Top serviços (histórico)")
        fig_s.update_layout(template="plotly_white", xaxis_title="", yaxis_title="Atendimentos")
        st.plotly_chart(fig_s, use_container_width=True)
else:
    st.info("Para ver o exploratório operacional, garanta que 'senhas_testes_MA_Resumo.csv' esteja populado.")
