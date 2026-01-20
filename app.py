#streamlit run app.py

import streamlit as st
from streamlit_option_menu import option_menu

# 匯入你兩個頁面的 main()
from app_mechanic_trends import main as mechanic_trends_main
from app_game_search import main as game_search_main
from app_category_trends import main as category_trends_main



# 1) 全站 page config 只做一次（必須是第一個 Streamlit 呼叫）
st.set_page_config(
    page_title="BGG Analytics",
    layout="wide",
    page_icon="🎲",
)

# 2) 做一個頂部橫向 Navbar
selected = option_menu(
    menu_title=None,  # 不顯示標題
    options=["Mechanics", "Categories", "Ranking", "Other"],
    icons=["bar-chart", "grid", "trophy", "three-dots"],
    orientation="horizontal",
    default_index=0,
    styles={
        "container": {"padding": "0.4rem 1rem", "background-color": "#5a5c77"},
        "icon": {"color": "white", "font-size": "18px"},
        "nav-link": {
            "font-size": "18px",
            "text-align": "left",
            "margin": "0px",
            "color": "white",
            "padding": "0.5rem 0.8rem",
        },
        "nav-link-selected": {"background-color": "#4b4d66"},
    },
)

# 3) 依照選單切換頁面（內容保持不變）
if selected == "Mechanics":
    mechanic_trends_main()

elif selected == "Ranking":
    game_search_main()
elif selected == "Categories":
    category_trends_main()
else:
    st.title(f"🚧 {selected}")
    st.info("這個頁面功能尚未完成。")
