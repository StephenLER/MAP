# kg_api.py
# -*- coding: utf-8 -*-
"""
KG API for the movie knowledge graph.

说明：
- 读取 imdb_kg.graphml（由你之前的 buildKG.py 生成）
- 提供一系列面向“电影问答”的查询函数，供上层（例如大模型）调用
- 所有函数都只做“结构化查询”，不做自然语言处理

重要约定：
- 通过电影名查询时，统一 **只传 title，不传 year**
- 如遇同名多部电影，将在内部自动选一个“代表电影”：
    - 优先 IMDb Rating 高的
    - 如果评分一样或缺失，再优先年份新的
"""

import os
from typing import List, Dict, Optional

import networkx as nx

# ----------------------------------------------------------------------
# 1. 加载图谱
# ----------------------------------------------------------------------

GRAPH_PATH = os.path.join(os.path.dirname(__file__), "imdb_kg.graphml")

if not os.path.exists(GRAPH_PATH):
    raise FileNotFoundError(f"找不到图文件：{GRAPH_PATH}")

G = nx.read_graphml(GRAPH_PATH)


def get_graph() -> nx.Graph:
    """如果在别处需要直接访问图对象，可以用这个函数获取。"""
    return G


# ----------------------------------------------------------------------
# 2. 通用工具函数
# ----------------------------------------------------------------------

def find_movie_nodes_by_title(title: str) -> List[str]:
    """
    根据片名找到所有同名电影的节点 ID 列表。

    返回的每个元素都是节点 id，例如 "movie::Inception (2010)"。
    """
    ids: List[str] = []
    for n, data in G.nodes(data=True):
        if data.get("type") == "movie" and data.get("title") == title:
            ids.append(n)
    return ids


def find_movie_node(title: str) -> Optional[str]:
    """
    根据片名找到一个“代表电影”的节点 ID。

    如果存在多部同名电影，则按以下规则自动选择：
    1) IMDb Rating 高的优先（缺失视为很低）
    2) 如评分相同或缺失，则年份更晚的优先（缺失视为很早）

    找不到则返回 None。
    """
    candidates = []
    for n, data in G.nodes(data=True):
        if data.get("type") != "movie":
            continue
        if data.get("title") != title:
            continue
        candidates.append((n, data))

    if not candidates:
        return None

    def _score(item):
        _, d = item
        rating = d.get("imdb_rating")
        year = d.get("year")
        try:
            rating_val = float(rating) if rating is not None else float("-inf")
        except (TypeError, ValueError):
            rating_val = float("-inf")
        try:
            year_val = int(year) if year is not None else float("-inf")
        except (TypeError, ValueError):
            year_val = float("-inf")
        # 返回一个元组，先比评分，再比年份
        return (rating_val, year_val)

    best_node, _ = max(candidates, key=_score)
    return best_node


def find_person_node(name: str) -> Optional[str]:
    """
    根据人名找到人物节点 ID（找不到返回 None）。

    人物节点的 id 规则是 "person::<Name>"。
    """
    node_id = f"person::{name}"
    if node_id in G:
        return node_id
    return None


def search_movies_by_keyword(
    keyword: str,
    case_sensitive: bool = False,
    limit: Optional[int] = None,
) -> List[Dict]:
    """
    按关键字在电影标题中模糊搜索。

    返回：列表，每个元素是 {title, year, imdb_rating}。
    """
    results: List[Dict] = []
    if not keyword:
        return results

    for n, data in G.nodes(data=True):
        if data.get("type") != "movie":
            continue
        title = data.get("title", "")
        if not case_sensitive:
            if keyword.lower() not in str(title).lower():
                continue
        else:
            if keyword not in str(title):
                continue
        results.append({
            "title": title,
            "year": data.get("year"),
            "imdb_rating": data.get("imdb_rating"),
        })
        if limit is not None and len(results) >= limit:
            break

    return results


# ----------------------------------------------------------------------
# 3. 电影相关查询
# ----------------------------------------------------------------------

def get_movie_basic_info(title: str) -> Optional[Dict]:
    """
    返回一部电影的基本信息和关联实体（按 title 自动选一部“代表电影”）。

    返回结构（找不到返回 None）：
    {
        "title": str,
        "year": int | None,
        "imdb_rating": float | None,
        "metascore": float | None,
        "duration_minutes": float | None,
        "directors": [str],
        "actors": [str],
        "genres": [str],
        "certificates": [str],
        "node_id": str
    }
    """
    movie_id = find_movie_node(title)
    if movie_id is None:
        return None

    data = G.nodes[movie_id]
    res: Dict = {
        "title": data.get("title"),
        "year": data.get("year"),
        "imdb_rating": data.get("imdb_rating"),
        "metascore": data.get("metascore"),
        "duration_minutes": data.get("duration_minutes"),
        "directors": [],
        "actors": [],
        "genres": [],
        "certificates": [],
        "node_id": movie_id,
    }

    # in_edges: 谁指向这部电影（导演 / 演员）
    for u, v, edge in G.in_edges(movie_id, data=True):
        rel = edge.get("relation")
        ndata = G.nodes[u]
        if rel == "DIRECTED":
            res["directors"].append(ndata.get("name"))
        elif rel == "ACTED_IN":
            res["actors"].append(ndata.get("name"))

    # out_edges: 电影指向谁（类型 / 分级）
    for u, v, edge in G.out_edges(movie_id, data=True):
        rel = edge.get("relation")
        ndata = G.nodes[v]
        if rel == "HAS_GENRE":
            res["genres"].append(ndata.get("name"))
        elif rel == "HAS_CERTIFICATE":
            res["certificates"].append(ndata.get("name"))

    # 去重并排序
    for key in ["directors", "actors", "genres", "certificates"]:
        res[key] = sorted({x for x in res[key] if x})

    return res


def get_similar_movies_by_neighbors(
    title: str,
    top_k: int = 10,
) -> Dict:
    """
    基于“共享邻居”的简单相似电影推荐（图结构相似度）。

    输入：
        title：电影标题（内部自动选一部代表电影）

    思路：
    - 从目标电影节点出发，找到所有邻居（导演 / 演员 / 类型 / 分级）
    - 再从这些邻居出发，回到其它电影节点
    - 按共享邻居数量打分，取前 top_k 个

    返回：
    {
        "movie": {"title": ..., "year": ..., "imdb_rating": ..., "node_id": ...} | None,
        "similar_movies": [
            {"title": ..., "year": ..., "imdb_rating": ..., "score": int},
            ...
        ]
    }
    """
    movie_id = find_movie_node(title)
    if movie_id is None:
        return {"movie": None, "similar_movies": []}

    data = G.nodes[movie_id]
    base_info = {
        "title": data.get("title"),
        "year": data.get("year"),
        "imdb_rating": data.get("imdb_rating"),
        "node_id": movie_id,
    }

    # 为了方便，把有向图当无向图看
    UG = G.to_undirected()
    neighbors = list(UG.neighbors(movie_id))

    scores: Dict[str, int] = {}
    for n in neighbors:
        # 从邻居回到其它电影
        for m in UG.neighbors(n):
            if m == movie_id:
                continue
            if G.nodes[m].get("type") != "movie":
                continue
            scores[m] = scores.get(m, 0) + 1

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    similar_movies = []
    for mid, score in ranked[:top_k]:
        md = G.nodes[mid]
        similar_movies.append({
            "title": md.get("title"),
            "year": md.get("year"),
            "imdb_rating": md.get("imdb_rating"),
            "score": score,
        })

    return {"movie": base_info, "similar_movies": similar_movies}


# ----------------------------------------------------------------------
# 4. 人物相关查询（导演 / 演员）
# ----------------------------------------------------------------------

def get_movies_by_director(
    name: str,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    sort_by: str = "year",
    descending: bool = False,
    limit: Optional[int] = None,
) -> List[Dict]:
    """
    按导演查电影，可选年份过滤和排序。

    返回：列表，每个元素：
    {
        "title": str,
        "year": int | None,
        "imdb_rating": float | None,
        "metascore": float | None
    }
    """
    node_id = find_person_node(name)
    if not node_id:
        return []

    results: List[Dict] = []

    for u, v, edge in G.out_edges(node_id, data=True):
        if edge.get("relation") != "DIRECTED":
            continue
        mdata = G.nodes[v]
        if mdata.get("type") != "movie":
            continue

        y = mdata.get("year")
        try:
            y_int = int(y) if y is not None else None
        except (TypeError, ValueError):
            y_int = None

        if year_min is not None and (y_int is None or y_int < year_min):
            continue
        if year_max is not None and (y_int is None or y_int > year_max):
            continue

        results.append({
            "title": mdata.get("title"),
            "year": y_int,
            "imdb_rating": mdata.get("imdb_rating"),
            "metascore": mdata.get("metascore"),
        })

    # 排序
    if sort_by in {"year", "imdb_rating", "metascore"}:
        results.sort(
            key=lambda x: (x.get(sort_by) is None, x.get(sort_by)),
            reverse=descending,
        )

    if limit is not None:
        results = results[:limit]

    return results


def get_movies_by_actor(
    name: str,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    sort_by: str = "year",
    descending: bool = False,
    limit: Optional[int] = None,
) -> List[Dict]:
    """
    按演员查电影，可选年份过滤和排序。

    返回结构与 get_movies_by_director 类似。
    """
    node_id = find_person_node(name)
    if not node_id:
        return []

    results: List[Dict] = []

    for u, v, edge in G.out_edges(node_id, data=True):
        if edge.get("relation") != "ACTED_IN":
            continue
        mdata = G.nodes[v]
        if mdata.get("type") != "movie":
            continue

        y = mdata.get("year")
        try:
            y_int = int(y) if y is not None else None
        except (TypeError, ValueError):
            y_int = None

        if year_min is not None and (y_int is None or y_int < year_min):
            continue
        if year_max is not None and (y_int is None or y_int > year_max):
            continue

        results.append({
            "title": mdata.get("title"),
            "year": y_int,
            "imdb_rating": mdata.get("imdb_rating"),
            "metascore": mdata.get("metascore"),
        })

    if sort_by in {"year", "imdb_rating", "metascore"}:
        results.sort(
            key=lambda x: (x.get(sort_by) is None, x.get(sort_by)),
            reverse=descending,
        )

    if limit is not None:
        results = results[:limit]

    return results


def get_co_actors(name: str, top_k: Optional[int] = None) -> List[Dict]:
    """
    计算某个演员的“合作演员”（共同出演过电影的人），按合作次数排序。

    返回：
    [
        {"name": "Another Actor", "count": 5},
        ...
    ]
    """
    node_id = find_person_node(name)
    if not node_id:
        return []

    # 先找出他参演的所有电影
    movies: List[str] = []
    for u, v, edge in G.out_edges(node_id, data=True):
        if edge.get("relation") != "ACTED_IN":
            continue
        if G.nodes[v].get("type") == "movie":
            movies.append(v)

    # 再在这些电影中找其他演员
    co_counts: Dict[str, int] = {}

    for movie_id in set(movies):
        for u, v, edge in G.in_edges(movie_id, data=True):
            if edge.get("relation") != "ACTED_IN":
                continue
            if u == node_id:
                continue
            pdata = G.nodes[u]
            if pdata.get("type") != "person":
                continue
            pname = pdata.get("name")
            if not pname:
                continue
            co_counts[pname] = co_counts.get(pname, 0) + 1

    co_list = [{"name": k, "count": v} for k, v in co_counts.items()]
    co_list.sort(key=lambda x: x["count"], reverse=True)

    if top_k is not None:
        co_list = co_list[:top_k]

    return co_list


# ----------------------------------------------------------------------
# 5. 类型 / 分级相关查询
# ----------------------------------------------------------------------

def get_movies_by_genre(
    genre_name: str,
    rating_min: Optional[float] = None,
    sort_by_rating: bool = False,
    limit: Optional[int] = None,
) -> List[Dict]:
    """
    按类型查电影，可设置 IMDb 评分下限，并按评分排序。

    返回：
    [
        {"title": ..., "year": ..., "imdb_rating": ..., "metascore": ...},
        ...
    ]
    """
    genre_id = f"genre::{genre_name}"
    if genre_id not in G:
        return []

    results: List[Dict] = []
    for u, v, edge in G.in_edges(genre_id, data=True):
        if edge.get("relation") != "HAS_GENRE":
            continue
        mdata = G.nodes[u]
        if mdata.get("type") != "movie":
            continue

        rating = mdata.get("imdb_rating")
        try:
            r_float = float(rating) if rating is not None else None
        except (TypeError, ValueError):
            r_float = None

        if rating_min is not None and (r_float is None or r_float < rating_min):
            continue

        results.append({
            "title": mdata.get("title"),
            "year": mdata.get("year"),
            "imdb_rating": r_float,
            "metascore": mdata.get("metascore"),
        })

    if sort_by_rating:
        results.sort(
            key=lambda x: (x["imdb_rating"] is None, x["imdb_rating"]),
            reverse=True,
        )

    if limit is not None:
        results = results[:limit]

    return results


def get_movies_by_certificate(
    cert_name: str,
    limit: Optional[int] = None,
) -> List[Dict]:
    """
    按分级查电影（例如 "PG-13", "R"）。

    返回同样是电影列表。
    """
    cert_id = f"certificate::{cert_name}"
    if cert_id not in G:
        return []

    results: List[Dict] = []
    for u, v, edge in G.in_edges(cert_id, data=True):
        if edge.get("relation") != "HAS_CERTIFICATE":
            continue
        mdata = G.nodes[u]
        if mdata.get("type") != "movie":
            continue

        results.append({
            "title": mdata.get("title"),
            "year": mdata.get("year"),
            "imdb_rating": mdata.get("imdb_rating"),
            "metascore": mdata.get("metascore"),
        })

    # 简单按年份排序
    def _year_key(x):
        y = x.get("year")
        try:
            return int(y)
        except (TypeError, ValueError):
            return 0

    results.sort(key=_year_key)

    if limit is not None:
        results = results[:limit]

    return results


# ----------------------------------------------------------------------
# 6. 复合查询：基于一部电影做拓展
# ----------------------------------------------------------------------

def get_other_movies_by_director_of_movie(title: str) -> Optional[Dict]:
    """
    给一部电影（按 title 自动选代表电影）→ 找导演 → 列出每个导演的其它作品。

    返回结构：
    {
        "movie": {"title": ..., "year": ..., "node_id": ...},
        "by_director": [
            {
                "director": "Name",
                "other_movies": [
                    {"title": ..., "year": ..., "imdb_rating": ...},
                    ...
                ]
            },
            ...
        ]
    }

    找不到这部电影时，返回 None。
    """
    info = get_movie_basic_info(title)
    if info is None:
        return None

    this_title = info.get("title")
    this_year = info.get("year")
    this_node = info.get("node_id")

    result_by_director: List[Dict] = []

    for director in info.get("directors", []):
        movies = get_movies_by_director(director)
        others = []
        for m in movies:
            if m.get("title") == this_title and m.get("year") == this_year:
                continue
            others.append({
                "title": m.get("title"),
                "year": m.get("year"),
                "imdb_rating": m.get("imdb_rating"),
            })
        result_by_director.append({
            "director": director,
            "other_movies": others,
        })

    return {
        "movie": {"title": this_title, "year": this_year, "node_id": this_node},
        "by_director": result_by_director,
    }


# ----------------------------------------------------------------------
# 7. 简单自测
# ----------------------------------------------------------------------

if __name__ == "__main__":
    print("图节点数:", G.number_of_nodes())
    print("图边数:", G.number_of_edges())

    demo = get_movie_basic_info("Inception")
    print("\n[Demo] get_movie_basic_info('Inception'):")
    print(demo)

    print("\n[Demo] get_movies_by_director('Christopher Nolan'):")
    print(get_movies_by_director("Christopher Nolan", sort_by="year"))

    print(
        "\n[Demo] get_movies_by_genre('Action', rating_min=8.0, "
        "sort_by_rating=True, limit=5):"
    )
    print(get_movies_by_genre("Action", rating_min=8.0, sort_by_rating=True, limit=5))

    print("\n[Demo] get_other_movies_by_director_of_movie('Inception'):")
    print(get_other_movies_by_director_of_movie("Inception"))

    print("\n[Demo] search_movies_by_keyword('Mission'):")
    print(search_movies_by_keyword("Mission", limit=10))

    print("\n[Demo] get_co_actors('Tom Cruise', top_k=10):")
    print(get_co_actors("Tom Cruise", top_k=10))
