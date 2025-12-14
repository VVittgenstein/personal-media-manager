# 性能 Spike（ACT-009）— 缩略图 / 懒加载 / 万级媒体库

> 目标：用可复现数据验证缩略图生成与前端懒加载策略在“万级库”下的实际表现，并给出默认参数建议与瓶颈分析。

## 1) 可复现测试集（MediaRoot）

使用脚本生成（不提交生成出来的测试集）：

```bash
python3 perf/test/generate_media_root.py --out /tmp/ppm-media-root-10k --force
```

默认数据形状：
- 200 个相册（`Albums/Album-0000..0199`），每相册 40 张图（合计 8000）
- MediaRoot 根目录 2000 张散图（合计 10000）
- 500 个 `Videos/*.mp4`（占位文件，用于索引规模压测）
- 500 个 `Others/*.txt`

额外建议（前端最坏情况）：散图视图 10k（无相册）：

```bash
python3 perf/test/generate_media_root.py --out /tmp/ppm-media-root-scattered-10k --force --albums 0 --scattered-images 10000 --videos 0 --others 0
```

## 2) 硬件基线（本次测量环境）

- OS: `Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.39`
- CPU: `AMD Ryzen 9 9950X3D 16-Core Processor`（`os.cpu_count()=32`）
- RAM: `46.9 GB`
- Python: `3.12.3`

> Windows 目标机建议记录：CPU 型号/核数、内存、磁盘类型（SSD/HDD）、MediaRoot 所在盘符与文件系统；并尽量固定“测试集路径与规模”。

## 3) 压测方法

脚本执行（会输出 JSON，含耗时与内存 RSS 快照）：

```bash
python3 perf/test/run_perf_spike.py --media-root /tmp/ppm-media-root-10k --out /tmp/ppm-perf-10k.json
```

测量项：
- Index：`scan_inventory + classify_inventory`（`build_media_index`）
- Thumbnails：`/api/thumb` 等价路径（并发 `ensure_thumb`）+ `/api/thumbs/warm` 等价路径（`enqueue_many + queue.join`）
- Album covers：`ensure_cover`（2x2 封面拼图）
- Video mosaics：若 `ffmpeg` 不在 PATH，则跳过

## 4) 结果（本机 / 10k 图 / sample=2000 图生成）

### 4.1 索引（10k 图 + 500 video + 500 other）

`build_media_index`（repeats=3）：
- p50: `~45.5ms`
- p95: `~55.1ms`
- RSS: `27.5MB → 36.2MB`

### 4.2 缩略图（sample_images=2000）

| thumb_size | thumb_workers | direct_cold (items/s) | batch_cold (items/s) | 备注 |
|---:|---:|---:|---:|---|
| 240 | 2 | ~166 | ~181 | 更快但缩略图更小 |
| 320 | 2 | ~148 | ~161 | 当前默认参数组合 |
| 320 | 4 | ~227 | ~271 | 性价比最明显提升 |
| 320 | 8 | ~257 | ~236 | 继续加并发收益变小/波动变大 |
| 480 | 2 | ~99 | ~106 | 更清晰但明显变慢 |

补充：warm cache 下 direct 路径可达 `~1250 items/s`（主要为 etag 计算 + exists 检查）。

### 4.3 相册封面（200 albums）

- `ensure_cover`：`~27.7 albums/s`（thumb_size=320, q=82）

### 4.4 视频拼图

本次环境 `ffmpeg/ffprobe` 不在 PATH：跳过（`Video mosaics skipped`）。

## 5) 瓶颈结论与参数建议

### 后端缩略图参数建议（MVP 默认）

- `thumb_size`：建议保持 `320`（240 更快但观感下降；480 成本显著上升）。
- `thumb_quality`：`80~85` 区间均可；本次保持 `82`。
- `thumb_workers`：
  - 默认值继续保守（`2`）能降低“首次打开大相册时 CPU 突刺”风险；
  - 对 8 核以上机器，推荐用户手动调到 `4`（本次测量 direct_cold 约 +53% 吞吐）。

### 前端（首屏/滚动）结论（基于实现形态）

- 当前实现已具备：
  - `IntersectionObserver` + `img[loading=lazy]`（只推迟图片请求/解码）。
- 主要风险点：
  - 对于“散图/相册内图片”视图，`renderThumbGrid` 会一次性创建 N 个 tile DOM；N 达到几千以上时，DOM 构建/布局/样式计算会成为滚动瓶颈（与是否懒加载网络请求无关）。
- 建议（按优先级）：
  1) 增量渲染（chunked render：每帧/空闲时间渲染一部分，避免长任务卡住主线程）
  2) 超大列表引入虚拟列表/窗口化（只保留视窗附近 DOM）
  3) 样式层面尝试 `content-visibility: auto; contain-intrinsic-size: ...` 降低离屏成本（浏览器支持差异需验证）
