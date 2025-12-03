import networkx as nx

G = nx.read_graphml("imdb_kg.graphml")

# 例 1：查某个导演的所有电影
def movies_by_director(name: str):
    person_id = f"person::{name}"
    if person_id not in G:
        return []
    movies = [
        G.nodes[v]["title"]
        for u, v, data in G.out_edges(person_id, data=True)
        if data.get("relation") == "DIRECTED"
    ]
    return sorted(set(movies))

# 例 2：查某个演员参演的所有电影
def movies_by_actor(name: str):
    person_id = f"person::{name}"
    if person_id not in G:
        return []
    movies = [
        G.nodes[v]["title"]
        for u, v, data in G.out_edges(person_id, data=True)
        if data.get("relation") == "ACTED_IN"
    ]
    return sorted(set(movies))

# 例 3：查某个类型下的所有电影
def movies_by_genre(genre_name: str):
    genre_id = f"genre::{genre_name}"
    if genre_id not in G:
        return []
    movies = [
        G.nodes[u]["title"]
        for u, v, data in G.in_edges(genre_id, data=True)
        if data.get("relation") == "HAS_GENRE"
    ]
    return sorted(set(movies))


if __name__ == "__main__":
    print("导演 Christopher Nolan 的电影：")
    print(movies_by_director("Christopher Nolan"))

    print("\n演员 Tom Cruise 的电影：")
    print(movies_by_actor("Tom Cruise"))

    print("\n类型 Action 的电影示例：")
    print(movies_by_genre("Action")[:20])
