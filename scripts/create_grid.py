"""
将裁切后的单字图片拼成缩略图网格，方便批量视觉识别。

用法:
    python create_grid.py <src_dir> [cols]

参数:
    src_dir - 包含 pos_xxxx.jpg 文件的目录
    cols    - 每行显示几张（默认 15）

输出:
    src_dir/grid_overview.jpg
"""

import sys
from pathlib import Path
from PIL import Image


def create_grid(src_dir, cols=15, thumb_size=(128, 128)):
    src_path = Path(src_dir)
    files = sorted(src_path.glob("pos_*.jpg"))
    if not files:
        print("No pos_*.jpg files found")
        return

    n = len(files)
    rows = (n + cols - 1) // cols
    grid_w = cols * thumb_size[0] + (cols + 1) * 4
    grid_h = rows * thumb_size[1] + (rows + 1) * 4

    grid = Image.new("RGB", (grid_w, grid_h), (240, 240, 240))

    for idx, fpath in enumerate(files):
        img = Image.open(str(fpath)).convert("RGB")
        img.thumbnail(thumb_size, Image.LANCZOS)

        row = idx // cols
        col = idx % cols
        x = col * thumb_size[0] + (col + 1) * 4 + (thumb_size[0] - img.width) // 2
        y = row * thumb_size[1] + (row + 1) * 4 + (thumb_size[1] - img.height) // 2
        grid.paste(img, (x, y))

    out_path = src_path / "grid_overview.jpg"
    grid.save(str(out_path), "JPEG", quality=90)
    print(f"Grid saved: {out_path} ({n} images, {rows} rows x {cols} cols)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python create_grid.py <src_dir> [cols]")
        sys.exit(1)
    src_dir = sys.argv[1]
    cols = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    create_grid(src_dir, cols)
