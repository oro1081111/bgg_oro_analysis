#streamlit run app_mechanic_trends.py

import sqlite3
import pandas as pd
import numpy as np
import streamlit as st
import altair as alt
import json
import os
from typing import Dict, Tuple, Optional

# ==========================================
# 1. 頁面設定與常數 (Configuration)
# ==========================================
# st.set_page_config(
#     page_title="BGG Mechanic Trends",
#     layout="wide",
#     page_icon="🎲"
# )

DB_PATH = "bgg.db"

# ==========================================
# 2. 資料讀取層 (Data Layer)
# ==========================================
@st.cache_data(show_spinner="Loading BGG data...")
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
            m.name AS mechanic,
            r.rank AS overall_rank
        FROM games g
        JOIN mechanics m ON g.bgg_id = m.bgg_id
        JOIN ranks r ON g.bgg_id = r.bgg_id
        WHERE
            g.year_published IS NOT NULL
            AND r.domain = 'overall'
        """
        df = pd.read_sql_query(query, conn)
        return df
    finally:
        conn.close()




@st.cache_data(show_spinner=False)
def load_mechanic_descriptions_from_db(db_path: str) -> Dict[str, Dict[str, str]]:
    """從 SQLite 讀取 mechanic 描述（取代 JSON 檔）。"""
    if not os.path.exists(db_path):
        return {}

    conn = sqlite3.connect(db_path, timeout=10)
    try:
        df = pd.read_sql_query(
            """
            SELECT mechanic, description, url
            FROM mechanic_descriptions
            """,
            conn,
        )
    finally:
        conn.close()

    # 回傳格式保持與你原本 desc_map 類似，讓下游不用大改
    out: Dict[str, Dict[str, str]] = {}
    for _, r in df.iterrows():
        mech = r["mechanic"]
        if not mech:
            continue
        out[str(mech)] = {
            "description": (r["description"] or "").strip(),
            "url": (r["url"] or "").strip(),
        }
    return out


# ==========================================
# 3. 邏輯處理層 (Logic Layer)
# ==========================================
@st.cache_data
def compute_impact(filtered_df: pd.DataFrame) -> pd.DataFrame:
    """計算每個機制的 Impact 分數並排序（全頁唯一允許的 Impact 計算入口）"""
    impact_scores = filtered_df.groupby("mechanic").agg(
        count=("bgg_id", "nunique"),
        avg_geek=("rating_geek", "mean"),
    )
    # Impact 定義：avg_geek * ln(count + 1)
    impact_scores["impact"] = impact_scores["avg_geek"] * np.log(impact_scores["count"] + 1)
    return impact_scores

# NOTE:
# - 為避免在此檔案內出現任何可被誤用的 Impact 計算函式，僅保留 compute_impact(filtered_df) 作為唯一入口。

def manage_mechanic_state(all_mechanics_sorted, all_mechanics_by_impact):
    """處理側邊欄機制的 Session State 邏輯"""
    
    # 初始化 Session State
    if "use_impact_top_n" not in st.session_state:
        # 預設勾選：一進來就使用 Impact 前 N 名機制
        st.session_state.use_impact_top_n = True
    if "impact_top_n" not in st.session_state:
        st.session_state.impact_top_n = 10
    if "selected_mechanics" not in st.session_state:
        # 預設前 10 個
        st.session_state.selected_mechanics = all_mechanics_sorted[:10]

    # Callback: 新增機制
    def _add_mechanic():
        mech = st.session_state.get("mechanic_to_add", "")
        if mech:
            selected = set(st.session_state.get("selected_mechanics", []))
            selected.add(mech)
            st.session_state.selected_mechanics = sorted(selected)
            st.session_state.use_impact_top_n = False
            # 不重置選擇器：使用者希望保留目前選擇（但下拉選單仍可再選其他項）

    # Callback: 移除機制
    def _remove_mechanic(mech_name):
        current = st.session_state.get("selected_mechanics", [])
        st.session_state.selected_mechanics = sorted([m for m in current if m != mech_name])
        st.session_state.use_impact_top_n = False

    return _add_mechanic, _remove_mechanic

# ==========================================
# 4. UI 元件層 (UI Components)
# ==========================================
def render_sidebar(df: pd.DataFrame, impact_df: pd.DataFrame) -> Tuple[pd.DataFrame, str, int]:
    """渲染側邊欄並回傳篩選後的資料與設定"""
    st.sidebar.header("🔧 分析設定")

    # 1. 排名限制
    rank_limit = st.sidebar.slider(
        "僅統計 Board Game Rank 前 N 名",
        500,
        28000,
        10000,
        500,
        key="rank_limit",
    )
    
    # 2. 年份範圍
    min_y, max_y = int(df["year"].min()), int(df["year"].max())
    year_range = st.sidebar.slider(
        "選擇年份範圍",
        1995,
        2025,
        (2005, 2025),
        key="year_range",
    )

    filtered_df = df[
        (df["overall_rank"] <= rank_limit) &
        (df["year"] >= year_range[0]) &
        (df["year"] <= year_range[1])
    ]

    # 3. 分析指標 (完全保留原本的文字與清單模式)
    st.sidebar.subheader("選擇分析指標")
    metric_help_map = {
        "Popularity(出版量)": "count",
        "Quality(評分)": "avg_geek",
        "Impact(影響力)": "impact",
    }
    
    # 這裡保留原本的 label_visibility="collapsed" 以及選項文字
    metric_label = st.sidebar.radio(
        "", 
        options=list(metric_help_map.keys()), 
        label_visibility="collapsed",
        key="metric_radio" 
    )
    
    # 4. 機制顯示設定
    st.sidebar.subheader("🎯 機制顯示設定")

    # impact_df 由 main() 預先計算並傳入（render_sidebar 內禁止 groupby）
    all_sorted_by_count = impact_df.sort_values("count", ascending=False).index.tolist()
    all_sorted_by_impact = impact_df.sort_values("impact", ascending=False).index.tolist()

    add_cb, remove_cb = manage_mechanic_state(all_sorted_by_count, all_sorted_by_impact)

    # Checkbox & Slider
    st.sidebar.checkbox("使用 Impact 前 N 名機制", key="use_impact_top_n")
    top_n = st.sidebar.slider("顯示 Impact 前 N 名", 1, 50, st.session_state.impact_top_n)
    st.session_state.impact_top_n = top_n

    if st.session_state.use_impact_top_n:
        st.session_state.selected_mechanics = all_sorted_by_impact[:top_n]
    
    # 防呆：確保不選到空值或不存在的機制
    valid_mechanics = set(all_sorted_by_count)
    st.session_state.selected_mechanics = [m for m in st.session_state.selected_mechanics if m in valid_mechanics]

    # 搜尋加入
    selected_set = set(st.session_state.selected_mechanics)
    remaining = [m for m in sorted(all_sorted_by_count) if m not in selected_set]
    
    with st.sidebar.expander("🔍 搜尋並加入", expanded=True):
        # 選擇後直接加入（不需要額外的「加入」按鈕）
        # 注意：加入後該 mechanic 會從 remaining 消失，因此要把目前選到的值也保留在 options 裡，避免 value 不在 options。
        current_pick = st.session_state.get("mechanic_to_add", "")
        options = [""] + remaining
        if current_pick and current_pick not in options:
            options = [""] + [current_pick] + remaining

        st.selectbox(
            "搜尋機制",
            options,
            key="mechanic_to_add",
            label_visibility="collapsed",
            on_change=add_cb,
        )

    # 目前列表
    st.sidebar.markdown("**目前顯示的機制（字母排序）**")
    for mech in sorted(st.session_state.selected_mechanics):
        c1, c2 = st.sidebar.columns([0.82, 0.18])
        c1.write(mech)
        c2.button("X", key=f"remove_{mech}", on_click=remove_cb, args=(mech,))

    return filtered_df, metric_label, rank_limit

def render_chart(grouped_df: pd.DataFrame, metric_label: str, rank_limit: int):
    """繪製 Altair 折線圖"""
    # 防呆：若沒有任何資料，避免產生 domain=[NaN, NaN] 造成前端 JSON.parse 爆炸
    if grouped_df is None or grouped_df.empty:
        st.info("請至少選擇一個機制（Mechanic）以顯示圖表。")
        return None

    # 根據原本邏輯決定 Y 軸與欄位
    if metric_label.startswith("Popularity"):
        grouped_df["value"] = grouped_df["count"]
        y_label = "Game Count"
    elif metric_label.startswith("Quality"):
        grouped_df["value"] = grouped_df["avg_geek"]
        y_label = "Average Geek Rating"
    else:
        grouped_df["value"] = grouped_df["avg_geek"] * np.log(grouped_df["count"] + 1)
        y_label = "Impact Score"

    # 圖例排序 (總分高->低)
    legend_order = grouped_df.groupby("mechanic")["value"].sum().sort_values(ascending=False).index.tolist()
    
    # Y 軸範圍
    y_min, y_max = grouped_df["value"].min(), grouped_df["value"].max()
    # min/max 可能是 NaN（例如全部空值），避免產生 domain=[NaN, NaN]
    if pd.isna(y_min) or pd.isna(y_max):
        st.info("目前資料不足以繪製圖表（可能沒有可用的數值）。")
        return None
    padding = (y_max - y_min) * 0.1 if y_max > y_min else 1

    # Altair Chart
    point_select = alt.selection_point(fields=["year", "mechanic"], on="click", clear="dblclick", name="point_select")
    
    chart = (
        alt.Chart(grouped_df).mark_line(point=alt.OverlayMarkDef(size=80, filled=True))
        .encode(
            x=alt.X("year:O", title="Year"),
            y=alt.Y("value:Q", title=y_label, scale=alt.Scale(domain=[y_min - padding, y_max + padding])),
            color=alt.Color("mechanic:N", sort=legend_order, scale=alt.Scale(scheme="category20")),
            tooltip=[
                alt.Tooltip("year:O", title="Year"),
                alt.Tooltip("mechanic:N", title="Mechanic"),
                alt.Tooltip("value:Q", title=y_label, format=".2f"),
                alt.Tooltip("count:Q", title="Game Count")
            ],
        )
        .properties(height=500)
        .add_params(point_select)
    )

    st.subheader(f"📈 {metric_label}（Rank ≤ {rank_limit}）")
    return st.altair_chart(chart, use_container_width=True, on_select="rerun", selection_mode="point_select")

def render_game_card_original_style(game: pd.Series):
    """依照原版視覺風格渲染遊戲卡片（字體大小、排版還原）"""
    
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

    # 左右欄：圖片 | 資訊
    c1, c2 = st.columns([1, 3], vertical_alignment="top")
    
    with c1:
        if isinstance(img, str) and img.strip():
            st.image(img, width=200)
        else:
            st.write("(no image)")
    
    with c2:
        # BGG 風格頭部：左側大分數 + 標題
        # 使用原本的比例 [0.9, 4.1]
        top_left, top_right = st.columns([0.9, 4.1], vertical_alignment="center")
        
        with top_left:
            if pd.notna(rating_avg):
                # ★★★ 還原重點：使用原本的 div style font-size:34px ★★★
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
            if pd.notna(rank): meta.append(f"Rank #{int(rank)}")
            if pd.notna(geek): meta.append(f"Geek {float(geek):.2f}")
            if pd.notna(rating_count): meta.append(f"{int(rating_count):,} ratings")
            if pd.notna(weight_count): meta.append(f"{int(weight_count):,} weight")
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

def extract_selection(chart_state) -> Tuple[Optional[int], Optional[str]]:
    """解析 Streamlit Altair 的選擇狀態"""
    if not chart_state: return None, None
    try:
        # 處理不同版本的 selection 結構
        sel = chart_state.get("selection") or chart_state.get("selections") or chart_state
        if "point_select" in sel:
            data = sel["point_select"]
            # 可能是 list 或是 dict
            item = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else None)
            if item:
                # 這裡要小心 year 可能是字串或整數，嘗試轉型
                y = item.get("year")
                m = item.get("mechanic")
                try:
                    y = int(y)
                except:
                    pass
                return y, m
    except:
        pass
    return None, None

# ==========================================
# 5. 主程式流程 (Main Execution)
# ==========================================
def main():
    st.title("🎲 BGG Mechanic 遊戲機制年度趨勢分析")

    # 1. 載入資料
    raw_df = load_data(DB_PATH)
    if raw_df.empty:
        st.warning("請確認 bgg.db 檔案是否存在。")
        return

    desc_map = load_mechanic_descriptions_from_db(DB_PATH)

    # 2. 先用目前 filter 狀態計算 impact_df（全頁只計算一次），再交給 sidebar/main/drill-down 共用
    #    這裡的預設值需與 sidebar widget 預設一致，避免首次進入時行為差異。
    if "rank_limit" not in st.session_state:
        st.session_state.rank_limit = 10000
    if "year_range" not in st.session_state:
        st.session_state.year_range = (2005, 2025)

    filtered_df_for_impact = raw_df[
        (raw_df["overall_rank"] <= st.session_state.rank_limit)
        & (raw_df["year"] >= st.session_state.year_range[0])
        & (raw_df["year"] <= st.session_state.year_range[1])
    ]
    impact_df = compute_impact(filtered_df_for_impact)

    # 3. 側邊欄與篩選 (包含最上排的選擇模式清單)
    filtered_df, metric_label, rank_limit = render_sidebar(raw_df, impact_df)
    
    if filtered_df.empty:
        st.info("目前的篩選條件下沒有資料。")
        return

    # 3. 資料聚合 (Aggregation) for Chart
    selected_mechanics = st.session_state.selected_mechanics
    if not selected_mechanics:
        st.warning("目前沒有選擇任何機制，請在左側至少選擇 1 個機制。")
        return

    chart_data = filtered_df[filtered_df["mechanic"].isin(selected_mechanics)]
    
    grouped = chart_data.groupby(["year", "mechanic"]).agg(
        count=("bgg_id", "nunique"),
        avg_geek=("rating_geek", "mean")
    ).reset_index()

    if grouped.empty:
        st.warning("目前選擇的機制在篩選條件下沒有資料可繪圖，請調整篩選或機制選擇。")
        return

    # 4. 顯示圖表
    chart_state = render_chart(grouped, metric_label, rank_limit)

    # 5. 詳細資料互動 (Drill Down)
    st.divider()
    
    # 解析點擊或使用 Session 紀錄
    click_year, click_mech = extract_selection(chart_state)
    
    avail_years = sorted(grouped["year"].unique())
    avail_mechs = sorted(grouped["mechanic"].unique())

    # 以目前篩選條件下的 Impact 排名決定 drill-down 預設 mechanic
    #（需落在 avail_mechs 內，確保下拉選單一定可選）
    impact_ranked_mechs = (
        impact_df.loc[impact_df.index.isin(avail_mechs)]
        .sort_values("impact", ascending=False)
        .index
        .tolist()
    )

    # 同步 State（點擊圖表後，要同步到 selectbox 的 key，否則 widget 仍會維持舊值）
    if click_year is not None and click_mech:
        if click_year in avail_years:
            st.session_state.detail_year = click_year
            st.session_state.detail_year_box = click_year
        if click_mech in avail_mechs:
            st.session_state.detail_mechanic = click_mech
            st.session_state.detail_mechanic_box = click_mech
    
    # 預設值防呆
    if "detail_year" not in st.session_state or st.session_state.detail_year not in avail_years:
        st.session_state.detail_year = avail_years[-1] if avail_years else 2020
    if "detail_mechanic" not in st.session_state or st.session_state.detail_mechanic not in avail_mechs:
        default_mech = impact_ranked_mechs[0] if impact_ranked_mechs else (avail_mechs[0] if avail_mechs else "")
        st.session_state.detail_mechanic = default_mech

    # 確保 selectbox 的 key 也有預設值（避免第一次以後 index 參數被忽略）
    if "detail_year_box" not in st.session_state or st.session_state.detail_year_box not in avail_years:
        st.session_state.detail_year_box = st.session_state.detail_year
    if "detail_mechanic_box" not in st.session_state or st.session_state.detail_mechanic_box not in avail_mechs:
        st.session_state.detail_mechanic_box = st.session_state.detail_mechanic

    # 詳細資料控制列
    col_sel1, col_sel2 = st.columns(2)
    with col_sel1:
        # 使用 index 來確保預設選中
        curr_mech = st.session_state.detail_mechanic
        idx_mech = avail_mechs.index(curr_mech) if curr_mech in avail_mechs else 0
        
        sel_mech = st.selectbox(
            "Mechanic", 
            avail_mechs, 
            index=idx_mech,
            key="detail_mechanic_box" # 與點擊圖表同步此 key，才能讓點擊生效
        )
    with col_sel2:
        curr_year = st.session_state.detail_year
        idx_year = avail_years.index(curr_year) if curr_year in avail_years else 0
        
        sel_year = st.selectbox(
            "Year", 
            avail_years, 
            index=idx_year,
            key="detail_year_box"
        )
    
    # 更新 session state
    st.session_state.detail_mechanic = sel_mech
    st.session_state.detail_year = sel_year

    # 6. 顯示詳細統計與遊戲列表
    if sel_mech and sel_year:
        # 重置分頁邏輯
        current_point = (sel_year, sel_mech)
        if st.session_state.get("_last_selected_point") != current_point:
            st.session_state._last_selected_point = current_point
            st.session_state.games_show_n = 10
        
        # 統計數據區塊
        row = grouped[(grouped["year"] == sel_year) & (grouped["mechanic"] == sel_mech)]
        if not row.empty:
            r = row.iloc[0]
            st.markdown(f"### {sel_mech} — {sel_year}")
            
            # 統計指標
            m1, m2, m3 = st.columns(3)
            # 固定顯示三個指標
            pop_val = float(r["count"])
            qlty_val = float(r["avg_geek"]) if pd.notna(r["avg_geek"]) else None
            imp_val = (qlty_val * np.log(pop_val + 1)) if qlty_val is not None else None

            m1.metric("Popularity", f"{int(pop_val)}")
            m2.metric("Quality", f"{qlty_val:.2f}" if qlty_val else "-")
            m3.metric("Impact", f"{imp_val:.2f}" if imp_val else "-")
            
            # 機制描述
            desc_info = desc_map.get(sel_mech, {})
            if desc_info.get("description"):
                st.write(desc_info["description"])
                if desc_info.get("url"):
                    st.markdown(f"來源：{desc_info['url']}")
            else:
                st.write("（無介紹文字）")

            # 遊戲列表
            st.markdown(f"### {sel_year}年包含{sel_mech}的遊戲列表")
            games_in_year = filtered_df[
                (filtered_df["year"] == sel_year) & 
                (filtered_df["mechanic"] == sel_mech)
            ].sort_values(["overall_rank", "rating_geek"], ascending=[True, False])
            
            games_in_year = games_in_year.drop_duplicates(subset=["bgg_id"])

            total_games = len(games_in_year)
            st.caption(f"共 {total_games} 款（已依 rank / rating 排序）")

            if "games_show_n" not in st.session_state:
                st.session_state.games_show_n = 10
            
            show_n = min(st.session_state.games_show_n, total_games)
            
            # 使用原版風格渲染
            for _, game in games_in_year.head(show_n).iterrows():
                render_game_card_original_style(game)
            
            if show_n < total_games:
                if st.button("顯示更多", key="show_more_games"):
                    st.session_state.games_show_n = min(total_games, st.session_state.games_show_n + 10)
                    st.rerun()
        else:
            st.warning("找不到該節點資料（可能是篩選條件變更後資料已不存在）。")

if __name__ == "__main__":
    main()
