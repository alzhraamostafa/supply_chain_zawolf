
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import requests
import pandas as pd
import plotly.express as px
import streamlit as st


# =====================================================
# PAGE CONFIGURATION
# =====================================================
st.set_page_config(
    page_title="Smart Supply Chain Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------- CSS ----------
css_file = Path(__file__).resolve().parent / "styles.css"

if css_file.exists():
    st.markdown(
        f"<style>{css_file.read_text(encoding='utf-8')}</style>",
        unsafe_allow_html=True
    )
else:
    st.warning(f"CSS file not found: {css_file}")


# =====================================================
# API LAYER
# =====================================================
api_url = os.getenv(
    "API_URL",
    "http://127.0.0.1:8000"
).rstrip("/")


@st.cache_data(ttl=90, show_spinner=False)
def api_get(base, path, params=None):
    response = requests.get(
        f"{base}{path}",
        params=params or {},
        timeout=45
    )
    response.raise_for_status()
    return response.json()


def call(path, params=None):
    try:
        return api_get(api_url, path, params)
    except requests.RequestException as exc:
        st.error(f"API request failed for {path}: {exc}")
        st.info(
            "اتأكدي إن FastAPI شغال في Terminal منفصل "
            "وإن عنوان الـ API صحيح."
        )
        st.stop()


health = call("/api/health")

if health.get("status") != "ok":
    st.error("Database/API readiness check is degraded.")
    st.json(health.get("checks", health))
    st.stop()


# =====================================================
# HELPERS
# =====================================================
def pct(value):
    return "N/A" if value is None else f"{float(value):.1%}"


def money(value):
    return "N/A" if value is None else f"EGP {float(value):,.0f}"


def number(value):
    return "N/A" if value is None else f"{float(value):,.0f}"


def df_call(path):
    return pd.DataFrame(call(path, params))


def metric(label, value, formatter=number, help_text=None):
    st.metric(label, formatter(value), help=help_text)


def empty(df):
    if df.empty:
        st.info("No records for the selected period.")
        return True
    return False


def section(title, note=None):
    st.markdown(
        f'<div class="section-title">{title}</div>',
        unsafe_allow_html=True
    )
    if note:
        st.caption(note)


def chart(fig, height=340):
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            family="Inter, sans-serif",
            color="#dce5f5",
            size=11
        ),
        margin=dict(l=18, r=18, t=58, b=18),
        height=height,
        title=dict(
            x=0.02,
            xanchor="left",
            font=dict(size=15, color="#f5f7fb")
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        hoverlabel=dict(
            bgcolor="#111827",
            bordercolor="#f4cc35",
            font=dict(color="#fff")
        ),
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            linecolor="rgba(148,163,184,.18)"
        ),
        yaxis=dict(
            gridcolor="rgba(148,163,184,.12)",
            zeroline=False
        )
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "displayModeBar": False,
            "responsive": True
        }
    )


def metric_grid(items, columns=4):
    for i in range(0, len(items), columns):
        batch = items[i:i + columns]
        cols = st.columns(len(batch))

        for col, item in zip(cols, batch):
            label, value, formatter, help_text = item
            with col:
                metric(label, value, formatter, help_text)


# =====================================================
# SIDEBAR
# =====================================================
with st.sidebar:

    st.markdown(
        '<div class="side-brand">SC<span>•</span>INTELLIGENCE</div>',
        unsafe_allow_html=True
    )

    st.markdown("### Workspace")

    api_url = st.text_input(
        "Backend API URL",
        api_url
    ).rstrip("/")

    st.markdown(
        '<div class="side-label">ANALYSIS PERIOD</div>',
        unsafe_allow_html=True
    )

    min_d = date(2026, 1, 1)
    max_d = date(2026, 6, 30)

    start_d = st.date_input("From", value=min_d)
    end_d = st.date_input("To", value=max_d)

    if start_d > end_d:
        st.error("Start date must be on or before end date.")
        st.stop()

    params = {
        "start_date": start_d.isoformat(),
        "end_date": end_d.isoformat()
    }

    if st.button("↻ Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown(
        '<div class="side-label">NAVIGATION</div>',
        unsafe_allow_html=True
    )

    page = st.radio(
        "Workspace",
        [
            "Executive Control Tower",
            "Demand & Forecasting",
            "Production Intelligence",
            "Inventory & FEFO",
            "Procurement & Suppliers",
            "Logistics & Fleet",
            "Decision Intelligence",
            "Data Quality"
        ],
        label_visibility="collapsed"
    )

    st.divider()
    st.caption("SQLite → FastAPI → Streamlit")

    st.markdown(
        '<span class="status-pill">● HISTORICAL DATASET</span>',
        unsafe_allow_html=True
    )


# =====================================================
# HEADER
# =====================================================
st.markdown("""
<div class="hero">
  <div class="hero-topline">
    SMART SUPPLY CHAIN · ANALYTICS PLATFORM
  </div>
  <div class="hero-title">
    Supply Chain <span>Control Tower</span>
  </div>
  <div class="hero-subtitle">
    Operational visibility, performance monitoring
    & decision intelligence
  </div>
</div>
""", unsafe_allow_html=True)


# =====================================================
# SHARED DATA
# =====================================================
ov = call("/api/overview", params)

sales, prod, fleet, proc = [
    ov[k] for k in (
        "sales",
        "production",
        "fleet",
        "procurement"
    )
]

period = f"{start_d:%d %b %Y} — {end_d:%d %b %Y}"

st.markdown(
    f'<div class="period-line">'
    f'<span class="live-dot"></span> '
    f'Selected period: <b>{period}</b>'
    f'<span class="period-spacer"></span>'
    f'<span class="muted-inline">'
    f'API status: {health.get("status", "unknown")}'
    f'</span></div>',
    unsafe_allow_html=True
)


# =====================================================
# 1. EXECUTIVE CONTROL TOWER
# =====================================================
if page == "Executive Control Tower":

    section(
        "Executive performance snapshot",
        "A consolidated view of commercial, production, supplier and delivery performance."
    )

    metric_grid([
        ("Demanded units", sales.get("demanded_units"), number, None),
        ("Gross revenue", sales.get("gross_revenue_egp"), money, None),
        ("Gross profit", sales.get("gross_profit_egp"), money, None),
        ("Gross profit margin", sales.get("gross_profit_margin"), pct,
         "Total profit divided by total revenue"),
        ("Mean shift OEE", prod.get("mean_shift_oee"), pct,
         "Arithmetic mean of shift-level OEE"),
        ("Weighted scrap rate", prod.get("scrap_rate_weighted"), pct,
         "Scrap / (good units + scrap units)"),
        ("On-time delivery", fleet.get("on_time_rate"), pct,
         "Compliant on-time dispatches / all dispatches"),
        ("Avg. supplier lead time", proc.get("avg_actual_lead_time_days"),
         lambda x: "N/A" if x is None else f"{x:.1f} days", None)
    ])

    section("Performance trends")

    left, right = st.columns(2)

    monthly = df_call("/api/sales/monthly")
    production_monthly = df_call("/api/production/monthly")

    with left:
        if not empty(monthly):
            chart(px.area(
                monthly,
                x="month_period",
                y="revenue_egp",
                markers=True,
                title="Monthly revenue (EGP)"
            ))

    with right:
        if not empty(production_monthly):
            chart(px.line(
                production_monthly,
                x="month_period",
                y="mean_oee",
                markers=True,
                title="Mean shift OEE trend"
            ))

    left, right = st.columns(2)

    with left:
        if not empty(monthly):
            chart(px.bar(
                monthly,
                x="month_period",
                y="demanded_units",
                title="Demand by month"
            ))

    with right:
        logistics_monthly = df_call("/api/logistics/monthly")
        if not empty(logistics_monthly):
            chart(px.line(
                logistics_monthly,
                x="month_period",
                y="on_time_rate",
                markers=True,
                title="On-time delivery trend"
            ))

    section(
        "Priority signals",
        "Rule-based indicators to support review by the responsible business owner."
    )

    insights = call("/api/decision/insights", params)

    if not insights:
        st.success("No priority signals were returned for this period.")

    for item in insights[:4]:
        with st.container(border=True):
            st.markdown(
                f"**{item['severity']} · "
                f"{item['area']} — {item['title']}**"
            )
            st.write(item["evidence"])
            st.write(
                "**Suggested action:** "
                + item["recommended_action"]
            )


# =====================================================
# 2. DEMAND & FORECASTING
# =====================================================
elif page == "Demand & Forecasting":

    section("Demand, revenue & forecast performance")

    metric_grid([
        ("Demand", sales.get("demanded_units"), number, None),
        ("Revenue", sales.get("gross_revenue_egp"), money, None),
        ("Gross margin", sales.get("gross_profit_margin"), pct, None),
        ("Historical forecast accuracy",
         sales.get("forecast_accuracy_weighted"), pct,
         "Existing dataset field; the separate new model is not integrated.")
    ])

    monthly = df_call("/api/sales/monthly")

    if not empty(monthly):

        a, b = st.columns(2)

        with a:
            chart(px.line(
                monthly,
                x="month_period",
                y="demanded_units",
                markers=True,
                title="Monthly demanded units"
            ))

        with b:
            chart(px.area(
                monthly,
                x="month_period",
                y="revenue_egp",
                markers=True,
                title="Monthly revenue"
            ))

        chart(px.line(
            monthly,
            x="month_period",
            y="gross_margin",
            markers=True,
            title="Gross profit margin trend"
        ))

    top = pd.DataFrame(
        call(
            "/api/sales/top-products",
            {"limit": 15, **params}
        )
    )

    section("Top products by revenue")

    if not empty(top):
        st.dataframe(
            top,
            use_container_width=True,
            hide_index=True
        )


# =====================================================
# 3. PRODUCTION INTELLIGENCE
# =====================================================
elif page == "Production Intelligence":

    section("Production performance & loss analysis")

    metric_grid([
        ("Good units", prod.get("good_units"), number, None),
        ("Scrap units", prod.get("scrap_units"), number, None),
        ("Mean shift OEE", prod.get("mean_shift_oee"), pct, None),
        ("Unplanned downtime",
         prod.get("unplanned_downtime_min"),
         lambda x: "N/A" if x is None else f"{x:,.0f} min",
         None)
    ])

    monthly = df_call("/api/production/monthly")

    if not empty(monthly):

        a, b = st.columns(2)

        with a:
            chart(px.line(
                monthly,
                x="month_period",
                y="mean_oee",
                markers=True,
                title="Mean shift OEE trend"
            ))

        with b:
            chart(px.bar(
                monthly,
                x="month_period",
                y="scrap_units",
                title="Scrap units by month"
            ))

        chart(px.line(
            monthly,
            x="month_period",
            y="scrap_rate",
            markers=True,
            title="Weighted scrap rate trend"
        ))

    machines = pd.DataFrame(
        call("/api/production/machines", params)
    )

    section("Machine scorecard")

    if not empty(machines):

        for col in [
            "mean_oee",
            "mean_availability",
            "mean_performance",
            "mean_quality"
        ]:
            if col in machines.columns:
                machines[col + "_display"] = machines[col].map(pct)

        st.dataframe(
            machines,
            use_container_width=True,
            hide_index=True
        )


# =====================================================
# 4. INVENTORY & FEFO
# =====================================================
elif page == "Inventory & FEFO":

    section("Inventory expiry & replenishment risk")

    st.warning(
        "FEFO data is a historical snapshot from "
        "vw_fefo_expiry_risk; it is not live inventory. "
        "The date filter does not change this snapshot."
    )

    inv = pd.DataFrame(call("/api/inventory/fefo"))

    if not empty(inv):

        status = (
            inv["inventory_health_status"]
            .fillna("Unknown")
            .value_counts()
            .rename_axis("Health status")
            .reset_index(name="Lots")
        )

        left, right = st.columns([1, 2])

        with left:
            chart(px.pie(
                status,
                names="Health status",
                values="Lots",
                hole=.62,
                title="Inventory health mix"
            ))

        with right:
            st.metric(
                "Lots below reorder point",
                number(int((inv["reorder_gap_units"] < 0).sum()))
            )

            st.dataframe(
                inv,
                use_container_width=True,
                hide_index=True
            )


# =====================================================
# 5. PROCUREMENT & SUPPLIERS
# =====================================================
elif page == "Procurement & Suppliers":

    section("Supplier scorecard & procurement")

    metric_grid([
        ("Avg. actual lead time",
         proc.get("avg_actual_lead_time_days"),
         lambda x: "N/A" if x is None else f"{x:.1f} days",
         None),
        ("Supplier quality yield",
         proc.get("avg_supplier_quality_yield"), pct, None),
        ("Procurement savings",
         proc.get("procurement_savings_egp"), money, None)
    ], columns=3)

    suppliers = pd.DataFrame(
        call("/api/procurement/suppliers", params)
    )

    if not empty(suppliers):

        chart(px.bar(
            suppliers,
            x="supplier_name_ar",
            y="avg_actual_lead_time",
            title="Actual lead time by supplier"
        ))

        st.dataframe(
            suppliers,
            use_container_width=True,
            hide_index=True
        )

    # -------------------------------------------------
    # SUPPLIER INTELLIGENCE
    # -------------------------------------------------
    st.divider()

    section(
        "Supplier Intelligence",
        "Material-level supplier analysis and category-based supplier ranking."
    )

    st.caption(
        "Exact-SKU suppliers are based on historical RFQ records. "
        "Category-level candidates are not automatically approved "
        "or confirmed suppliers for the selected SKU."
    )

    try:

        material_options = call(
            "/api/procurement/material-options"
        )

        categories = (
            material_options.get("categories", [])
            if isinstance(material_options, dict)
            else []
        )

        if not categories:

            st.info("No material categories were returned by the API.")

        else:

            selected_category = st.selectbox(
                "Material Category",
                options=categories,
                key="supplier_intel_category"
            )

            material_rows = call(
                "/api/procurement/materials",
                {"category": selected_category}
            )

            material_df = pd.DataFrame(material_rows)

            if (
                material_df.empty
                or "material_sku_code" not in material_df.columns
            ):

                st.info(
                    "No RFQ-linked material SKUs were found for this category."
                )

            else:

                sku_values = (
                    material_df["material_sku_code"]
                    .dropna()
                    .astype(str)
                    .unique()
                    .tolist()
                )

                selected_sku = st.selectbox(
                    "Material SKU",
                    options=sku_values,
                    key="supplier_intel_sku"
                )

                selected_material = material_df[
                    material_df["material_sku_code"].astype(str)
                    == selected_sku
                ]

                if not selected_material.empty:

                    exact_count = selected_material.iloc[0].get(
                        "exact_sku_supplier_count", 0
                    )

                    rfq_count = selected_material.iloc[0].get(
                        "rfq_count", 0
                    )

                    c1, c2 = st.columns(2)

                    with c1:
                        st.metric(
                            "Recorded exact-SKU suppliers",
                            number(exact_count)
                        )

                    with c2:
                        st.metric(
                            "Historical RFQ records",
                            number(rfq_count)
                        )

                with st.spinner("Analyzing supplier performance..."):

                    recommendation = call(
                        "/api/procurement/supplier-recommendations",
                        {
                            "material_category": selected_category,
                            "material_sku_code": selected_sku,
                            **params
                        }
                    )

                def supplier_table(data, title, note=None):

                    frame = pd.DataFrame(
                        data if isinstance(data, list) else []
                    )

                    st.markdown(f"#### {title}")

                    if note:
                        st.caption(note)

                    if frame.empty:
                        st.info("No supplier records available in this group.")
                        return

                    view = frame.copy()

                    for col in view.columns:

                        col_lower = str(col).lower()

                        if any(
                            token in col_lower
                            for token in (
                                "quality",
                                "yield",
                                "stockout_rate",
                                "savings_pct"
                            )
                        ):

                            if pd.api.types.is_numeric_dtype(view[col]):

                                view[col] = view[col].map(
                                    lambda value:
                                    f"{value:.1%}"
                                    if pd.notna(value) and abs(value) <= 1
                                    else (
                                        f"{value:.1f}%"
                                        if pd.notna(value)
                                        else "N/A"
                                    )
                                )

                    st.dataframe(
                        view,
                        use_container_width=True,
                        hide_index=True
                    )

                exact_suppliers = recommendation.get(
                    "exact_sku_suppliers", []
                )

                category_candidates = recommendation.get(
                    "category_candidates", []
                )

                alternative_candidates = recommendation.get(
                    "alternative_candidates", []
                )

                supplier_table(
                    exact_suppliers,
                    "Confirmed in RFQ history for this exact SKU",
                    "These suppliers have recorded RFQ activity for the selected material SKU."
                )

                supplier_table(
                    category_candidates,
                    "Category-level supplier ranking",
                    "Candidates are ranked using category-level historical performance. "
                    "This is not proof of SKU-specific capability."
                )

                if alternative_candidates:

                    supplier_table(
                        alternative_candidates,
                        "Additional category alternatives",
                        "Treat these as candidates for qualification, "
                        "not approved suppliers for this SKU."
                    )

                weights = recommendation.get("scoring_weights")

                if weights:

                    with st.expander(
                        "Scoring methodology and weights"
                    ):

                        st.json(weights)

                        st.write(
                            recommendation.get(
                                "methodology_note",
                                "Scores summarize historical category-level "
                                "performance and should support, not replace, "
                                "procurement validation."
                            )
                        )

    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError
    ) as exc:

        st.error(
            f"Supplier Intelligence could not be loaded: {exc}"
        )

        st.caption(
            "Check that the updated FastAPI endpoints are running "
            "and returning the expected response."
        )


# =====================================================
# 6. LOGISTICS & FLEET
# =====================================================
elif page == "Logistics & Fleet":

    section("Fleet reliability & route efficiency")

    metric_grid([
        ("Dispatches", fleet.get("dispatches"), number, None),
        ("On-time rate", fleet.get("on_time_rate"), pct, None),
        ("Delayed dispatches",
         fleet.get("delayed_dispatches"), number, None),
        ("Route savings", fleet.get("route_savings_egp"), money, None)
    ])

    monthly = df_call("/api/logistics/monthly")

    if not empty(monthly):

        a, b = st.columns(2)

        with a:
            chart(px.line(
                monthly,
                x="month_period",
                y="on_time_rate",
                markers=True,
                title="On-time delivery trend"
            ))

        with b:
            chart(px.bar(
                monthly,
                x="month_period",
                y="savings_egp",
                title="Route optimization savings (EGP)"
            ))

    fleet_df = pd.DataFrame(
        call("/api/fleet/summary", params)
    )

    if not empty(fleet_df):
        st.dataframe(
            fleet_df,
            use_container_width=True,
            hide_index=True
        )

    st.info(
        "Payload utilization source contains values above 100%; "
        "it is flagged for validation rather than shown as a trusted headline KPI."
    )


# =====================================================
# 7. DECISION INTELLIGENCE
# =====================================================
elif page == "Decision Intelligence":

    section("Explainable decision-support recommendations")

    st.caption(
        "Transparent rule-based diagnostics based on observed "
        "source fields; not a trained AI model or autonomous decision-making."
    )

    insights = call(
        "/api/decision/insights",
        params
    )

    if not insights:
        st.success(
            "No priority signals for the selected period."
        )

    for item in insights:

        with st.container(border=True):

            st.markdown(
                f"### {item['severity']} · {item['area']}"
            )

            st.markdown(
                f"**{item['title']}**"
            )

            st.write(
                "**Evidence:** " + item["evidence"]
            )

            st.write(
                "**Recommended next step:** "
                + item["recommended_action"]
            )

            st.caption(
                "Basis: " + item["basis"]
            )


# =====================================================
# 8. DATA QUALITY
# =====================================================
elif page == "Data Quality":

    section("Data readiness & metric governance")

    st.json(health)

    st.markdown("#### Known validation notes")

    st.warning(
        "Fleet payload utilization has source values above 1.0 (100%). "
        "Investigate denominator/unit consistency before interpreting the average."
    )

    st.info(
        "OEE, availability, performance, quality, demand forecast accuracy, "
        "gross margin and supplier yield are stored as ratios (0–1)."
    )

    st.info(
        "On-time delivery is categorical: "
        "'Compliant On-Time' and 'Congestion Delayed'. "
        "The dashboard computes a compliant dispatch share."
    )

    st.info(
        "The FEFO view schema is matched to the supplied database. "
        "This page is snapshot-based."
    )

    st.info(
        "Forecast accuracy shown here is the historical dataset field; "
        "the separate forecasting model still needs its own integration "
        "endpoint and metadata."
    )


# =====================================================
# FOOTER
# =====================================================
st.divider()

st.markdown(
    '<div class="footer-note">'
    'SMART SUPPLY CHAIN ANALYTICS · Historical dataset view · '
    'Confirm business definitions before operational use.'
    '</div>',
    unsafe_allow_html=True
)
