```python
import networkx as nx
G = nx.read_graphml("imdb_kg.graphml")
```

你的图是用 `nx.MultiDiGraph()` 建的，所以是**多重有向图**：

* **有向**：有“谁指向谁”的方向（导演→电影、电影→类型……）
* **多重**：同一对节点之间允许存在多条边（比如理论上可以有多条 ACTED_IN）

---

## 1. 节点相关：`G.nodes(...)` 到底返回啥？

### 1.1 只看节点 ID：`G.nodes`

```python
print(len(G.nodes))
for n in list(G.nodes)[:5]:
    print(n)
```

**含义：**

* `G.nodes` 是一个 *NodeView*，你可以当成节点 ID 的集合来用
* 每个 `n` 就是一个节点的 **唯一 ID**，在你的图里例如：

  * `movie::Inception (2010)`
  * `person::Christopher Nolan`
  * `genre::Action`
  * `certificate::PG-13`

### 1.2 带属性：`G.nodes(data=True)`

```python
for n, attrs in list(G.nodes(data=True))[:5]:
    print("node id:", n)
    print("attrs:", attrs)
```

**每一项是：**

* `n`：节点 ID（字符串）
* `attrs`：一个 `dict`，就是你在 `add_node` 时传进去的所有属性

在你的电影图里，典型样子：

```text
node id: movie::Inception (2010)
attrs: {
  'type': 'movie',
  'title': 'Inception',
  'year': 2010,
  'imdb_rating': 8.8,
  'metascore': 74.0,
  'duration_minutes': 148.0,
  'certificate': 'PG-13',
  'genre_primary': 'Action'
}
```

**关键：**

* `type`：是你自己定义用来区分节点类型的字段（movie / person / genre / certificate）
* 其它字段就是你在建图时塞进去的属性

访问方式：

```python
G.nodes[n]["type"]
G.nodes[n]["title"]
```

---

## 2. 边相关：`G.edges` / `in_edges` / `out_edges`

### 2.1 整体看边：`G.edges(data=True)`

```python
for u, v, attrs in list(G.edges(data=True))[:5]:
    print("from:", u)
    print("to:  ", v)
    print("attrs:", attrs)
    print("---")
```

在你的 `MultiDiGraph` 里，这个返回的是一堆三元组：

* `u`：起点节点 ID（source）
* `v`：终点节点 ID（target）
* `attrs`：一条边的属性 dict

你建图时是这样加边的：

```python
G.add_edge(director_id, movie_id, relation="DIRECTED")
G.add_edge(actor_id, movie_id, relation="ACTED_IN")
G.add_edge(movie_id, genre_id, relation="HAS_GENRE")
G.add_edge(movie_id, cert_id, relation="HAS_CERTIFICATE")
```

所以某条边看起来会像：

```text
from: person::Christopher Nolan
to:   movie::Inception (2010)
attrs: {'relation': 'DIRECTED'}
```

**这里“每个字段的含义”：**

* `u`：边的“from”，谁发出这条关系
* `v`：边的“to”，指向谁
* `attrs["relation"]`：你自己定义的关系类型（DIRECTED / ACTED_IN / HAS_GENRE / HAS_CERTIFICATE）

---

### 2.2 只看某个节点发出去的边：`G.out_edges(node, data=True)`

**原理：**

* 对于有向图，`out_edges(node)` 就是：**从这个节点出发的所有边**
* 在你的图里：

  * 对 **person** 节点：`out_edges` 主要是 DIRECTED / ACTED_IN 边
  * 对 **movie** 节点：`out_edges` 主要是 HAS_GENRE / HAS_CERTIFICATE 边

**示例：**

```python
node = "person::Christopher Nolan"
for u, v, attrs in G.out_edges(node, data=True):
    print("from:", u)
    print("to:  ", v)
    print("relation:", attrs.get("relation"))
```

输出类似：

```text
from: person::Christopher Nolan
to:   movie::Inception (2010)
relation: DIRECTED
from: person::Christopher Nolan
to:   movie::Interstellar (2014)
relation: DIRECTED
...
```

**解释：**

* `out_edges` 不会看“边的含义”，只是从底层 adjacency 里拿出“从 node 出发的所有边”
* 你通过 `attrs["relation"]` 来判断这条边在语义上是什么关系

---

### 2.3 只看某个节点指向它的边：`G.in_edges(node, data=True)`

**原理：**

* 对有向图，`in_edges(node)` 就是：**所有指向这个节点的边**

在你的图里：

* 对 **movie 节点**：

  * 来自 DIRECTED 边 → 导演是谁
  * 来自 ACTED_IN 边 → 演员是谁

**示例：**

```python
movie = "movie::Inception (2010)"
for u, v, attrs in G.in_edges(movie, data=True):
    print("from:", u)
    print("to:  ", v)
    print("relation:", attrs.get("relation"))
```

可能输出：

```text
from: person::Christopher Nolan
to:   movie::Inception (2010)
relation: DIRECTED
from: person::Leonardo DiCaprio
to:   movie::Inception (2010)
relation: ACTED_IN
...
```

**解释字段：**

* `u`：导演 / 演员 / 其它实体
* `v`：就是你指定的 `movie` 节点
* `attrs["relation"]`：告诉你这条边是“导演了”还是“参演了”

---

## 3. 邻居相关：`neighbors` 和 `to_undirected`

有时候你不在乎边方向，只想知道“跟这个节点相连的所有节点是谁”。

### 3.1 简单邻居：`neighbors(node)`

在**无向图**里，`neighbors(node)` 就是所有相连节点；
在有向图里，它返回：**出边和入边都算上的邻居**。

但是 NetworkX 推荐的写法是，如果你想明确“不考虑方向”，可以先转成无向图：

```python
UG = G.to_undirected()

for n in UG.neighbors("movie::Inception (2010)"):
    print(n, G.nodes[n].get("type"), G.nodes[n])
```

你会看到：

* 一堆 `person::...` → 导演 / 演员
* 若干 `genre::...` → 类型
* 1 个 `certificate::...` → 分级

**原理：**

* `to_undirected()` 把每条有向边复制成一条无向边
* `neighbors(node)` 在无向图上就很好理解：任何跟它有边相连的点都是邻居

---

## 4. 底层原理一眼看懂版

NetworkX 的图本质上是一堆嵌套字典（dict of dict of dict）：

* 节点属性存放在：

  ```python
  G._node[node_id]  # 就是 attrs dict
  ```
* 有向图的边存放在类似：

  ```python
  G._adj[u][v]  # 对应 u→v 的所有边属性（多重图是再嵌套一层 key）
  ```

所以：

* `G.nodes(data=True)` → 把 `G._node` 这层 dict 挨个吐出来
* `G.edges(data=True)` → 把 `G._adj` 里所有 (u,v,attrs) 吐出来
* `G.out_edges(n, data=True)` → 从 `G._adj[n]` 这块取出所有以 n 为起点的边
* `G.in_edges(n, data=True)` → 对 `G._pred[n]`（前驱表）做类似操作

你不需要记住内部私有属性，但知道它们本质上都是**“从字典里过滤出你要的那部分 (节点 or 边 or 属性)”**就够了。

---

## 5. 跟你项目相关的几种典型组合

快速总结几个你现在最常用的查询模式，并标注每个字段的意义：

### 5.1 从电影找导演

```python
movie_id = "movie::Inception (2010)"

for u, v, attrs in G.in_edges(movie_id, data=True):
    # u: 指向电影的节点（人）
    # v: 电影节点本身 (movie_id)
    # attrs: 这条边的属性字典，如 {'relation': 'DIRECTED'}
    if attrs.get("relation") == "DIRECTED":
        print("导演节点 id:", u)
        print("导演名字:", G.nodes[u]["name"])
```

### 5.2 从导演找所有导演过的电影

```python
director_id = "person::Christopher Nolan"

for u, v, attrs in G.out_edges(director_id, data=True):
    # u: 导演节点本身 (director_id)
    # v: 被指向的节点（通常是电影）
    # attrs: {'relation': 'DIRECTED'} 或其他
    if attrs.get("relation") == "DIRECTED":
        movie_data = G.nodes[v]
        print(movie_data["title"], movie_data["year"])
```

### 5.3 判断当前遍历到的节点/边是什么“类型”

* 节点类型：`G.nodes[n]["type"]`
* 边类型：`attrs["relation"]`

---

