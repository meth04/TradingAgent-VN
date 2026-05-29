import os
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = os.getenv("NEWS_DB_PATH", str(PROJECT_ROOT / "data" / "news.db"))
DEFAULT_DATE_FROM = date.fromisoformat(os.getenv("INGEST_DATE_FROM", "2025-01-01"))
DEFAULT_DATE_TO = date.fromisoformat(os.getenv("INGEST_DATE_TO", date.today().isoformat()))
DEFAULT_SOURCE = "cafef"
TABLE_LIMIT = 200

st.set_page_config(page_title="CafeF Canonical Dashboard", layout="wide")
st.title("CafeF Canonical Dashboard")


@st.cache_data(ttl=30)
def load_df(query: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    con = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(query, con, params=params)
    finally:
        con.close()


@st.cache_data(ttl=30)
def load_filter_options() -> tuple[list[str], list[str]]:
    sections_df = load_df(
        """
        select distinct seed_section
        from articles
        where source = ? and seed_section is not null and trim(seed_section) <> ''
        order by seed_section
        """,
        (DEFAULT_SOURCE,),
    )
    categories_df = load_df(
        """
        select distinct category
        from articles
        where source = ? and category is not null and trim(category) <> ''
        order by category
        """,
        (DEFAULT_SOURCE,),
    )
    sections = sections_df["seed_section"].tolist() if not sections_df.empty else []
    categories = categories_df["category"].tolist() if not categories_df.empty else []
    return sections, categories


def build_articles_filter_clause(
    *,
    source: str,
    selected_sections: list[str],
    selected_categories: list[str],
    min_fomo: float,
    keyword: str,
) -> tuple[str, list[Any], str]:
    clauses = ["a.source = ?", "a.published_date between ? and ?", "a.fomo_score >= ?"]
    params: list[Any] = [source, str(date_from), str(date_to), float(min_fomo)]
    fts_join = ""

    if selected_sections:
        placeholders = ", ".join("?" for _ in selected_sections)
        clauses.append(f"a.seed_section in ({placeholders})")
        params.extend(selected_sections)

    if selected_categories:
        placeholders = ", ".join("?" for _ in selected_categories)
        clauses.append(f"a.category in ({placeholders})")
        params.extend(selected_categories)

    keyword = keyword.strip()
    if keyword:
        fts_join = " join articles_fts on articles_fts.rowid = a.id"
        clauses.append("articles_fts match ?")
        params.append(keyword)

    return " and ".join(clauses), params, fts_join


st.sidebar.header("Filters")
date_from = st.sidebar.date_input("From", value=DEFAULT_DATE_FROM)
date_to = st.sidebar.date_input("To", value=DEFAULT_DATE_TO)
section_options, category_options = load_filter_options()
selected_sections = st.sidebar.multiselect("Sections", section_options, default=section_options)
selected_categories = st.sidebar.multiselect(
    "Categories", category_options, default=category_options
)
min_fomo = st.sidebar.slider("Min fomo", min_value=-1.0, max_value=1.0, value=-1.0, step=0.1)
keyword = st.sidebar.text_input("Keyword (FTS)", value="")

where_clause, where_params, fts_join = build_articles_filter_clause(
    source=DEFAULT_SOURCE,
    selected_sections=selected_sections,
    selected_categories=selected_categories,
    min_fomo=min_fomo,
    keyword=keyword,
)

stats = load_df(
    f"""
    select
      count(*) as total_articles,
      count(distinct a.seed_section) as section_count,
      count(distinct a.category) as category_count,
      max(a.published_at) as latest_published_at
    from articles a
    {fts_join}
    where {where_clause}
    """,
    tuple(where_params),
)

latest_run = load_df(
    """
    select started_at, finished_at, mode, inserted_count,
           dropped_no_date_count, dropped_irrelevant_count,
           dropped_out_of_window_count, dedup_dropped_count, error
    from ingest_runs
    order by id desc
    limit 1
    """
)

daily_counts = load_df(
    f"""
    select
      a.published_date,
      count(*) as article_count
    from articles a
    {fts_join}
    where {where_clause}
    group by a.published_date
    order by a.published_date
    """,
    tuple(where_params),
)

section_breakdown = load_df(
    f"""
    select
      a.seed_section,
      count(*) as article_count,
      min(a.published_at) as earliest_published_at,
      max(a.published_at) as latest_published_at
    from articles a
    {fts_join}
    where {where_clause}
    group by a.seed_section
    order by article_count desc, a.seed_section asc
    limit 50
    """,
    tuple(where_params),
)

latest_articles = load_df(
    f"""
    select
      a.published_at,
      a.seed_section,
      a.category,
      a.title,
      a.fomo_score,
      a.url
    from articles a
    {fts_join}
    where {where_clause}
    order by a.published_at desc
    limit {TABLE_LIMIT}
    """,
    tuple(where_params),
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("CafeF articles", int(stats.loc[0, "total_articles"]) if not stats.empty else 0)
c2.metric("Sections", int(stats.loc[0, "section_count"]) if not stats.empty else 0)
c3.metric("Categories", int(stats.loc[0, "category_count"]) if not stats.empty else 0)
c4.metric(
    "Latest published_at",
    stats.loc[0, "latest_published_at"]
    if not stats.empty and stats.loc[0, "latest_published_at"]
    else "-",
)

if not latest_run.empty:
    st.caption(
        "Last ingest run: "
        f"mode={latest_run.loc[0, 'mode']} inserted={latest_run.loc[0, 'inserted_count']} "
        f"dropped_no_date={latest_run.loc[0, 'dropped_no_date_count']} "
        f"dedup_dropped={latest_run.loc[0, 'dedup_dropped_count']}"
    )

st.subheader("Articles per day")
if not daily_counts.empty:
    st.line_chart(daily_counts.set_index("published_date")[["article_count"]], width="stretch")
else:
    st.info("No CafeF canonical articles for current filters.")

s1, s2 = st.columns([1, 2])

s1.subheader("Section breakdown")
if not section_breakdown.empty:
    s1.dataframe(section_breakdown, width="stretch")
else:
    s1.info("No section breakdown available.")

s2.subheader("Latest articles")
if not latest_articles.empty:
    s2.dataframe(
        latest_articles,
        column_config={"url": st.column_config.LinkColumn("URL")},
        width="stretch",
    )
else:
    s2.info("No articles available.")
