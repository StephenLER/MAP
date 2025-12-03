#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
从三个 IMDb CSV 构建知识图谱，输出 GraphML。
只使用三个文件共同拥有的字段：
Title, Year, IMDb Rating, MetaScore, Duration (minutes),
Certificates, Genre, Director, Star Cast
"""

import re
import math
from pathlib import Path

import pandas as pd
import networkx as nx


CSV_FILES = [
    "data/IMDb_Dataset.csv",
    "data/IMDb_Dataset_2.csv",
    "data/IMDb_Dataset_3.csv",
]

COMMON_COLS = [
    "Title",
    "IMDb Rating",
    "Year",
    "Certificates",
    "Genre",
    "Director",
    "Star Cast",
    "MetaScore",
    "Duration (minutes)",
]


def split_star_cast(raw):
    """
    把 Star Cast 这一列拆成一个个独立人名。
    数据里的人名是黏在一起的，比如：
      "Tom CruiseHayley AtwellVing Rhames"
    用一个简单的规则按小写→大写的边界拆开，
    再对 Mac/Mc/Di/Le 等前缀做一点合并修复。

    注意：这是启发式方法，不是完美的姓名分词。
    """
    if pd.isna(raw):
        return []

    s = str(raw).strip()
    if not s:
        return []

    # 规范空格
    s = re.sub(r"\s+", " ", s)

    # 在小写→大写的边界拆分（没有空格）
    parts = re.split(r"(?<=[a-z])(?=[A-Z])", s)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) <= 1:
        return parts

    prefixes = {"Mc", "Mac", "De", "Di", "Le", "La", "Van", "Von", "O'"}
    merged = []
    i = 0
    while i < len(parts):
        part = parts[i].strip()
        if i + 1 < len(parts):
            last_token = part.split()[-1]
            if last_token in prefixes:
                # 把前缀碎片和下一段合并在一起
                part = (part + " " + parts[i + 1].lstrip()).strip()
                i += 1
        merged.append(part)
        i += 1

    return merged


def most_common_nonempty(series: pd.Series):
    """取 series 中最常见的非空值，没有则返回 None。"""
    s = series.dropna().astype(str).str.strip()
    s = s[s != ""]
    if s.empty:
        return None
    # 使用众数（可能有多个，取第一个）
    return s.mode().iloc[0]


def build_graph(df: pd.DataFrame) -> nx.MultiDiGraph:
    """
    根据整理好的 DataFrame 构建 MultiDiGraph。
    节点类型：
      - movie::Title (Year)
      - person::Name
      - genre::Name
      - certificate::Name
    边类型（通过 edge 属性 relation 标记）：
      - DIRECTED
      - ACTED_IN
      - HAS_GENRE
      - HAS_CERTIFICATE
    """
    G = nx.MultiDiGraph()

    def add_movie_node(title, year, row_group):
        movie_id = f"movie::{title} ({year})"

        # 数值属性用均值聚合
        imdb_rating = row_group["IMDb Rating"].mean()
        metascore = row_group["MetaScore"].mean()
        duration = row_group["Duration (minutes)"].mean()

        certificate = most_common_nonempty(row_group["Certificates"])
        genre = most_common_nonempty(row_group["Genre"])

        attrs = {
            "type": "movie",
            "title": title,
            "year": int(year) if not pd.isna(year) else None,
            "imdb_rating": float(imdb_rating) if not pd.isna(imdb_rating) else None,
            "metascore": float(metascore) if not pd.isna(metascore) else None,
            "duration_minutes": float(duration) if not pd.isna(duration) else None,
            "certificate": certificate,
            "genre_primary": genre,
        }

        # 去掉 None / NaN 属性，避免 GraphML 类型混乱
        clean_attrs = {}
        for k, v in attrs.items():
            if v is None:
                continue
            if isinstance(v, float) and math.isnan(v):
                continue
            clean_attrs[k] = v

        G.add_node(movie_id, **clean_attrs)
        return movie_id

    def add_person_node(name):
        person_id = f"person::{name}"
        if not G.has_node(person_id):
            G.add_node(person_id, type="person", name=name)
        return person_id

    def add_genre_node(name):
        genre_id = f"genre::{name}"
        if not G.has_node(genre_id):
            G.add_node(genre_id, type="genre", name=name)
        return genre_id

    def add_certificate_node(name):
        cert_id = f"certificate::{name}"
        if not G.has_node(cert_id):
            G.add_node(cert_id, type="certificate", name=name)
        return cert_id

    # 按 Title + Year 聚合，把多文件中的同一电影合并成一个 Movie 节点
    for (title, year), group in df.groupby(["Title", "Year"]):
        movie_id = add_movie_node(title, year, group)

        # 导演关系
        for d in group["Director"].dropna().unique():
            d = str(d).strip()
            if not d:
                continue
            director_id = add_person_node(d)
            G.add_edge(director_id, movie_id, relation="DIRECTED")

        # 演员关系（Star Cast）
        for raw_cast in group["Star Cast"].dropna().unique():
            for name in split_star_cast(raw_cast):
                actor_id = add_person_node(name)
                G.add_edge(actor_id, movie_id, relation="ACTED_IN")

        # 类型关系（只用公共字段 Genre）
        for gname in group["Genre"].dropna().unique():
            gname = str(gname).strip()
            if not gname:
                continue
            genre_id = add_genre_node(gname)
            G.add_edge(movie_id, genre_id, relation="HAS_GENRE")

        # 分级关系
        for cname in group["Certificates"].dropna().unique():
            cname = str(cname).strip()
            if not cname:
                continue
            cert_id = add_certificate_node(cname)
            G.add_edge(movie_id, cert_id, relation="HAS_CERTIFICATE")

    return G


def load_and_merge_csv(csv_files):
    """读取多个 CSV，只保留共同字段，然后合并。"""
    dfs = []
    for f in csv_files:
        path = Path(f)
        if not path.exists():
            raise FileNotFoundError(f"找不到文件：{path.resolve()}")
        df = pd.read_csv(path)
        missing = set(COMMON_COLS) - set(df.columns)
        if missing:
            raise ValueError(f"{path} 缺少这些公共列：{missing}")
        dfs.append(df[COMMON_COLS].copy())

    df = pd.concat(dfs, ignore_index=True)

    # 数值列类型转换
    numeric_cols = ["IMDb Rating", "MetaScore", "Duration (minutes)"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 字符串列清洗
    for col in ["Title", "Certificates", "Genre", "Director", "Star Cast"]:
        df[col] = df[col].astype(str).str.strip()

    return df


def main():
    df = load_and_merge_csv(CSV_FILES)
    print(f"合并后总行数: {len(df)}（包含重复电影记录）")

    G = build_graph(df)

    print(f"图中节点数: {G.number_of_nodes()}")
    print(f"图中边数:   {G.number_of_edges()}")

    out_path = Path("imdb_kg.graphml")
    nx.write_graphml(G, out_path)
    print(f"GraphML 已保存到: {out_path.resolve()}")


if __name__ == "__main__":
    main()
