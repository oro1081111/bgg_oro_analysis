#streamlit run app_game_search.py


import sqlite3
from typing import List, Optional, Tuple, Union

import pandas as pd
import streamlit as st


# st.set_page_config(
#     page_title="BGG Game Finder",
#     layout="wide",
#     page_icon="🎲",
# )


DB_PATH = "bgg.db"


# ==========================================
# Data Layer
# ==========================================
@st.cache_data
def get_filter_options(db_path: str) -> Tuple[List[str], List[str], List[str], List[str]]:
    """讀取 sidebar 篩選用的 options。

    Mechanics -> mechanics.name
    Categories -> ranks.domain (實際是 BGG 的 rank subdomain)
    Themes -> categories.name (BGG categories)
    Year -> games.year_published
    """
    conn = sqlite3.connect(db_path)

    mechanics = pd.read_sql_query(
        "SELECT DISTINCT name FROM mechanics WHERE name IS NOT NULL AND TRIM(name) != '' ORDER BY name",
        conn,
    )["name"].tolist()

    # ranks.domain 會包含 'overall'，這裡把它放第一個，其餘照字母排序
    domains_df = pd.read_sql_query(
        "SELECT DISTINCT domain FROM ranks WHERE domain IS NOT NULL AND TRIM(domain) != '' ORDER BY domain",
        conn,
    )
    domains = domains_df["domain"].tolist()
    if "overall" in domains:
        domains = ["overall"] + [d for d in domains if d != "overall"]

    themes = pd.read_sql_query(
        "SELECT DISTINCT name FROM categories WHERE name IS NOT NULL AND TRIM(name) != '' ORDER BY name",
        conn,
    )["name"].tolist()

    years_raw = pd.read_sql_query(
        """
        SELECT DISTINCT year_published AS year
        FROM games
        WHERE year_published IS NOT NULL
        ORDER BY year_published
        """,
        conn,
    )["year"].dropna().astype(int).tolist()

    # 年分選項：最新 -> 最舊；且 <=0 統一顯示成 "<0"
    pos_years = sorted([y for y in years_raw if y > 0], reverse=True)
    has_non_positive = any(y <= 0 for y in years_raw)
    years: List[str] = [str(y) for y in pos_years]
    if has_non_positive:
        years.append("<0")

    conn.close()
    return mechanics, domains, themes, years


def _make_in_clause(values: List[str]) -> Tuple[str, List[str]]:
    """回傳 ("(?,?,?)", params) 形式的 IN clause。"""
    if not values:
        return "()", []
    placeholders = ",".join(["?"] * len(values))
    return f"({placeholders})", list(values)


def _build_game_query(
    mechanics: List[str],
    rank_domain: Optional[str],
    themes: List[str],
    year: Optional[Union[int, str]],
) -> Tuple[str, List]:
    """組出查詢用的 WHERE 子句與參數（不含 SELECT/ORDER/LIMIT）。"""

    # 預設「不加任何篩選條件」：讓查詢基底永遠成立。
    # 只有在使用者真的選了 year / category(domain) / mechanics / themes 時才加入 WHERE。
    # NOTE:
    # - 不再強制 year_published 必須非空
    # - 不再強制 overall rank 必須存在（未上榜的遊戲仍會被列出，只是排序會放到後面）
    where_sql: List[str] = ["1=1"]
    params: List = []

    if year is not None:
        # 特殊年分："<0" 代表 year_published <= 0
        if isinstance(year, str) and year.strip() == "<0":
            where_sql.append("g.year_published <= 0")
        else:
            where_sql.append("g.year_published = ?")
            params.append(int(year))

    if rank_domain:
        # 必須在 ranks 有這個 domain
        where_sql.append(
            "EXISTS (SELECT 1 FROM ranks r2 WHERE r2.bgg_id = g.bgg_id AND r2.domain = ? AND r2.rank IS NOT NULL)"
        )
        params.append(rank_domain)

    if mechanics:
        in_sql, in_params = _make_in_clause(mechanics)
        where_sql.append(
            f"EXISTS (SELECT 1 FROM mechanics m WHERE m.bgg_id = g.bgg_id AND m.name IN {in_sql})"
        )
        params.extend(in_params)

    if themes:
        in_sql, in_params = _make_in_clause(themes)
        where_sql.append(
            f"EXISTS (SELECT 1 FROM categories c WHERE c.bgg_id = g.bgg_id AND c.name IN {in_sql})"
        )
        params.extend(in_params)

    return " AND ".join(where_sql), params


@st.cache_data
def query_games_page(
    db_path: str,
    mechanics: List[str],
    rank_domain: Optional[str],
    themes: List[str],
    year: Optional[Union[int, str]],
    limit: int,
    offset: int,
) -> Tuple[int, pd.DataFrame]:
    """分頁查詢遊戲（避免一次撈全表導致卡住）。

    回傳：(total_count, page_df)
    """
    where_clause, params = _build_game_query(
        mechanics=mechanics,
        rank_domain=rank_domain,
        themes=themes,
        year=year,
    )

    conn = sqlite3.connect(db_path)

    count_sql = f"""
    SELECT COUNT(*)
    FROM games g
    WHERE {where_clause}
    """
    total = int(pd.read_sql_query(count_sql, conn, params=params).iloc[0, 0])

    page_sql = f"""
    SELECT
        g.bgg_id,
        g.name AS game_name,
        g.year_published AS year,
        g.min_players,
        g.max_players,
        g.min_playtime,
        g.max_playtime,
        g.min_age,
        g.rating_avg,
        g.rating_geek,
        g.rating_count,
        g.weight_avg,
        g.weight_count,
        g.url AS game_url,
        g.image AS game_image,
        ro.rank AS overall_rank,
        rd.rank AS selected_rank,
        (
            SELECT group_concat(r3.domain || ':' || r3.rank, ' | ')
            FROM ranks r3
            WHERE r3.bgg_id = g.bgg_id
              AND r3.rank IS NOT NULL
              AND r3.domain != 'overall'
            ORDER BY r3.rank ASC
        ) AS other_ranks
    FROM games g
    LEFT JOIN (
        SELECT bgg_id, MIN(rank) AS rank
        FROM ranks
        WHERE domain = 'overall'
        GROUP BY bgg_id
    ) ro
        ON g.bgg_id = ro.bgg_id
    LEFT JOIN (
        SELECT bgg_id, MIN(rank) AS rank
        FROM ranks
        WHERE domain = ?
        GROUP BY bgg_id
    ) rd
        ON g.bgg_id = rd.bgg_id
    WHERE {where_clause}
    ORDER BY
        CASE WHEN ro.rank IS NULL THEN 1 ELSE 0 END ASC,
        ro.rank ASC,
        g.rating_geek DESC
    LIMIT ? OFFSET ?
    """

    # rd.domain 需要一個固定值（None 時就用 overall，代表不額外顯示特定 domain rank）
    selected_domain = rank_domain or "overall"
    page_df = pd.read_sql_query(
        page_sql,
        conn,
        params=[selected_domain, *params, int(limit), int(offset)],
    )
    conn.close()
    return total, page_df


@st.cache_data
def query_games_top_n(
    db_path: str,
    mechanics: List[str],
    rank_domain: Optional[str],
    themes: List[str],
    year: Optional[Union[int, str]],
    limit: int,
) -> Tuple[int, pd.DataFrame]:
    """查詢前 N 筆（for『顯示更多』模式）。

    回傳：(total_count, df_top_n)
    """
    total, df = query_games_page(
        db_path=db_path,
        mechanics=mechanics,
        rank_domain=rank_domain,
        themes=themes,
        year=year,
        limit=limit,
        offset=0,
    )
    return total, df


# ==========================================
# UI Components
# ==========================================
def render_game_card_original_style(game: pd.Series, list_rank: Optional[int] = None):
    """參考 app_mechanic_trends.py 的卡片樣式，並加上篩選順位。"""
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
    overall_rank = game.get("overall_rank")
    selected_rank = game.get("selected_rank")
    other_ranks = game.get("other_ranks")

    # 左右欄：圖片 | 資訊
    c1, c2 = st.columns([1, 3], vertical_alignment="top")

    with c1:
        if isinstance(img, str) and img.strip():
            st.image(img, width=200)
        else:
            st.write("(no image)")

    with c2:
        # 標題行（篩選順位 + overall rank）
        prefix = []
        if list_rank is not None:
            prefix.append(f"篩選順位 #{int(list_rank)}")
        if pd.notna(overall_rank):
            prefix.append(f"Overall Rank #{int(overall_rank)}")

        # 若有選擇特定 domain（Categories 篩選），顯示該 domain rank
        if pd.notna(selected_rank) and pd.notna(overall_rank) and int(selected_rank) != int(overall_rank):
            prefix.append(f"Selected Rank #{int(selected_rank)}")

        # 其他 ranks 一次列出（例如 strategic:123 | family:456 ...）
        if isinstance(other_ranks, str) and other_ranks.strip():
            prefix.append(other_ranks)
        if prefix:
            st.caption(" • ".join(prefix))

        # BGG 風格頭部：左側大分數 + 標題
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
            if pd.notna(geek):
                meta.append(f"Geek {float(geek):.2f}")
            if pd.notna(rating_count):
                meta.append(f"{int(rating_count):,} ratings")
            if pd.notna(weight_count):
                meta.append(f"{int(weight_count):,} weight")
            if meta:
                st.caption(" • ".join(meta))

        # 下方四格資訊
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


def render_sidebar(mech_opts: List[str], domain_opts: List[str], theme_opts: List[str], year_opts: List[str]):
    st.sidebar.header("🔎 遊戲排名篩選條件")

    with st.sidebar.form("search_form"):
        mechanics = st.multiselect(
            "Mechanics（機制）",
            options=mech_opts,
            default=[],
        )

        # Categories = ranks.domain
        rank_domain = st.selectbox(
            "Categories（類型）",
            options=["All"] + domain_opts,
            index=0,
        )
        rank_domain = None if rank_domain == "All" else rank_domain

        # Themes = categories.name
        themes = st.multiselect(
            "Themes（主題）",
            options=theme_opts,
            default=[],
        )

        year = st.selectbox(
            "Year（年分）",
            options=["All"] + year_opts,
            index=0,
        )
        if year == "All":
            year = None
        elif year == "<0":
            year = "<0"
        else:
            year = int(year)

        submitted = st.form_submit_button("搜尋")

    return submitted, mechanics, rank_domain, themes, year


# ==========================================
# Main
# ==========================================
def main():
    st.title("🎲 BGG 遊戲篩選排名")
    st.caption(
        "可依 Mechanics / Categories(ranks.domain) / Themes(categories) / 年份篩選，並依 overall rank 排序。"
    )

    try:
        mech_opts, domain_opts, theme_opts, year_opts = get_filter_options(DB_PATH)
    except Exception as e:
        st.error(f"讀取資料庫失敗：{e}")
        return

    submitted, mechanics, rank_domain, themes, year = render_sidebar(
        mech_opts, domain_opts, theme_opts, year_opts
    )

    # 初始化 session state
    if "search_total" not in st.session_state:
        st.session_state.search_total = None
    if "search_page_df" not in st.session_state:
        st.session_state.search_page_df = None
    if "results_show_n" not in st.session_state:
        st.session_state.results_show_n = 10
    if "_last_query_key" not in st.session_state:
        st.session_state._last_query_key = None

    query_key = (
        tuple(sorted(mechanics)),
        rank_domain,
        tuple(sorted(themes)),
        year,
    )

    # 查詢條件改變或按下搜尋：重設到第 1 頁
    if submitted:
        st.session_state.results_show_n = 10
        st.session_state._last_query_key = query_key

    # 若還沒搜尋過：預設用「空篩選」直接查詢（符合：預設沒有任何篩選條件）
    if st.session_state._last_query_key is None:
        st.session_state._last_query_key = query_key

    # 顯示更多模式：只抓前 N 筆（避免一次撈全表）
    total, page_df = query_games_top_n(
        DB_PATH,
        mechanics=mechanics,
        rank_domain=rank_domain,
        themes=themes,
        year=year,
        limit=int(st.session_state.results_show_n),
    )
    st.session_state.search_total = total
    st.session_state.search_page_df = page_df

    # 顯示結果
    df = st.session_state.search_page_df
    total = int(st.session_state.search_total or 0)
    st.subheader("📋 篩選結果")
    st.caption(f"共 {total} 款（已依 overall rank 排序）")

    if total == 0:
        st.warning("沒有符合條件的遊戲。")
        return

    shown = len(df)
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        render_game_card_original_style(row, list_rank=i)

    if shown < total:
        if st.button("顯示更多", key="show_more"):
            st.session_state.results_show_n = min(total, int(st.session_state.results_show_n) + 10)
            st.rerun()


if __name__ == "__main__":
    main()
