# perf/test

本目录用于可复现的“万级媒体库”性能 Spike（不提交生成出来的测试集）。

## 1) 生成测试集（MediaRoot）

```bash
python3 perf/test/generate_media_root.py --out /tmp/ppm-media-root --force
```

依赖：`Pillow`（建议在虚拟环境内安装：`python3 -m pip install -r backend/requirements.txt`）。

默认会生成：
- 200 个相册目录（`Albums/Album-0000..`），每相册 40 张图（合计 8000）
- MediaRoot 根目录 2000 张散图（合计 10000）
- 500 个 dummy `Videos/*.mp4`
- 500 个 `Others/*.txt`

> 生成的视频文件是“占位文件”，用于索引/列表规模压测；如要跑 `video-mosaic`，请自行用 ffmpeg 生成可解码的视频样例。

## 2) 执行压测并输出 JSON

```bash
python3 perf/test/run_perf_spike.py --media-root /tmp/ppm-media-root --out /tmp/ppm-perf.json
```

可调参数（示例）：

```bash
python3 perf/test/run_perf_spike.py \
  --media-root /tmp/ppm-media-root \
  --thumb-size 320 --thumb-quality 82 --thumb-workers 2 \
  --sample-images 2000 --repeats 3 \
  --out /tmp/ppm-perf.json
```
