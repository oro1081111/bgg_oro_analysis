# streamlit run app_category_trends.py

import sqlite3
import pandas as pd
import numpy as np
import streamlit as st
import altair as alt
import os
from typing import Dict, Tuple, Optional

# ==========================================
# 1. 頁面設定與常數
# ==========================================
# st.set_page_config(
#     page_title="BGG Category Trends",
#     layout="wide",
#     page_icon="🎲"
# )

DB_PATH = "bgg.db"

# ==========================================
# 2. 資料載入 (Data Layer)
# ==========================================
@st.cache_data(show_spinner="Loading BGG category data...")
def load_data(db_path: str) -> pd.DataFrame:
    if not os.path.exists(db_path):
        return pd.DataFrame()

    conn = sqlite3.connect(db_path, timeout=10)
    try:
        query = """
        SELECT
            g.bgg_id,
            g.name AS game_name,
            g.year_published AS year,
            g.min_players, g.max_players,
            g.min_playtime, g.max_playtime,
            g.min_age,
            g.rating_avg, g.rating_geek, g.rating_count,
            g.weight_avg, g.weight_count,
            g.url AS game_url,
            g.image AS game_image,
            ro.rank AS overall_rank,
            rc.domain AS category
        FROM games g
        JOIN ranks ro
            ON g.bgg_id = ro.bgg_id
           AND ro.domain = 'overall'
        JOIN ranks rc
            ON g.bgg_id = rc.bgg_id
           AND rc.domain != 'overall'
        WHERE g.year_published IS NOT NULL
        """
        df = pd.read_sql_query(query, conn)
        return df
    finally:
        conn.close()

@st.cache_data(show_spinner=False)
def query_top_mechanics_by_category(
    db_path: str,
    category_domain: str,
    year_range: Tuple[int, int],
    rank_limit: int,
) -> pd.DataFrame:
    """
    依據 (category_domain, year_range, rank_limit) 查出該條件下
    該條件下各 mechanic 的統計資訊。

    NOTE:
    - 這裡不先 LIMIT top_n，因為 bar chart 需要依照使用者選擇的指標
      (Popularity / Quality / Impact) 來決定 Top 20。
    """
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        start_year, end_year = int(year_range[0]), int(year_range[1])
        if start_year > end_year:
            start_year, end_year = end_year, start_year

        where_sql = [
            "ro.domain = 'overall'",
            "ro.rank IS NOT NULL",
            "ro.rank <= ?",
            "rc.domain = ?",
            "rc.rank IS NOT NULL",
            "g.year_published BETWEEN ? AND ?",
        ]

        params = [int(rank_limit), str(category_domain), int(start_year), int(end_year)]

        sql = f"""
        SELECT
            m.name AS mechanic,
            COUNT(DISTINCT g.bgg_id) AS game_count
            ,AVG(g.rating_geek) AS avg_geek
        FROM games g
        JOIN ranks ro
            ON g.bgg_id = ro.bgg_id
        JOIN ranks rc
            ON g.bgg_id = rc.bgg_id
        JOIN mechanics m
            ON g.bgg_id = m.bgg_id
        WHERE {" AND ".join(where_sql)}
        GROUP BY m.name
        ORDER BY game_count DESC
        """

        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


# ==========================================
# 3. Utility Functions
# ==========================================
def render_game_card_original_style(game: pd.Series):
    """原版風格遊戲卡片"""
    img = game.get("game_image")
    name = game.get("game_name")
    url = game.get("game_url")
    year = game.get("year")
    min_p = game.get("min_players")
    max_p = game.get("max_players")
    min_t = game.get("min_playtime")
    max_t = game.get("max_playtime")
    min_age = game.get("min_age")
    rating_avg = game.get("rating_avg")
    geek = game.get("rating_geek")
    rating_count = game.get("rating_count")
    weight_avg = game.get("weight_avg")
    weight_count = game.get("weight_count")
    rank = game.get("overall_rank")

    c1, c2 = st.columns([1, 3], vertical_alignment="top")

    with c1:
        if isinstance(img, str) and img.strip():
            st.image(img, width=200)
        else:
            st.write("(no image)")

    with c2:
        top_left, top_right = st.columns([0.9, 4.1], vertical_alignment="center")
        with top_left:
            if pd.notna(rating_avg):
                st.markdown(
                    f"<div style='font-size:34px; font-weight:800; line-height:1;'>{float(rating_avg):.1f}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    "<div style='font-size:34px; font-weight:800; line-height:1;'>-</div>",
                    unsafe_allow_html=True,
                )
            st.caption("Avg Rating")

        with top_right:
            title = name
            if pd.notna(year):
                title = f"{name} ({int(year)})"
            if isinstance(url, str) and url.strip():
                st.markdown(f"### [{title}]({url})")
            else:
                st.markdown(f"### {title}")

            meta = []
            if pd.notna(rank):
                meta.append(f"Rank #{int(rank)}")
            if pd.notna(geek):
                meta.append(f"Geek {float(geek):.2f}")
            if pd.notna(rating_count):
                meta.append(f"{int(rating_count):,} ratings")
            if pd.notna(weight_count):
                meta.append(f"{int(weight_count):,} weight")
            if meta:
                st.caption(" • ".join(meta))

        card_cols = st.columns(4)
        with card_cols[0]:
            if pd.notna(min_p) and pd.notna(max_p):
                st.markdown(f"**{int(min_p)}–{int(max_p)} Players**")
            else:
                st.markdown("**Players**")
            st.caption("Player Count")
        with card_cols[1]:
            if pd.notna(min_t) and pd.notna(max_t):
                st.markdown(f"**{int(min_t)}–{int(max_t)} Min**")
            else:
                st.markdown("**Playtime**")
            st.caption("Playing Time")
        with card_cols[2]:
            if pd.notna(min_age):
                st.markdown(f"**Age: {int(min_age)}+**")
            else:
                st.markdown("**Age**")
            st.caption("Age")
        with card_cols[3]:
            if pd.notna(weight_avg):
                st.markdown(f"**Weight: {float(weight_avg):.2f} / 5**")
            else:
                st.markdown("**Weight**")
            st.caption("Complexity")

    st.divider()

# ==========================================
# 4. Sidebar
# ==========================================
def render_sidebar(raw_df: pd.DataFrame) -> Tuple[pd.DataFrame, str, int, Tuple[int, int]]:
    st.sidebar.header("🔧 分析設定")

    rank_limit = st.sidebar.slider(
        "僅統計 Board Game Rank 前 N 名",
        500, 28000, 10000, 500,
        key="cat_rank_limit",
    )

    min_y, max_y = 1995, 2025
    year_range = st.sidebar.slider(
        "選擇年份範圍",
        min_y, max_y, (2005, 2025),
        key="cat_year_range"
    )

    metric_label = st.sidebar.radio(
        "分析指標",
        ["Popularity(出版量)", "Quality(評分)", "Impact(影響力)"],
        key="cat_metric_radio"
    )

    base_filtered = raw_df[
        (raw_df["overall_rank"] <= rank_limit) &
        (raw_df["year"] >= year_range[0]) &
        (raw_df["year"] <= year_range[1])
    ]

    # 注意：這裡回傳的 df 只做 rank/year 的基礎過濾（不含 category），
    # 以便上方趨勢圖仍能比較各 category；category 將在下方主畫面選擇。
    return base_filtered, metric_label, rank_limit, year_range

# ==========================================
# 5. Chart
# ==========================================
def render_chart(grouped_df: pd.DataFrame, metric_label: str, rank_limit: int):
    if grouped_df is None or grouped_df.empty:
        st.info("請至少有資料以顯示圖表。")
        return None

    if metric_label.startswith("Popularity"):
        grouped_df["value"] = grouped_df["count"]
        y_label = "Game Count"
    elif metric_label.startswith("Quality"):
        grouped_df["value"] = grouped_df["avg_geek"]
        y_label = "Average Geek Rating"
    else:
        grouped_df["value"] = grouped_df["avg_geek"] * np.log(grouped_df["count"] + 1)
        y_label = "Impact Score"

    legend_order = grouped_df.groupby("category")["value"].sum().sort_values(ascending=False).index.tolist()
    y_min, y_max = grouped_df["value"].min(), grouped_df["value"].max()
    padding = (y_max - y_min) * 0.1 if y_max > y_min else 1

    point_select = alt.selection_point(
        fields=["year","category"], on="click", clear="dblclick", name="point_select"
    )

    chart = (
        alt.Chart(grouped_df).mark_line(point=alt.OverlayMarkDef(size=80, filled=True))
        .encode(
            x=alt.X("year:O", title="Year"),
            y=alt.Y("value:Q", title=y_label, scale=alt.Scale(domain=[y_min - padding, y_max + padding])),
            color=alt.Color("category:N", sort=legend_order, scale=alt.Scale(scheme="category20")),
            tooltip=[
                alt.Tooltip("year:O", title="Year"),
                alt.Tooltip("category:N", title="Category"),
                alt.Tooltip("value:Q", title=y_label, format=".2f"),
                alt.Tooltip("count:Q", title="Game Count"),
            ],
        )
        .properties(height=500)
        .add_params(point_select)
    )

    st.subheader(f"📈 {metric_label}（Rank ≤ {rank_limit}）")
    return st.altair_chart(chart, use_container_width=True, on_select="rerun", selection_mode="point_select")

def render_mechanic_bar_chart(
    mech_df: pd.DataFrame,
    sel_cat: str,
    year_range: Tuple[int, int],
    metric_label: str,
):
    st.subheader("🔧 Top 20 Mechanics")

    if mech_df is None or mech_df.empty:
        st.info("此條件下沒有可用的 Mechanic 資料。")
        return

    # 依照 metric_label 計算 bar chart 的值
    mech_df = mech_df.copy()

    if metric_label.startswith("Popularity"):
        mech_df["value"] = mech_df["game_count"]
        x_label = "Number of Games"
        value_tooltip_title = "Game Count"
        value_format = ".0f"
    elif metric_label.startswith("Quality"):
        mech_df["value"] = mech_df["avg_geek"]
        x_label = "Average Geek Rating"
        value_tooltip_title = "Avg Geek Rating"
        value_format = ".2f"
    else:
        mech_df["value"] = mech_df["avg_geek"] * np.log(mech_df["game_count"] + 1)
        x_label = "Impact Score"
        value_tooltip_title = "Impact"
        value_format = ".2f"

    # 防呆：若 value 全部是 NaN，直接提示
    mech_df = mech_df.dropna(subset=["value"])
    if mech_df.empty:
        st.info("此條件下沒有可用的 Mechanic 數值可繪製直條圖。")
        return

    # 依 value 取 Top 20
    mech_df = mech_df.sort_values("value", ascending=False).head(20)

    # 讓 bar chart 按 value 排序（由大到小）
    chart = (
        alt.Chart(mech_df)
        .mark_bar()
        .encode(
            x=alt.X("value:Q", title=x_label),
            y=alt.Y("mechanic:N", sort="-x", title="Mechanic"),
            tooltip=[
                alt.Tooltip("mechanic:N", title="Mechanic"),
                alt.Tooltip("value:Q", title=value_tooltip_title, format=value_format),
                alt.Tooltip("game_count:Q", title="Game Count", format=","),
                alt.Tooltip("avg_geek:Q", title="Avg Geek Rating", format=".2f"),
            ],
        )
        .properties(height=520)
    )

    start_y, end_y = int(year_range[0]), int(year_range[1])
    if start_y > end_y:
        start_y, end_y = end_y, start_y
    st.caption(f"Category = {sel_cat} | Year = {start_y}–{end_y} | Metric = {metric_label}")

    st.altair_chart(chart, use_container_width=True)



# ==========================================
# 6. Drill-down Selection
# ==========================================
def extract_selection(chart_state) -> Tuple[Optional[int], Optional[str]]:
    if not chart_state:
        return None, None
    try:
        sel = chart_state.get("selection") or chart_state.get("selections") or chart_state
        if "point_select" in sel:
            data = sel["point_select"]
            item = data[0] if isinstance(data, list) and data else data
            year = item.get("year")
            cat = item.get("category")
            try:
                year = int(year)
            except:
                pass
            return year, cat
    except:
        pass
    return None, None

# ==========================================
# 7. Main
# ==========================================
def main():
    st.title("🎲 BGG Category 遊戲類型年度趨勢分析")

    raw_df = load_data(DB_PATH)
    if raw_df.empty:
        st.warning("請確認 bgg.db 是否存在於本目錄。")
        return

    if "cat_rank_limit" not in st.session_state:
        st.session_state.cat_rank_limit = 10000
    if "cat_year_range" not in st.session_state:
        st.session_state.cat_year_range = (2005, 2025)

    filtered_df, metric_label, rank_limit, year_range = render_sidebar(raw_df)

    grouped = (
        filtered_df.groupby(["year", "category"])
        .agg(count=("bgg_id","nunique"), avg_geek=("rating_geek","mean"))
        .reset_index()
    )

    chart_state = render_chart(grouped, metric_label, rank_limit)

    st.divider()

    # ===== 下方明細：改在主畫面選擇 category（不是 sidebar） =====
    avail_cats = sorted(filtered_df["category"].dropna().unique().tolist())
    if not avail_cats:
        st.info("在目前篩選條件下沒有可用的 Category。請調整 Rank 或年份範圍。")
        return

    prev = st.session_state.get("cat_selected_category")
    if prev not in avail_cats:
        prev = avail_cats[0]

    sel_cat = st.selectbox(
        "Category",
        avail_cats,
        index=avail_cats.index(prev),
        key="cat_selected_category",
    )

    start_y, end_y = int(year_range[0]), int(year_range[1])
    if start_y > end_y:
        start_y, end_y = end_y, start_y

    st.markdown(f"### {sel_cat} — {start_y}–{end_y}")

    # ---- Top 20 Mechanics Bar Chart (限定在年份區間內) ----
    mech_df = query_top_mechanics_by_category(
        db_path=DB_PATH,
        category_domain=sel_cat,
        year_range=(start_y, end_y),
        rank_limit=rank_limit,
    )
    render_mechanic_bar_chart(mech_df, sel_cat, (start_y, end_y), metric_label)

    st.divider()

    detail_df = filtered_df[filtered_df["category"] == sel_cat]

    games_in_range = (
        detail_df
        .sort_values(["overall_rank", "rating_geek"], ascending=[True, False])
        .drop_duplicates(subset=["bgg_id"])
    )

    total_games = len(games_in_range)
    st.markdown("#### 🎮 遊戲列表")
    st.caption(f"共 {total_games} 款（已依 rank / rating 排序）")

    if "games_show_n_cat" not in st.session_state:
        st.session_state.games_show_n_cat = 10

    show_n = min(st.session_state.games_show_n_cat, total_games)

    for _, game in games_in_range.head(show_n).iterrows():
        render_game_card_original_style(game)

    if show_n < total_games:
        if st.button("顯示更多", key="show_more_games_cat"):
            st.session_state.games_show_n_cat = min(total_games, st.session_state.games_show_n_cat + 10)
            st.rerun()

if __name__ == "__main__":
    main()
