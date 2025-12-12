# 媒体分类规则（Album / Scattered / Videos / Games / Others）

本规则为 ACT-001 索引与视图的产品口径，后端扫描与前端展示均应遵循。

## 1. 基本范围

- 仅扫描与展示 `MediaRoot` 及其子路径；任何越界路径一律拒绝（安全沙箱）。
- 分类与索引内所有路径字段均为 **MediaRoot 内相对路径**。
- 默认忽略保留目录：`MediaRoot/_trash/`（回收站）；其内容不计入 Images/Scattered/Videos/Games/Others 的扫描与索引。

## 2. 文件类型与默认扩展名映射

### 2.1 Images（图片）

默认图片扩展名（不区分大小写，统一转小写比较）：

`[".jpg",".jpeg",".png",".gif",".bmp",".webp",".tif",".tiff",".heic",".avif",".svg"]`

### 2.2 Videos（视频）

默认视频扩展名：

`[".mp4",".mkv",".mov",".avi",".wmv",".flv",".webm",".m4v",".mpg",".mpeg",".ts"]`

### 2.3 Games（游戏）

MVP 以“可执行入口文件”为主进行粗粒度识别：

默认游戏扩展名：

`[".exe",".bat",".cmd",".com",".lnk",".url"]`

> 现阶段不做“游戏文件夹”深度识别；后续若需要，可增加目录级规则（例如包含可执行文件且无图片/视频的目录作为 game-folder）。

### 2.4 Others（其他）

除 Images / Videos / Games 外的所有文件归为 Others。

## 3. 相册（Album）识别规则

相册对应 **叶子图片目录**（决策 D-20251212-album-leaf-rule）：

给定任一目录 `D`（相对路径）：

1. `D` **直接包含 ≥1 张图片文件**（Images 扩展名）。
2. `D` 不存在“包含图片的子目录”。  
   - 若 `D` 没有子目录，满足本条件。  
   - 若 `D` 有子目录，但这些子目录及其后代 **都不包含图片**，仍满足本条件。
   - 子目录仅包含视频/游戏/其他文件时，不影响 Album 判定。

满足 1&2 的 `D` 记为一个 Album；其父目录仅作为容器，不再重复计为 Album。

**示例**

```
MediaRoot/
  旅行/
    海边/          (含图片)   -> Album: 旅行/海边
    美食/          (含图片)   -> Album: 旅行/美食
  临时/            (含图片 + 有子目录但子目录无图片) -> Album: 临时
    raw/           (无图片)
```

## 4. 散图（Scattered Images）识别规则

散图定义（决策 D-20251212-scattered-definition）：

> MediaRoot 下所有 **不在任何 Album 路径内** 的图片文件。

具体判定：

- 若图片文件的 `folder_rel_path` 等于某个 `Album.rel_path`，则属于该相册。
- 若图片文件位于某个 Album 的子路径内（理论上叶子相册不再包含图片子目录，但实现上按前缀匹配更稳妥），仍归属该 Album。
- 否则归为 Scattered。

**示例**

```
MediaRoot/
  封面.jpg               -> Scattered
  旅行/
    预览.png             -> Scattered（父目录不是 Album，且不在任何 Album 路径内）
    海边/1.jpg           -> Album: 旅行/海边
```

## 5. 扁平聚合规则

- Videos 视图：聚合 MediaRoot 内所有 `VideoFile`，与其目录层级无关。
- Games 视图：聚合 `OtherFile.category="game"` 的条目，目录层级不影响展示。
- Others 视图：聚合 `OtherFile.category="other"` 的条目。

## 6. 扩展机制

默认扩展名可通过配置覆盖或追加。建议配置文件：

`config/media-types.json`

```json
{
  "images": [".jpg", ".jpeg", "..."],
  "videos": [".mp4", ".mkv", "..."],
  "games":  [".exe", ".bat", "..."]
}
```

后端启动时读取该文件：

- 若缺失则使用默认映射。
- 若存在则以配置为准（可约定“完全覆盖”或“在默认基础上追加”，实现时需固定一种策略并记录在代码注释/README）。
