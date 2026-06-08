import os

import pandas as pd
import plotly.express as px
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
        r = requests.post(f"{API}{path}", json=body, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"API error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Default 2026 World Cup groups (illustrative Elo ratings)
# ---------------------------------------------------------------------------

_DEFAULT_GROUPS = {
    "A": [("Qatar", 1550), ("Ecuador", 1769), ("Senegal", 1746), ("Netherlands", 1990)],
    "B": [("England", 1950), ("Iran", 1706), ("USA", 1827), ("Wales", 1800)],
    "C": [("Argentina", 2142), ("Saudi Arabia", 1634), ("Mexico", 1848), ("Poland", 1826)],
    "D": [("France", 2003), ("Australia", 1726), ("Denmark", 1843), ("Tunisia", 1705)],
    "E": [("Spain", 1975), ("Costa Rica", 1650), ("Germany", 1988), ("Japan", 1725)],
    "F": [("Belgium", 1928), ("Canada", 1735), ("Morocco", 1779), ("Croatia", 1944)],
    "G": [("Brazil", 2045), ("Serbia", 1800), ("Switzerland", 1879), ("Cameroon", 1603)],
    "H": [("Portugal", 1960), ("Ghana", 1607), ("Uruguay", 1890), ("South Korea", 1732)],
}

_DEFAULT_DF = pd.DataFrame(
    [{"Group": g, "Team": name, "Elo": elo} for g, teams in _DEFAULT_GROUPS.items() for name, elo in teams]
)

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Football Analytics", page_icon="⚽", layout="wide")
st.title("⚽ Football Analytics Platform")

tab_teams, tab_matches, tab_preds, tab_sim, tab_players = st.tabs(
    ["Teams", "Matches", "Predictions", "Simulate", "Player Metrics"]
)

# ---------------------------------------------------------------------------
# Tab 1 — Teams
# ---------------------------------------------------------------------------

with tab_teams:
    st.subheader("Teams by Elo Rating")
    teams = _get("/teams")
    if teams:
        df = pd.DataFrame(teams)
        fig = px.bar(
            df.head(30),
            x="name",
            y="elo_rating",
            color="elo_rating",
            color_continuous_scale="Blues",
            labels={"name": "Team", "elo_rating": "Elo"},
            title="Top teams by Elo rating",
        )
        fig.update_layout(xaxis_tickangle=-45, coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df[["name", "fifa_code", "elo_rating"]], use_container_width=True, hide_index=True)
    else:
        st.info("No teams in database yet — run the ETL pipeline first.")

# ---------------------------------------------------------------------------
# Tab 2 — Matches
# ---------------------------------------------------------------------------

with tab_matches:
    st.subheader("Matches")
    col1, col2 = st.columns(2)
    competition = col1.text_input("Competition", placeholder="e.g. FIFA World Cup")
    season = col2.text_input("Season", placeholder="e.g. 2022")

    params: dict = {}
    if competition:
        params["competition"] = competition
    if season:
        params["season"] = season

    matches = _get("/matches", params)
    if matches:
        df = pd.DataFrame(matches)
        df["score"] = (
            df["home_score"].fillna("?").astype(str)
            + " – "
            + df["away_score"].fillna("?").astype(str)
        )
        st.dataframe(
            df[["match_date", "competition", "season", "home_team_id", "away_team_id", "score"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No matches found.")

# ---------------------------------------------------------------------------
# Tab 3 — Predictions
# ---------------------------------------------------------------------------

with tab_preds:
    st.subheader("Match Predictions")
    model_version = st.selectbox("Model version", ["", "xgb_v1.0", "lr_v1.0"])

    preds = _get("/predictions", {"model_version": model_version} if model_version else {})
    if preds:
        df = pd.DataFrame(preds)
        for col, label in [("home_win_prob", "home_win_pct"), ("draw_prob", "draw_pct"), ("away_win_prob", "away_win_pct")]:
            df[label] = (df[col] * 100).round(1)

        show_cols = ["model_version", "match_id", "home_win_pct", "draw_pct", "away_win_pct"]
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
# Tab 4 — Simulate
# ---------------------------------------------------------------------------

with tab_sim:
    st.subheader("World Cup Monte Carlo Simulator")
    st.markdown("Edit the groups below, adjust simulations, then click **Run**.")

    edited = st.data_editor(
        _DEFAULT_DF,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Elo": st.column_config.NumberColumn(min_value=1000, max_value=2500, step=1, format="%d"),
        },
        hide_index=True,
    )

    col_sims, col_seed, col_btn = st.columns([3, 1, 1])
    n_sims = col_sims.slider("Simulations", min_value=100, max_value=10_000, value=5_000, step=100)
    seed = col_seed.number_input("Seed", value=42, step=1)

    if col_btn.button("Run", type="primary", use_container_width=True):
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
            with st.spinner(f"Running {n_sims:,} simulations…"):
                result = _post("/simulate", {"groups": groups_payload, "n_sims": n_sims, "seed": int(seed)})

            if result:
                df = pd.DataFrame(result["results"])
                stage_cols = [c for c in df.columns if c != "team"]

                fig_heat = px.imshow(
                    df.set_index("team")[stage_cols],
                    color_continuous_scale="Blues",
                    zmin=0,
                    zmax=1,
                    labels={"color": "Probability"},
                    title=f"Stage-reach probabilities — {result['n_sims']:,} simulations",
                    aspect="auto",
                )
                st.plotly_chart(fig_heat, use_container_width=True)

                fig_champ = px.bar(
                    df.sort_values("champion", ascending=False),
                    x="team",
                    y="champion",
                    color="champion",
                    color_continuous_scale="Greens",
                    labels={"team": "Team", "champion": "Champion probability"},
                    title="Champion probability",
                )
                fig_champ.update_layout(xaxis_tickangle=-45, coloraxis_showscale=False)
                st.plotly_chart(fig_champ, use_container_width=True)

                st.dataframe(df, use_container_width=True, hide_index=True)

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
