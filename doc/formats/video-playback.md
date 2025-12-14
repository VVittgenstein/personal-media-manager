# 视频格式支持与“不支持提示”策略

更新时间：2025-12-14

## 1) 背景

- 本项目通过浏览器 HTML5 `<video>` 播放视频；“是否可播放”取决于 **封装（container）+ 编码（codec）+ 浏览器/系统解码能力**。
- 后端索引默认把这些扩展名归类为视频（`backend/indexing/media_types.py`）：
  - `.mp4` `.m4v` `.mov` `.webm` `.mkv` `.avi` `.wmv` `.flv` `.mpeg` `.mpg` `.ts`
- 其中不少封装在多数浏览器里不可直接播放（或仅部分编码可播放），因此需要在播放失败时给出明确的“外部打开/转码”提示。

## 2) 运行时检测（前端）

检测由前端 Overlay 在打开视频时完成（`frontend/spa/app.js`）。

### 2.1 预判（canPlayType）

- 对当前文件扩展名映射一组 MIME candidates，并用 `HTMLVideoElement.canPlayType(...)` 探测。
- 若所有候选均返回空串（`""`），视为“当前浏览器大概率不支持”，提前展示提示。
- 若返回 `maybe/probably`，仍可能因实际编码不匹配而失败（例如 `.mp4` 内是 HEVC/H.265、AV1 等）。

### 2.2 兜底（实际加载错误）

- 监听 `video.error`：
  - `MEDIA_ERR_SRC_NOT_SUPPORTED`：封装/编码不支持
  - `MEDIA_ERR_DECODE`：解码失败（可能是编码不支持或文件损坏）
- 失败时展示同一提示与操作入口。

## 3) 已实现的提示策略（Overlay）

当判定“无法播放/大概率不支持”时，Overlay 会展示：

- **新标签打开**：打开媒体 URL（有时浏览器会直接触发下载）
- **下载文件**：下载到本地后用系统默认播放器/VLC 打开
- **复制链接**：复制媒体 URL，可粘贴到 VLC → “打开网络串流”
- **复制转码命令**：提供 ffmpeg 转码到更通用格式的命令模板

## 4) 扩展名 → MIME candidates（用于 canPlayType 探测）

> 说明：这只是“探测用候选”，最终仍以运行时加载结果为准。

| 扩展名 | MIME candidates（示例） | 备注 |
|---|---|---|
| `.mp4` / `.m4v` | `video/mp4`；`video/mp4; codecs="avc1.42E01E, mp4a.40.2"` | 通用推荐：H.264/AAC；若实际为 HEVC/H.265/AV1 等可能失败 |
| `.mov` | `video/quicktime`；`video/mp4` | 取决于封装内编码；常见 H.264 的 `.mov` 在部分浏览器可播放 |
| `.webm` | `video/webm`；`video/webm; codecs="vp9, opus"` | 多数 Chromium 可播放；部分平台/浏览器可能不支持 WebM |
| `.mkv` | `video/x-matroska` | 多数浏览器不支持 |
| `.avi` | `video/x-msvideo` | 多数浏览器不支持 |
| `.flv` | `video/x-flv` | 多数浏览器不支持 |
| `.wmv` | `video/x-ms-wmv` | 多数浏览器不支持 |
| `.mpg` / `.mpeg` | `video/mpeg` | 浏览器支持差异较大 |
| `.ts` | `video/mp2t` | 浏览器支持差异较大（常见于 HLS 场景，直链不一定可播） |

## 5) 转码建议（ffmpeg）

### 5.1 转 MP4（优先推荐）

`ffmpeg -i "<input>" -c:v libx264 -c:a aac -movflags +faststart "<output>.mp4"`

### 5.2 转 WebM（可选）

`ffmpeg -i "<input>" -c:v libvpx-vp9 -crf 32 -b:v 0 -c:a libopus "<output>.webm"`

## 6) “已验证支持范围”的定义

- 本项目对“支持/不支持”的判定以 **当前浏览器** 的 `canPlayType` 探测 + 实际加载结果为准。
- Overlay 会展示 `canPlayType` 探测结果（MIME → maybe/probably/""），方便在不同浏览器/设备上快速自证与排查。

