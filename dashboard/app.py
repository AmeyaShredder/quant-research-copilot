"""
Streamlit dashboard. Deliberately thin: every panel here is a
`pd.read_sql` against a view defined in db/views.sql (or a light query
over base tables for drill-down). No aggregation logic lives in this
file — that's the point of Part B.6's separation of concerns.

Run: streamlit run dashboard/app.py
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from db.session import engine

st.set_page_config(page_title="quant-research-copilot", layout="wide")
st.title("quant-research-copilot — observability dashboard")

tab_signal, tab_backtest, tab_eval, tab_cost, tab_docs = st.tabs(
    ["Signal", "Backtest", "Evaluation", "Cost / Latency", "Document drill-down"]
)

with tab_signal:
    st.subheader("Signal time series by ticker")
    tickers_df = pd.read_sql("SELECT DISTINCT ticker FROM signals ORDER BY ticker", engine)
    if tickers_df.empty:
        st.info("No signals yet — run the pipeline and the aggregator first.")
    else:
        ticker = st.selectbox("Ticker", tickers_df["ticker"])
        history = pd.read_sql(
            "SELECT date, aggregated_score, components FROM signals WHERE ticker = %(ticker)s ORDER BY date",
            engine, params={"ticker": ticker},
        )
        st.line_chart(history.set_index("date")["aggregated_score"])
        st.dataframe(history, use_container_width=True)

with tab_backtest:
    st.subheader("Signal vs. baseline performance")
    perf = pd.read_sql("SELECT * FROM v_signal_vs_baseline_performance", engine)
    st.dataframe(perf, use_container_width=True)

    st.subheader("Equity curve (cumulative PnL) by run")
    runs = pd.read_sql("SELECT run_id, label FROM backtest_runs ORDER BY created_at DESC", engine)
    if not runs.empty:
        run_label = st.selectbox("Backtest run", runs["label"])
        run_id = int(runs.loc[runs["label"] == run_label, "run_id"].iloc[0])
        positions = pd.read_sql(
            "SELECT date, SUM(pnl) AS daily_pnl FROM backtest_positions "
            "WHERE run_id = %(run_id)s GROUP BY date ORDER BY date",
            engine, params={"run_id": run_id},
        )
        if not positions.empty:
            positions["cumulative_pnl"] = positions["daily_pnl"].cumsum()
            st.line_chart(positions.set_index("date")["cumulative_pnl"])

with tab_eval:
    st.subheader("Extraction accuracy by source")
    acc = pd.read_sql("SELECT * FROM v_extraction_accuracy_by_source", engine)
    st.dataframe(acc, use_container_width=True)

with tab_cost:
    st.subheader("Daily LLM pipeline cost")
    cost = pd.read_sql("SELECT * FROM v_daily_pipeline_cost ORDER BY call_date", engine)
    if not cost.empty:
        st.bar_chart(cost.pivot_table(index="call_date", columns="stage", values="total_cost_usd", aggfunc="sum"))
    st.dataframe(cost, use_container_width=True)

with tab_docs:
    st.subheader("Document drill-down")
    doc_id = st.number_input("document_id", min_value=1, step=1)
    if doc_id:
        doc = pd.read_sql(
            "SELECT * FROM raw_documents WHERE document_id = %(id)s", engine, params={"id": int(doc_id)}
        )
        extractions = pd.read_sql(
            "SELECT * FROM extractions WHERE document_id = %(id)s", engine, params={"id": int(doc_id)}
        )
        st.write("Document")
        st.dataframe(doc, use_container_width=True)
        st.write("Extractions + critic reviews")
        st.dataframe(extractions, use_container_width=True)
