# Movie Knowledge Graph (IMDb CSV → GraphML)

本项目的目标是：  
从 3 个 IMDb 相关的 CSV 文件中，**抽取公共字段**，构建一张以“电影”为中心的**知识图谱（Knowledge Graph）**，并导出为 `GraphML` 格式，方便在 Neo4j、Gephi、Cytoscape 或 Python 中进行查询和可视化。

---

## 1. 数据来源（Data Sources）

当前使用的数据文件示例：

- `data/IMDb_Dataset.csv`
- `data/IMDb_Dataset_2.csv`
- `data/IMDb_Dataset_3.csv`

这三个文件的列名不完全一致，但有一组**公共字段**在三个文件中都存在，本项目只基于这些共同字段建图：

- `Title`
- `Year`
- `IMDb Rating`
- `MetaScore`
- `Duration (minutes)`
- `Certificates`
- `Genre`
- `Director`
- `Star Cast`

> **重要约束：**  
> 整个图谱只使用以上公共字段，不依赖任何某个文件独有的列（如海报链接、第二/第三类型等）。

---

## 2. 图谱结构概述（Graph Schema）

本图谱是一个**有向多重图**（`MultiDiGraph`），包含 4 类节点和 4 种主要关系。

### 2.1 节点类型（Node Types）

#### 2.1.1 Movie 节点

- **类型标记**：`type = "movie"`
- **节点 ID 规则**：  
  `movie::<Title> (<Year>)`  
  例如：`movie::Inception (2010)`

- **来源字段（按 Title + Year 聚合后的属性）：**
  - `title` ← `Title`
  - `year` ← `Year`
  - `imdb_rating` ← 同一电影在多个 CSV 中的 `IMDb Rating` 的**均值**
  - `metascore` ← 同一电影的 `MetaScore` 的均值
  - `duration_minutes` ← 同一电影的 `Duration (minutes)` 的均值
  - `certificate` ← 同一电影的 `Certificates` 中出现次数最多的值
  - `genre_primary` ← 同一电影的 `Genre` 中出现次数最多的值

> **去重策略：**  
> 使用 `(Title, Year)` 作为电影实体的逻辑主键。  
> 即：同名同年的电影记录（不管来自哪个 CSV）被视为同一部电影，合并为一个 Movie 节点。

---

#### 2.1.2 Person 节点（导演 / 演员）

- **类型标记**：`type = "person"`
- **节点 ID 规则**：  
  `person::<Name>`  
  例如：`person::Tom Cruise`

- **来源字段：**
  - `Director`
  - `Star Cast`

- **节点属性：**
  - `name`：人物姓名（从 Director 或 Star Cast 中抽取）

> 一个 Person 节点可以同时作为导演和演员，具体角色通过边的类型体现（DIRECTED / ACTED_IN），而不是通过节点属性区分。

---

#### 2.1.3 Genre 节点（类型）

- **类型标记**：`type = "genre"`
- **节点 ID 规则**：  
  `genre::<Name>`  
  例如：`genre::Action`

- **来源字段：**
  - `Genre`（仅使用公共字段里的主类型）

- **节点属性：**
  - `name`：类型名称（例如 "Action", "Drama", "Documentary"）

---

#### 2.1.4 Certificate 节点（分级）

- **类型标记**：`type = "certificate"`
- **节点 ID 规则**：  
  `certificate::<Name>`  
  例如：`certificate::PG-13`

- **来源字段：**
  - `Certificates`

- **节点属性：**
  - `name`：分级名称（例如 "PG", "PG-13", "R", "G" 等）

---

### 2.2 关系类型（Edge Types）

所有边都带有 `relation` 属性，用于标识关系类型。

#### 2.2.1 DIRECTED（导演了）

- **方向**：`Person → Movie`
- **关系类型标记**：`relation = "DIRECTED"`
- **来源字段**：`Director`

含义：  
某个 Person 节点是某个 Movie 节点的导演。

---

#### 2.2.2 ACTED_IN（参演了）

- **方向**：`Person → Movie`
- **关系类型标记**：`relation = "ACTED_IN"`
- **来源字段**：`Star Cast`

含义：  
某个 Person 节点在某个 Movie 节点中出演 / 参与演出。

> `Star Cast` 原本是一个混合姓名的字符串字段，如 `"Tom CruiseHayley AtwellVing Rhames"`，脚本中通过启发式规则进行姓名拆分，然后为每个姓名建立 Person 节点并连边。

---

#### 2.2.3 HAS_GENRE（属于类型）

- **方向**：`Movie → Genre`
- **关系类型标记**：`relation = "HAS_GENRE"`
- **来源字段**：`Genre`

含义：  
某个 Movie 节点属于某个 Genre 节点。

> 当前版本只使用公共字段中的主类型 `Genre`。  
> 如果未来需要多类型（第二、第三类型），可以在 schema 中扩展更多 HAS_GENRE 边。

---

#### 2.2.4 HAS_CERTIFICATE（具有分级）

- **方向**：`Movie → Certificate`
- **关系类型标记**：`relation = "HAS_CERTIFICATE"`
- **来源字段**：`Certificates`

含义：  
某个 Movie 节点拥有某个 Certificate 分级。

---

### 2.3 图的整体形态

整体图结构可以概括为：

- **Movie** 为中心节点
- 向外连接：
  - `Person`（导演/演员）  
    - `Person -[:DIRECTED]-> Movie`  
    - `Person -[:ACTED_IN]-> Movie`
  - `Genre`（类型）  
    - `Movie -[:HAS_GENRE]-> Genre`
  - `Certificate`（分级）  
    - `Movie -[:HAS_CERTIFICATE]-> Certificate`

这样构成一个以电影为中心的**异构知识图谱**，支持从电影出发查看导演、演员、类型和分级，也支持从人物或类型出发，反查相关电影。

---

## 3. 建图流程（Pipeline）

下面说明从 CSV 到 GraphML 的完整构建流程。

### 3.1 安装依赖

确保已安装 Python 及下面的依赖：

```bash
pip install pandas networkx
```

### 3.2 脚本入口

假定构图脚本为：`buildKG.py`  
核心步骤如下：

1. 读取三个 CSV 文件
2. 只保留公共字段
3. 合并为一个总表 DataFrame
4. 基于 `(Title, Year)` 合并电影记录，构建 Movie 节点
5. 从 `Director` 和 `Star Cast` 提取 Person 节点与关系
6. 从 `Genre`、`Certificates` 构建 Genre / Certificate 节点与关系
7. 使用 NetworkX 构建有向多重图 `MultiDiGraph`
8. 导出为 `GraphML` 文件（例如 `imdb_kg.graphml`）

---

### 3.3 读取和合并数据

在脚本中，首先定义文件列表和公共字段：

```python
CSV_FILES = [
    r"data\IMDb_Dataset.csv",
    r"data\IMDb_Dataset_2.csv",
    r"data\IMDb_Dataset_3.csv",
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
```

然后：

1. 对每个 CSV：
   - 读取为 DataFrame
   - 检查是否包含所有 `COMMON_COLS`
   - 只保留这几列
2. 将三个 DataFrame `concat` 合并为一个大表
3. 对数值列进行类型转换（非数字转为 `NaN`）：
   - `IMDb Rating`
   - `MetaScore`
   - `Duration (minutes)`
4. 对字符串列进行基本清洗（`strip()` 去空格）

---

### 3.4 电影去重与 Movie 节点构建

- 使用 `df.groupby(["Title", "Year"])` 对合并后的大表按 `(Title, Year)` 分组。
- 每个分组代表“认为是同一部电影”的多条记录。
- 对每个分组：
  - 聚合数值字段：取均值（`mean()`）
  - 聚合分类字段（`Certificates`, `Genre`）：取出现频率最高的值（众数）
  - 调用 `add_movie_node(...)` 创建一个 Movie 节点：
    - 节点 ID：`movie::<Title> (<Year>)`
    - 节点属性：`title, year, imdb_rating, metascore, duration_minutes, certificate, genre_primary`

> 这样可以把来自不同 CSV 的同一电影整合为一个统一的节点。

---

### 3.5 Person 节点与导演/演员关系

#### 3.5.1 导演（Director）

对于每个电影分组：

- 遍历该组的 `Director` 列（去重后）：
  - 为每个 director 名字创建/复用 Person 节点
  - 添加 `DIRECTED` 边：`Person → Movie`

#### 3.5.2 演员（Star Cast）

`Star Cast` 通常是多个名字拼在一起的一段字符串，例如：

- `"Tom CruiseHayley AtwellVing Rhames"`

在脚本中：

- 定义 `split_star_cast(raw)` 函数，对这类字符串进行启发式拆分：
  - 按“小写字母后接大写字母”的位置切开
  - 适当地合并如 `Mc`、`Mac`、`De` 等前缀碎片
- 将每个拆出的姓名作为一个 Person 节点
- 为每个姓名添加 `ACTED_IN` 边：`Person → Movie`

> 拆分规则并不完美，但在没有额外标注的前提下，能较好地自动化构建演员关系。

---

### 3.6 Genre / Certificate 节点与关系

在电影分组内：

- 遍历该组的 `Genre` 值（去重后）：
  - 为每个类型创建/复用 Genre 节点
  - 添加 `HAS_GENRE` 边：`Movie → Genre`

- 遍历该组的 `Certificates` 值（去重后）：
  - 为每个分级创建/复用 Certificate 节点
  - 添加 `HAS_CERTIFICATE` 边：`Movie → Certificate`

---

### 3.7 使用 NetworkX 构建图并导出 GraphML

整体图结构使用：

```python
G = nx.MultiDiGraph()
```

- 每个节点带有：
  - `type` 字段（movie / person / genre / certificate）
  - 以及对应的属性（如 title、year、name 等）
- 每条边带有：
  - `relation` 字段（DIRECTED / ACTED_IN / HAS_GENRE / HAS_CERTIFICATE）

构图完成后：

```python
nx.write_graphml(G, "imdb_kg.graphml")
```

即可生成 GraphML 文件，用于后续查询和可视化。

---

## 4. 使用方式（简单示例）

### 4.1 在 Python / NetworkX 中加载 GraphML

```python
import networkx as nx

G = nx.read_graphml("imdb_kg.graphml")

print("nodes:", G.number_of_nodes())
print("edges:", G.number_of_edges())
```

### 4.2 示例：查询某部电影的相关信息

```python
def find_movie_node(G, title, year=None):
    for n, data in G.nodes(data=True):
        if data.get("type") == "movie" and data.get("title") == title:
            if year is None or int(data.get("year", -1)) == year:
                return n
    return None

def show_movie_context(G, title, year=None):
    movie_id = find_movie_node(G, title, year)
    if movie_id is None:
        print("找不到电影:", title, year)
        return

    data = G.nodes[movie_id]
    print(f"电影: {data.get('title')} ({data.get('year')})")
    print(f"  IMDb Rating: {data.get('imdb_rating')}")
    print(f"  MetaScore:   {data.get('metascore')}")
    print(f"  Duration:    {data.get('duration_minutes')} min")

    directors, actors, genres, certs = set(), set(), set(), set()

    # in_edges: 谁指向这部电影（导演/演员）
    for u, v, edge in G.in_edges(movie_id, data=True):
        rel = edge.get("relation")
        ndata = G.nodes[u]
        if rel == "DIRECTED":
            directors.add(ndata.get("name", u))
        elif rel == "ACTED_IN":
            actors.add(ndata.get("name", u))

    # out_edges: 这部电影指向谁（类型/分级）
    for u, v, edge in G.out_edges(movie_id, data=True):
        rel = edge.get("relation")
        ndata = G.nodes[v]
        if rel == "HAS_GENRE":
            genres.add(ndata.get("name", v))
        elif rel == "HAS_CERTIFICATE":
            certs.add(ndata.get("name", v))

    print("  导演:", ", ".join(sorted(directors)) or "无")
    print("  演员:", ", ".join(sorted(actors)) or "无")
    print("  类型:", ", ".join(sorted(genres)) or "无")
    print("  分级:", ", ".join(sorted(certs)) or "无")

# 示例调用
show_movie_context(G, "Inception", 2010)
```

---

## 5. 后续扩展方向

本项目当前版本是基于**公共字段**的“最小可用图谱”。未来可以考虑：

- 利用各文件独有的字段（海报链接、多类型字段等）丰富 Movie 属性和关系；
- 引入 “DataSource” 节点表示不同来源；
- 加入国家、语言、制作公司、奖项等实体；
- 把演员间的合作次数、类型偏好等统计信息也编码到图中。
