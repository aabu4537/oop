import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API = os.getenv("API_BASE_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _get(path: str, params: dict | None = None) -> list | dict:
    try:
        r = requests.get(f"{API}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"API error: {exc}")
        return []


def _post(path: str, body: dict) -> dict | None:
    try:
        r = requests.post(f"{API}{path}", json=body, timeout=120)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"API error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Simulation results renderer
# ---------------------------------------------------------------------------

def _render_sim_results(result: dict) -> None:
    df = pd.DataFrame(result["results"])
    n = result["n_sims"]

    pct_cols = [c for c in df.columns if c not in ("team", "elo")]
    for c in pct_cols:
        df[c] = (df[c] * 100).round(1)

    st.markdown(f"**{n:,} simulations completed**")

    # Champion bar chart
    champ_df = df.sort_values("champion", ascending=False).head(16)
    fig_bar = px.bar(
        champ_df,
        x="team",
        y="champion",
        color="champion",
        color_continuous_scale="Blues",
        labels={"team": "", "champion": "Champion %"},
        title="Champion probability — top 16",
        text="champion",
    )
    fig_bar.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig_bar.update_layout(xaxis_tickangle=-40, coloraxis_showscale=False, height=380)
    st.plotly_chart(fig_bar, use_container_width=True)

    # Stage-reach heatmap
    stage_order = ["group_stage", "round_of_16", "quarter_final", "semi_final", "final", "champion"]
    heat_cols = [c for c in stage_order if c in df.columns]
    heat_df = df.set_index("team")[heat_cols].sort_values("champion", ascending=False)

    fig_heat = go.Figure(
        data=go.Heatmap(
            z=heat_df.values,
            x=[c.replace("_", " ").title() for c in heat_df.columns],
            y=heat_df.index.tolist(),
            colorscale="Blues",
            zmin=0,
            zmax=100,
            text=heat_df.values.round(1),
            texttemplate="%{text}%",
            hovertemplate="%{y} — %{x}: %{z:.1f}%<extra></extra>",
        )
    )
    fig_heat.update_layout(
        title="Stage-reach probabilities (%)",
        height=max(400, len(heat_df) * 22),
        yaxis={"autorange": "reversed"},
        margin={"l": 140},
    )
    st.plotly_chart(fig_heat, use_container_width=True)

    with st.expander("Full results table"):
        st.dataframe(df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Football Analytics", page_icon="⚽", layout="wide")
st.title("⚽ Football Analytics Platform")

tab_sim, tab_teams, tab_matches, tab_preds, tab_players = st.tabs(
    ["WC 2026 Simulator", "Elo Rankings", "Matches", "Predictions", "Player Metrics"]
)

# ---------------------------------------------------------------------------
# Tab 1 — WC 2026 Simulator (primary feature)
# ---------------------------------------------------------------------------

with tab_sim:
    st.subheader("World Cup 2026 — Monte Carlo Simulator")

    mode = st.radio(
        "Data source",
        ["Live (current Elo + OOP from DB)", "Custom groups"],
        horizontal=True,
    )

    if mode == "Live (current Elo + OOP from DB)":
        col_sims, col_seed, col_btn = st.columns([4, 1, 1])
        n_sims = col_sims.slider("Simulations", 1_000, 50_000, 10_000, step=1_000)
        seed = col_seed.number_input("Seed", value=42, step=1)

        if col_btn.button("Run", type="primary", use_container_width=True):
            with st.spinner(f"Running {n_sims:,} simulations with live DB data…"):
                result = _post(f"/simulate/wc2026?n_sims={n_sims}&seed={int(seed)}", {})
            if result:
                _render_sim_results(result)

    else:
        # Custom groups — load live Elo from DB as sensible defaults
        @st.cache_data(ttl=300)
        def _load_teams_df() -> pd.DataFrame:
            teams = _get("/teams")
            return pd.DataFrame(teams)[["name", "elo_rating"]].rename(
                columns={"name": "Team", "elo_rating": "Elo"}
            ) if teams else pd.DataFrame(columns=["Team", "Elo"])

        _WC2026_GROUPS = {
            "A": ["United States", "Canada", "Mexico", "Jamaica"],
            "B": ["Spain", "Croatia", "Morocco", "Japan"],
            "C": ["France", "Germany", "Portugal", "Senegal"],
            "D": ["Brazil", "Argentina", "Colombia", "Ecuador"],
            "E": ["England", "Netherlands", "Iran", "Wales"],
            "F": ["Belgium", "Switzerland", "Serbia", "Cameroon"],
            "G": ["Uruguay", "South Korea", "Ghana", "Australia"],
            "H": ["Denmark", "Tunisia", "Poland", "Saudi Arabia"],
        }

        teams_df = _load_teams_df()
        elo_map = dict(zip(teams_df["Team"], teams_df["Elo"])) if not teams_df.empty else {}

        default_rows = [
            {"Group": g, "Team": name, "Elo": int(elo_map.get(name, 1500))}
            for g, names in _WC2026_GROUPS.items()
            for name in names
        ]
        default_df = pd.DataFrame(default_rows)

        st.caption("Elo values pre-filled from DB. Edit any cell to override.")
        edited = st.data_editor(
            default_df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Elo": st.column_config.NumberColumn(min_value=1000, max_value=2500, step=1, format="%d"),
            },
            hide_index=True,
        )

        col_sims2, col_seed2, col_btn2 = st.columns([4, 1, 1])
        n_sims2 = col_sims2.slider("Simulations", 1_000, 50_000, 10_000, step=1_000, key="custom_sims")
        seed2 = col_seed2.number_input("Seed", value=42, step=1, key="custom_seed")

        if col_btn2.button("Run", type="primary", use_container_width=True, key="custom_run"):
            groups_payload: dict[str, list] = {}
            for _, row in edited.iterrows():
                g = str(row["Group"]).strip()
                if not g:
                    continue
                groups_payload.setdefault(g, [])
                groups_payload[g].append({"name": str(row["Team"]), "elo": float(row["Elo"])})

            if not groups_payload:
                st.warning("Add at least one group with teams.")
            else:
                with st.spinner(f"Running {n_sims2:,} simulations…"):
                    result = _post("/simulate", {"groups": groups_payload, "n_sims": n_sims2, "seed": int(seed2)})
                if result:
                    _render_sim_results(result)


# ---------------------------------------------------------------------------
# Tab 2 — Elo Rankings
# ---------------------------------------------------------------------------

with tab_teams:
    st.subheader("Current Elo Rankings")
    teams = _get("/teams")
    if teams:
        df = pd.DataFrame(teams)
        df["rank"] = range(1, len(df) + 1)

        top30 = df.head(30)
        fig = px.bar(
            top30,
            x="name",
            y="elo_rating",
            color="elo_rating",
            color_continuous_scale="Blues",
            labels={"name": "", "elo_rating": "Elo"},
            title="Top 30 teams by Elo rating",
            text="elo_rating",
        )
        fig.update_traces(texttemplate="%{text:.0f}", textposition="outside")
        fig.update_layout(xaxis_tickangle=-45, coloraxis_showscale=False, height=420)
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            df[["rank", "name", "fifa_code", "elo_rating"]].rename(
                columns={"rank": "#", "name": "Team", "fifa_code": "Code", "elo_rating": "Elo"}
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No teams in database yet — run the ETL pipeline first.")

# ---------------------------------------------------------------------------
# Tab 3 — Matches
# ---------------------------------------------------------------------------

with tab_matches:
    st.subheader("Match Results")
    col1, col2, col3 = st.columns([3, 2, 1])
    competition = col1.text_input("Competition", placeholder="e.g. FIFA World Cup")
    season = col2.text_input("Season", placeholder="e.g. 2022")
    limit = col3.number_input("Limit", min_value=10, max_value=1000, value=100, step=10)

    params: dict = {"limit": int(limit)}
    if competition:
        params["competition"] = competition
    if season:
        params["season"] = season

    if st.button("Search"):
        matches = _get("/matches", params)
        if matches:
            df = pd.DataFrame(matches)
            df["home"] = df["home_team_name"].fillna(df["home_team_id"].astype(str))
            df["away"] = df["away_team_name"].fillna(df["away_team_id"].astype(str))
            df["score"] = (
                df["home_score"].fillna("?").astype(str)
                + " – "
                + df["away_score"].fillna("?").astype(str)
            )
            st.dataframe(
                df[["match_date", "competition", "season", "home", "score", "away"]].rename(
                    columns={
                        "match_date": "Date",
                        "competition": "Competition",
                        "season": "Season",
                        "home": "Home",
                        "score": "Score",
                        "away": "Away",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No matches found.")

# ---------------------------------------------------------------------------
# Tab 4 — Predictions
# ---------------------------------------------------------------------------

with tab_preds:
    st.subheader("Match Predictions")
    model_version = st.selectbox("Model version", ["", "xgb_v1.0", "lr_v1.0"])

    preds = _get("/predictions", {"model_version": model_version} if model_version else {})
    if preds:
        df = pd.DataFrame(preds)
        for col, label in [
            ("home_win_prob", "Home Win %"),
            ("draw_prob", "Draw %"),
            ("away_win_prob", "Away Win %"),
        ]:
            df[label] = (df[col] * 100).round(1)

        show_cols = ["model_version", "match_id", "Home Win %", "Draw %", "Away Win %"]
        if "brier_score" in df.columns:
            show_cols += ["brier_score", "log_loss"]
        st.dataframe(df[show_cols], use_container_width=True, hide_index=True)

        if "brier_score" in df.columns and df["brier_score"].notna().any():
            fig = px.histogram(
                df.dropna(subset=["brier_score"]),
                x="brier_score",
                nbins=30,
                title="Brier score distribution (lower is better)",
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No predictions found — run src/models/predict.py first.")

# ---------------------------------------------------------------------------
# Tab 5 — Player Metrics
# ---------------------------------------------------------------------------

with tab_players:
    st.subheader("Player Metrics")
    player_id = st.text_input("Player UUID", placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    if player_id:
        metrics = _get(f"/players/{player_id}/metrics")
        if metrics:
            df = pd.DataFrame(metrics)
            st.dataframe(df, use_container_width=True, hide_index=True)

            metric_cols = ["press_intensity", "run_frequency", "space_creation_idx", "def_line_engagement"]
            available = [c for c in metric_cols if c in df.columns and df[c].notna().any()]
            if available:
                fig = px.line(
                    df.sort_values("match_id"),
                    x="match_id",
                    y=available,
                    markers=True,
                    title="Off-ball metrics across matches",
                    labels={"match_id": "Match", "value": "Score"},
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No metrics found for this player.")
