"""
extract_chars_v44.py - v44 升级版

核心改进（vs v34）：
1. tight crop：使用 Otsu 阈值（自适应），不再用固定 235 + CLAHE
2. 字符 + 10px 外扩 → 扩成方形 (max char dim + 2*pad)
3. 方形画布从原图取真实背景（不是 paper_color 也不是纯白）
4. 字符居中放 512x512，100% 填充
5. 边缘越界时用边像素平铺
6. 用 cv2.imencode + buf.tofile 解决中文路径写入问题
"""
import os
import json
import cv2
import numpy as np
from pathlib import Path
from PIL import Image
import sys


# === 可配置参数 ===
CELL_SIZE = 512
EXPAND_PX = 10           # 字符四周外扩像素
N_COLS = 3               # 竖排列数（从右到左）
EXCLUDE_FILES = set()    # 要排除的文件名（不含扩展名）


def read_image(path):
    """读取含 Unicode 路径的图片（中文路径兼容）"""
    img_data = np.fromfile(str(path), dtype=np.uint8)
    return cv2.imdecode(img_data, cv2.IMREAD_COLOR)


def write_image(path, img, quality=95):
    """写入图片，支持中文路径"""
    ext = os.path.splitext(path)[1]
    ok, buf = cv2.imencode(ext, img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if ok:
        buf.tofile(path)
    return ok


def is_seal(bgr_img):
    """判断是否为印章（红色印章）"""
    hsv = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    red = ((h < 10) | (h > 160)) & (s > 50) & (v > 50)
    return red.sum() / red.size > 0.03


def is_background(bgr_img, ink_threshold=0.005, std_threshold=20):
    """判断是否为背景纸图（无效图片）"""
    g = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
    if (g < 100).sum() / g.size < ink_threshold:
        return True
    if g.std() < std_threshold:
        return True
    return False


def get_col_splits(img, n_cols=N_COLS):
    """竖排三列（从右到左）"""
    h, w = img.shape[:2]
    col_w = w // n_cols
    return [(i * col_w, (i + 1) * col_w if i < n_cols - 1 else w)
            for i in range(n_cols)][::-1]


def estimate_char_height(col_img):
    """估算单字高度（用于连通域过滤）"""
    gray = cv2.cvtColor(col_img, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    vert_proj = bw.sum(axis=0)
    if vert_proj.max() == 0:
        return col_img.shape[1] * 1.2
    threshold = vert_proj.max() * 0.1
    ink_cols = np.where(vert_proj > threshold)[0]
    if len(ink_cols) == 0:
        return col_img.shape[1] * 1.2
    return (ink_cols[-1] - ink_cols[0] + 1) * 1.2


def detect_char_regions(col_img, close_kernel=(5, 5)):
    """连通域检测 + Y 坐标聚类合并"""
    h, w = col_img.shape[:2]
    gray = cv2.cvtColor(col_img, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    if close_kernel[0] > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, close_kernel)
        bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
    est_char_h = estimate_char_height(col_img)
    min_area = h * w * 0.0003
    min_height = est_char_h * 0.08

    comps = []
    for i in range(1, num_labels):
        x, y, cw, ch, area = stats[i]
        if area < min_area or ch < min_height:
            continue
        comps.append({
            'x': x, 'y': y, 'w': cw, 'h': ch,
            'x2': x + cw, 'y2': y + ch,
            'area': area
        })

    if not comps:
        return []

    comps.sort(key=lambda c: (c['y'] + c['y2']) / 2)

    # Y 聚类合并（保留小笔画）
    groups = []
    for comp in comps:
        merged = False
        for g in groups:
            last = g[-1]
            y_gap = max(0, max(comp['y'], last['y']) - min(comp['y2'], last['y2']))
            y_overlap = max(0, min(comp['y2'], last['y2']) - max(comp['y'], last['y']))
            min_h = min(comp['h'], last['h'])
            if y_overlap > min_h * 0.05 or y_gap < min_h * 0.20:
                g.append(comp)
                merged = True
                break
        if not merged:
            groups.append([comp])

    result = []
    for g in groups:
        x1 = min(c['x'] for c in g)
        y1 = min(c['y'] for c in g)
        x2 = max(c['x2'] for c in g)
        y2 = max(c['y2'] for c in g)
        result.append((x1, y1, x2, y2, sum(c['area'] for c in g)))
    result.sort(key=lambda r: (r[1] + r[3]) / 2)
    return result


def extract_from_full(full_img, char_box_in_col, col_box, expand_px=EXPAND_PX):
    """
    v44 核心：从整张原图取字符 + 周围背景，扩成方形

    参数：
      full_img: 整张原图
      char_box_in_col: 字符在列内的 (x1, y1, x2, y2)
      col_box: 列在全图中的 (cx0, cx1)
      expand_px: 字符四周外扩像素
    """
    cx0, cx1 = col_box
    x1, y1, x2, y2 = char_box_in_col
    H, W = full_img.shape[:2]
    char_w = x2 - x1
    char_h = y2 - y1
    side = max(char_h, char_w) + 2 * expand_px

    # 字符在全图中的位置
    abs_cx0 = cx0 + x1
    abs_cx1 = cx0 + x2
    abs_cy0 = y1
    abs_cy1 = y2
    center_x = (abs_cx0 + abs_cx1) // 2
    center_y = (abs_cy0 + abs_cy1) // 2

    # 以字符为中心取 side x side 区域
    half = side // 2
    ext_x0 = center_x - half
    ext_x1 = center_x + half + (side % 2)
    ext_y0 = center_y - half
    ext_y1 = center_y + half + (side % 2)

    # 实际可取范围
    src_x0 = max(0, ext_x0)
    src_x1 = min(W, ext_x1)
    src_y0 = max(0, ext_y0)
    src_y1 = min(H, ext_y1)

    canvas = np.ones((side, side, 3), dtype=np.uint8) * 255
    dst_x0 = src_x0 - ext_x0
    dst_y0 = src_y0 - ext_y0
    canvas[dst_y0:dst_y0 + (src_y1 - src_y0),
           dst_x0:dst_x0 + (src_x1 - src_x0)] = full_img[src_y0:src_y1, src_x0:src_x1]

    # 越界部分用边像素平铺
    if ext_y0 < 0:
        top_row = full_img[0:1, src_x0:src_x1]
        for dy in range(-ext_y0):
            canvas[dy:dy + 1, dst_x0:dst_x0 + (src_x1 - src_x0)] = top_row
    if ext_y1 > H:
        bot_row = full_img[H - 1:H, src_x0:src_x1]
        start_y = dst_y0 + (src_y1 - src_y0)
        for dy in range(ext_y1 - H):
            canvas[start_y + dy:start_y + dy + 1,
                   dst_x0:dst_x0 + (src_x1 - src_x0)] = bot_row
    if ext_x0 < 0:
        left_col = full_img[src_y0:src_y1, 0:1]
        for dx in range(-ext_x0):
            canvas[dst_y0:dst_y0 + (src_y1 - src_y0), dx:dx + 1] = left_col
    if ext_x1 > W:
        right_col = full_img[src_y0:src_y1, W - 1:W]
        start_x = dst_x0 + (src_x1 - src_x0)
        for dx in range(ext_x1 - W):
            canvas[dst_y0:dst_y0 + (src_y1 - src_y0),
                   start_x + dx:start_x + dx + 1] = right_col

    return canvas


def make_square(char_img, size=CELL_SIZE, fill=1.0):
    """居中放固定尺寸画布"""
    h, w = char_img.shape[:2]
    canvas = np.ones((size, size, 3), dtype=np.uint8) * 255
    target = int(size * fill)
    scale = min(target / h, target / w)
    nh = max(int(h * scale), 1)
    nw = max(int(w * scale), 1)
    interp = cv2.INTER_CUBIC if nh > h else cv2.INTER_AREA
    resized = cv2.resize(char_img, (nw, nh), interpolation=interp)
    y = (size - nh) // 2
    x = (size - nw) // 2
    canvas[y:y + nh, x:x + nw] = resized
    return canvas


def process_all_images(src_dir, out_dir, n_cols=N_COLS, cell_size=CELL_SIZE, expand_px=EXPAND_PX):
    src_dir = Path(src_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(exist_ok=True)

    meta_path = out_dir.parent / f"cell_positions_{out_dir.name}.json"

    jpg_files = sorted([
        f for f in src_dir.glob("*.jpg")
        if f.stem not in EXCLUDE_FILES
    ])
    print(f"Found {len(jpg_files)} source images")

    for f in out_dir.glob("*.jpg"):
        f.unlink()

    global_idx = 0
    all_meta = []
    skipped_seals = 0
    skipped_bg = 0

    for img_path in jpg_files:
        stem = img_path.stem
        print(f"\n[{stem}] Processing...")

        try:
            img = read_image(img_path)
        except Exception as e:
            print(f"  FAIL: {e}")
            continue

        col_splits = get_col_splits(img, n_cols)

        for ci, (cx0, cx1) in enumerate(col_splits):
            col_img = img[:, cx0:cx1]
            char_boxes = detect_char_regions(col_img, (5, 5))
            print(f"  Col {ci + 1}: {len(char_boxes)} chars")

            for ri, (x1, y1, x2, y2, _) in enumerate(char_boxes):
                raw_cell = col_img[y1:y2, x1:x2]

                if is_seal(raw_cell):
                    skipped_seals += 1
                    print(f"    Skip seal at row {ri + 1}")
                    continue

                # v44: 从整张原图取字符 + 周围背景，扩成方形
                square = extract_from_full(img, (x1, y1, x2, y2), (cx0, cx1), expand_px=expand_px)

                if is_background(square):
                    skipped_bg += 1
                    print(f"    Skip background at row {ri + 1}")
                    continue

                final = make_square(square, size=cell_size, fill=1.0)

                global_idx += 1
                fname = f"pos_{global_idx:04d}.jpg"
                out_path = out_dir / fname
                write_image(str(out_path), final)

                all_meta.append({
                    "pos": global_idx,
                    "img_file": stem,
                    "col": ci + 1,
                    "row": ri + 1,
                    "col_range": [int(cx0), int(cx1)],
                    "row_range": [int(y1), int(y2)],
                    "char_range": [int(x1), int(x2)],
                })

    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(all_meta, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 50}")
    print(f"DONE: {global_idx} cells extracted (v44)")
    print(f"Skipped seals: {skipped_seals}")
    print(f"Skipped background: {skipped_bg}")
    print(f"Output dir: {out_dir}")
    print(f"Metadata:   {meta_path}")
    return all_meta


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_chars_v44.py <图片目录> [列数] [输出尺寸] [外扩像素]")
        print("Example: python extract_chars_v44.py ./书法图片/ 3 512 10")
        sys.exit(1)

    src_dir = sys.argv[1]
    n_cols = int(sys.argv[2]) if len(sys.argv) > 2 else N_COLS
    cell_size = int(sys.argv[3]) if len(sys.argv) > 3 else CELL_SIZE
    expand_px = int(sys.argv[4]) if len(sys.argv) > 4 else EXPAND_PX

    src_path = Path(src_dir)
    out_dir = src_path / f"单字_v{cell_size}_v44"

    process_all_images(src_dir, out_dir, n_cols, cell_size, expand_px)
