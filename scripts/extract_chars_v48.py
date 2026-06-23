"""
extract_chars_v48.py - v48 升级版

核心改进（vs v44）：
1. 增强印章检测：增加形状宽高比检查，减少漏检
2. 小孤立笔画归并：上方小点（如"生"、"空"的头部）自动归并到下方字符
3. 更好的后处理逻辑
"""
import os
import json
import cv2
import numpy as np
from pathlib import Path
import sys


# === 可配置参数 ===
CELL_SIZE = 512
EXPAND_PX = 10           # 字符四周外扩像素
N_COLS = 3               # 竖排列数（从右到左）
EXCLUDE_FILES = set()     # 要排除的文件名（不含扩展名）
SMALL_THR = 100          # 小笔画阈值（宽或高 < 100px）


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
    """判断是否为印章（红色印章 + 形状检测）"""
    hsv = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    red = ((h < 10) | (h > 160)) & (s > 80) & (v > 50)
    red_ratio = red.sum() / red.size
    if red_ratio < 0.02:
        return False
    # 形状检测：印章通常是方形/圆形，宽高比接近 1
    red_u8 = red.astype(np.uint8) * 255
    n, _, st, _ = cv2.connectedComponentsWithStats(red_u8, connectivity=8)
    if n < 2:
        return red_ratio > 0.10
    areas = st[1:, cv2.CC_STAT_AREA]
    if len(areas) == 0 or max(areas) < 50:
        return red_ratio > 0.10
    max_i = 1 + areas.argmax()
    cw = st[max_i, cv2.CC_STAT_WIDTH]
    ch = st[max_i, cv2.CC_STAT_HEIGHT]
    if cw < 5 or ch < 5:
        return False
    aspect = max(cw, ch) / min(cw, ch)
    if aspect < 3.0:
        return True
    return red_ratio > 0.10


def is_background(bgr_img, ink_threshold=0.005, std_threshold=20):
    """判断是否为背景纸图（无效图片）"""
    g = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
    if (g < 100).sum() / g.size < ink_threshold:
        return True
    if g.std() < std_threshold:
        return True
    return False


def get_col_splits(img, n_cols=N_COLS):
    """竖排分列（从右到左）"""
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


def detect_char_regions_v48(col_img, close_kernel=(5, 5), small_thr=SMALL_THR):
    """
    v48 字符合并策略：
    1. v34 完整合并（宽松 Y 聚类）
    2. 后处理: 小孤立点归到下方字符
    """
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
            'cx': x + cw // 2, 'cy': y + ch // 2,
            'area': area
        })

    if not comps:
        return []

    comps.sort(key=lambda c: c['cy'])

    # v34 宽松 Y 聚类合并
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

    def group_bbox(g):
        x1 = min(c['x'] for c in g)
        y1 = min(c['y'] for c in g)
        x2 = max(c['x2'] for c in g)
        y2 = max(c['y2'] for c in g)
        return x1, y1, x2, y2

    # 后处理: 小孤立点归到下方字符
    bboxes = [group_bbox(g) for g in groups]
    cys = [(b[1] + b[3]) // 2 for b in bboxes]

    to_remove = set()
    for i in range(len(groups) - 1):
        if i in to_remove:
            continue
        x1, y1, x2, y2 = bboxes[i]
        gw, gh = x2 - x1, y2 - y1
        # 找 i 之后的第一个 "big" group
        for j in range(i + 1, len(groups)):
            if j in to_remove:
                continue
            bx1, by1, bx2, by2 = bboxes[j]
            bj_w, bj_h = bx2 - bx1, by2 - by1
            # 当前 group 是小 (宽<small_thr 且 高<small_thr)
            if gw < small_thr and gh < small_thr:
                # 下方 group 是 big → 归到下方
                if bj_w >= small_thr or bj_h >= small_thr:
                    # 检查 y 距离
                    if i > 0 and i - 1 not in to_remove:
                        d_up = cys[i] - (bboxes[i-1][1] + bboxes[i-1][3]) // 2
                        d_down = (by1 + by2) // 2 - cys[i]
                        if d_down <= d_up:
                            groups[j] = groups[j] + groups[i]
                            bboxes[j] = group_bbox(groups[j])
                            cys[j] = (bboxes[j][1] + bboxes[j][3]) // 2
                            to_remove.add(i)
                            break
                        else:
                            break
                    else:
                        # i 是第一个 group, 强制归下
                        groups[j] = groups[j] + groups[i]
                        bboxes[j] = group_bbox(groups[j])
                        cys[j] = (bboxes[j][1] + bboxes[j][3]) // 2
                        to_remove.add(i)
                        break
                else:
                    continue
            else:
                break

    # 移除已归并的 group
    final_groups = [g for i, g in enumerate(groups) if i not in to_remove]

    result = []
    for g in final_groups:
        x1 = min(c['x'] for c in g)
        y1 = min(c['y'] for c in g)
        x2 = max(c['x2'] for c in g)
        y2 = max(c['y2'] for c in g)
        result.append((x1, y1, x2, y2, sum(c['area'] for c in g)))
    result.sort(key=lambda r: (r[1] + r[3]) / 2)
    return result


def extract_from_full(full_img, char_box_in_col, col_box, expand_px=EXPAND_PX):
    """
    v44/v48 核心：从整张原图取字符 + 周围背景，扩成方形
    """
    cx0, cx1 = col_box
    x1, y1, x2, y2 = char_box_in_col
    H, W = full_img.shape[:2]
    char_w = x2 - x1
    char_h = y2 - y1
    side = max(char_h, char_w) + 2 * expand_px

    abs_cx0 = cx0 + x1
    abs_cx1 = cx0 + x2
    abs_cy0 = y1
    abs_cy1 = y2
    center_x = (abs_cx0 + abs_cx1) // 2
    center_y = (abs_cy0 + abs_cy1) // 2

    half = side // 2
    ext_x0 = center_x - half
    ext_x1 = center_x + half + (side % 2)
    ext_y0 = center_y - half
    ext_y1 = center_y + half + (side % 2)

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


def process_all_images(src_dir, out_dir, n_cols=N_COLS, cell_size=CELL_SIZE,
                       expand_px=EXPAND_PX, small_thr=SMALL_THR):
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
            char_boxes = detect_char_regions_v48(col_img, (5, 5), small_thr)
            print(f"  Col {ci + 1}: {len(char_boxes)} chars")

            for ri, (x1, y1, x2, y2, _) in enumerate(char_boxes):
                raw_cell = col_img[y1:y2, x1:x2]

                if is_seal(raw_cell):
                    skipped_seals += 1
                    print(f"    Skip seal at row {ri + 1}")
                    continue

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
                    "w": int(x2 - x1),
                    "h": int(y2 - y1),
                })

    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(all_meta, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 50}")
    print(f"DONE: {global_idx} cells extracted (v48)")
    print(f"Skipped seals: {skipped_seals}")
    print(f"Skipped background: {skipped_bg}")
    print(f"Output dir: {out_dir}")
    print(f"Metadata:   {meta_path}")
    return all_meta


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_chars_v48.py <图片目录> [列数] [输出尺寸] [外扩像素] [小笔画阈值]")
        print("Example: python extract_chars_v48.py ./书法图片/ 3 512 10 100")
        sys.exit(1)

    src_dir = sys.argv[1]
    n_cols = int(sys.argv[2]) if len(sys.argv) > 2 else N_COLS
    cell_size = int(sys.argv[3]) if len(sys.argv) > 3 else CELL_SIZE
    expand_px = int(sys.argv[4]) if len(sys.argv) > 4 else EXPAND_PX
    small_thr = int(sys.argv[5]) if len(sys.argv) > 5 else SMALL_THR

    src_path = Path(src_dir)
    out_dir = src_path / f"单字_v{cell_size}_v48"

    process_all_images(src_dir, out_dir, n_cols, cell_size, expand_px, small_thr)
