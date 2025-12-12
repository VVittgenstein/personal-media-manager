# 索引数据模型（Index Schema）

本索引用于支撑 **Images/Scattered/Videos/Games/Others** 视图、全局搜索、以及安全文件操作（删除/移动/归档）。  
索引只覆盖用户指定的 `MediaRoot` 沙箱范围；所有路径字段 **必须为 MediaRoot 内相对路径**。

## 1. 路径与 ID 约定

- `rel_path`：相对 `MediaRoot` 的路径，不以 `/` 或盘符开头。
  - 统一使用 `/` 作为分隔符（即便在 Windows 上）。
  - 根目录用空字符串 `""` 表示。
  - 任何包含 `..`、盘符（如 `C:\`）、UNC（如 `\\server\share`）的输入均视为非法，扫描/操作时直接拒绝。
- `id`：稳定主键，建议用 `rel_path` 的规范化结果做 hash（例如 `sha1(rel_path)`），保证跨进程/跨次扫描一致。

## 2. 实体定义

### 2.1 Folder（目录）

表示 MediaRoot 内的一个真实目录（含根目录）。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 目录主键（hash(rel_path)） |
| rel_path | string | 目录相对路径 |
| name | string | 目录名（basename） |
| parent_rel_path | string \| null | 父目录相对路径；根目录为 null |
| depth | number | 深度（根=0） |
| child_folder_rel_paths | string[] | 直接子目录相对路径列表 |
| image_count_direct | number | 该目录**直接**包含的图片数量 |
| video_count_direct | number | 该目录直接包含的视频数量 |
| other_count_direct | number | 该目录直接包含的其他文件数量（含 game/other） |
| has_image_descendant | boolean | 任一子孙目录是否包含图片（用于相册叶子判定） |
| mtime_ms | number | 目录最后修改时间（毫秒） |

> `has_image_descendant` 由扫描阶段自底向上汇总生成。

### 2.2 Album（相册）

Album 是 Images 视图的逻辑实体，对应一个“叶子图片目录”。  
每个 Album 与一个 Folder 一一对应（相同 `rel_path` 与 `id`）。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 同 Folder.id |
| rel_path | string | 同 Folder.rel_path |
| title | string | UI 展示名，推荐为 rel_path（如 `旅行/2024/海边`） |
| image_rel_paths | string[] | 该相册内图片相对路径（可延迟加载） |
| image_count | number | 图片数量 |
| cover_image_rel_paths | string[] | 参与 2×2 封面拼图的 1~4 张图片相对路径 |
| mtime_ms | number | 相册目录最后修改时间 |

### 2.3 ImageFile（图片文件）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 文件主键（hash(rel_path)） |
| rel_path | string | 图片相对路径 |
| folder_rel_path | string | 父目录相对路径 |
| album_rel_path | string \| null | 所属相册相对路径；散图为 null |
| ext | string | 小写扩展名（如 `.jpg`） |
| size_bytes | number | 文件大小 |
| mtime_ms | number | 最后修改时间 |
| width | number \| null | 像素宽度（可懒解析） |
| height | number \| null | 像素高度（可懒解析） |
| thumb_rel_path | string \| null | 缩略图缓存的相对路径（派生数据） |

### 2.4 VideoFile（视频文件）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 文件主键（hash(rel_path)） |
| rel_path | string | 视频相对路径 |
| folder_rel_path | string | 父目录相对路径 |
| ext | string | 小写扩展名（如 `.mp4`） |
| size_bytes | number | 文件大小 |
| mtime_ms | number | 最后修改时间 |
| duration_ms | number \| null | 时长（可懒解析） |
| width | number \| null | 像素宽度（可懒解析） |
| height | number \| null | 像素高度（可懒解析） |
| preview_rel_path | string \| null | 2×2 预览图缓存相对路径（派生数据） |

### 2.5 OtherFile（其他文件 / 游戏）

用于承载非图片/视频的文件；其中可细分出 Games。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 文件主键（hash(rel_path)） |
| rel_path | string | 文件相对路径 |
| folder_rel_path | string | 父目录相对路径 |
| ext | string | 小写扩展名（如 `.zip`） |
| size_bytes | number | 文件大小 |
| mtime_ms | number | 最后修改时间 |
| category | `"game"` \| `"other"` | 归类结果 |

### 2.6 OperationLog（操作日志）

用于审计 delete/move/archive/restore 等变更操作。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 日志主键（uuid） |
| ts_ms | number | 发生时间（毫秒） |
| op | `"delete"` \| `"move"` \| `"archive"` \| `"restore"` \| `"purge"` | 操作类型 |
| src_rel_path | string | 源路径相对 MediaRoot |
| dst_rel_path | string \| null | 目标路径（移动/恢复） |
| is_dir | boolean | 是否目录操作 |
| success | boolean | 是否成功 |
| error | string \| null | 失败原因（若有） |

## 3. 关系与派生

- `Folder` 形成一棵目录树；`Album` 是 `Folder` 的子集。
- `ImageFile.album_rel_path` 指向其所属 `Album.rel_path`；若为空则属于散图集合。
- `VideoFile` 与 `OtherFile` 只做扁平聚合，不依赖目录层级展示。
- 缩略图/封面/预览图为派生缓存，推荐存放在应用目录（非 MediaRoot）并以 `rel_path` hash 命名。

