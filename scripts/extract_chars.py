"""
书法单字裁切脚本 v34
用法：python extract_chars.py <图片目录> [列数] [输出尺寸]

核心算法：
1. OTSU二值化 + 自适应闭运算（自动尝试多种 kernel 尺寸）
2. 连通域检测 + Y坐标聚类合并（宽松条件，保留小笔画如点、偏旁）
3. 水平投影深谷分割（处理过高区域）
4. tight crop（非白像素检测，不过度依赖OTSU，保留淡墨笔画）
5. 印章过滤（HSV检测红色像素）
6. 背景过滤（低对比度/墨迹占比极低）
7. 100%填充画布，不留白边
"""

import os
import json
import cv2
import numpy as np
from pathlib import Path
from PIL import Image
import sys


# === 可配置参数 ===
CELL_SIZE = 512          # 输出图片尺寸（正方形）
TARGET_FILL = 1.0       # 字符占画布比例（1.0 = 100%，不留白边）
PAD_RATIO = 0.0         # tight_crop 留白比例（0 = 不留白边）
EXCLUDE_FILES = set()     # 要排除的文件名（不含扩展名）


def read_image_unicode(img_path):
    """读取含Unicode路径的图片"""
    pil_img = Image.open(str(img_path)).convert("RGB")
    img = np.array(pil_img)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def is_seal(bgr_img):
    """判断是否为印章（红色印章）"""
    hsv = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HSV)
    lower_red1 = np.array([0, 50, 50])
    upper_red1 = np.array([10, 255, 255])
    lower_red2 = np.array([160, 50, 50])
    upper_red2 = np.array([180, 255, 255])
    mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
    mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
    red_mask = mask1 | mask2
    red_ratio = red_mask.sum() / (255.0 * bgr_img.shape[0] * bgr_img.shape[1])
    return red_ratio > 0.03


def is_background(bgr_img, std_threshold=15, ink_threshold=0.003):
    """判断是否为背景纸图（无效图片）"""
    ink_mask = np.any(bgr_img < 235, axis=2)
    ink_ratio = ink_mask.sum() / (bgr_img.shape[0] * bgr_img.shape[1])
    if ink_ratio < ink_threshold:
        return True
    gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)
    if gray.std() < std_threshold:
        return True
    return False


def get_col_splits(img, n_cols=3):
    h, w = img.shape[:2]
    col_w = w // n_cols
    splits = []
    for i in range(n_cols):
        x0 = i * col_w
        x1 = (i + 1) * col_w if i < n_cols - 1 else w
        splits.append((x0, x1))
    return splits[::-1]  # 从右到左


def estimate_char_height(col_img):
    h, w = col_img.shape[:2]
    gray = cv2.cvtColor(col_img, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    vert_proj = bw.sum(axis=0)
    if vert_proj.max() == 0:
        return w * 1.2
    threshold = vert_proj.max() * 0.1
    ink_cols = np.where(vert_proj > threshold)[0]
    if len(ink_cols) == 0:
        return w * 1.2
    center_w = ink_cols[-1] - ink_cols[0] + 1
    return center_w * 1.2


def detect_char_regions(col_img, close_kernel=(5, 5)):
    h, w = col_img.shape[:2]
    gray = cv2.cvtColor(col_img, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    if close_kernel[0] > 0 and close_kernel[1] > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, close_kernel)
        bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel)

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(bw, connectivity=8)

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

    # 宽松Y聚类合并（保留小笔画）
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
        total_area = sum(c['area'] for c in g)
        result.append((x1, y1, x2, y2, total_area))

    result.sort(key=lambda r: (r[1] + r[3]) / 2)
    return result


def force_split_by_hproj(roi, est_char_h):
    roi_h, roi_w = roi.shape[:2]
    if roi_h <= est_char_h * 1.2:
        return None

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    margin = int(roi_w * 0.2)
    center_bw = bw[:, margin:roi_w - margin] if roi_w > 20 else bw
    horiz_proj = center_bw.sum(axis=1).astype(float)

    if horiz_proj.max() == 0:
        return None

    horiz_proj = horiz_proj / horiz_proj.max()

    valleys = []
    for i in range(1, len(horiz_proj) - 1):
        if horiz_proj[i] < horiz_proj[i - 1] and horiz_proj[i] <= horiz_proj[i + 1]:
            depth = (horiz_proj[i - 1] + horiz_proj[i + 1]) / 2 - horiz_proj[i]
            valleys.append((i, depth, horiz_proj[i]))

    if not valleys:
        return None

    valleys.sort(key=lambda v: v[1], reverse=True)
    deep_valleys = [v for v in valleys if v[1] > 0.20]

    est_n = max(2, int(round(roi_h / est_char_h)))
    max_splits = est_n - 1
    if len(deep_valleys) > max_splits:
        deep_valleys = deep_valleys[:max_splits]

    if not deep_valleys:
        return None

    split_points = sorted([0] + [v[0] for v in deep_valleys] + [roi_h])

    segments = []
    for i in range(len(split_points) - 1):
        sy0, sy1 = split_points[i], split_points[i + 1]
        if sy1 - sy0 >= est_char_h * 0.35:
            segments.append((sy0, sy1))

    if len(segments) < 2:
        return None

    return segments


def split_column_chars(col_img):
    h, w = col_img.shape[:2]
    est_char_h = estimate_char_height(col_img)
    est_n = max(5, int(round(h / est_char_h)))

    kernels = [(5, 5), (15, 30), (25, 50), (35, 70)]
    best_result = []

    for kw, kh in kernels:
        regions = detect_char_regions(col_img, close_kernel=(kw, kh))

        final_regions = []
        for r in regions:
            x1, y1, x2, y2, area = r
            ch = y2 - y1
            if ch > est_char_h * 1.3:
                roi = col_img[y1:y2, x1:x2]
                segments = force_split_by_hproj(roi, est_char_h)
                if segments:
                    for sy0, sy1 in segments:
                        final_regions.append((x1, y1 + sy0, x2, y1 + sy1, area // len(segments)))
                else:
                    final_regions.append(r)
            else:
                final_regions.append(r)

        filtered = []
        for r in final_regions:
            _, y1, _, y2, _ = r
            ch = y2 - y1
            if ch >= est_char_h * 0.3:
                filtered.append(r)

        if len(filtered) >= est_n * 0.5 or len(filtered) >= 5:
            best_result = filtered
            break
        elif len(filtered) > len(best_result):
            best_result = filtered

    margin_y = int(est_char_h * 0.10)
    margin_x = int(w * 0.03)
    expanded = []
    for r in best_result:
        x1, y1, x2, y2, area = r
        x1 = max(0, x1 - margin_x)
        y1 = max(0, y1 - margin_y)
        x2 = min(w, x2 + margin_x)
        y2 = min(h, y2 + margin_y)
        expanded.append((x1, y1, x2, y2, area))

    return expanded


def tight_crop_char(cell_img, pad_ratio=PAD_RATIO):
    """非白像素检测，保留淡墨笔画，不留白边"""
    h, w = cell_img.shape[:2]

    lab = cv2.cvtColor(cell_img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    enhanced = cv2.merge([l, a, b])
    enhanced = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)

    non_white = np.any(enhanced < 235, axis=2)
    if not np.any(non_white):
        non_white = np.any(cell_img < 235, axis=2)

    coords = np.column_stack(np.where(non_white))
    if len(coords) == 0:
        return cell_img

    y_min, x_min = coords.min(axis=0)
    y_max, x_max = coords.max(axis=0)

    pad = int(max(y_max - y_min + 1, x_max - x_min + 1) * pad_ratio)
    pad = max(pad, 0)

    x_min = max(0, x_min - pad)
    y_min = max(0, y_min - pad)
    x_max = min(w - 1, x_max + pad)
    y_max = min(h - 1, y_max + pad)

    return cell_img[y_min:y_max + 1, x_min:x_max + 1]


def make_square(char_img, size, target_fill=TARGET_FILL):
    """size 由调用方显式传入，不使用默认值"""
    ch, cw = char_img.shape[:2]
    if ch == 0 or cw == 0:
        return np.ones((size, size, 3), dtype=np.uint8) * 255

    target_px = int(size * target_fill)
    scale = min(target_px / ch, target_px / cw)
    new_ch = max(int(ch * scale), 1)
    new_cw = max(int(cw * scale), 1)

    interp = cv2.INTER_CUBIC if new_ch > ch else cv2.INTER_AREA
    resized = cv2.resize(char_img, (new_cw, new_ch), interpolation=interp)

    canvas = np.ones((size, size, 3), dtype=np.uint8) * 255
    y_offset = (size - new_ch) // 2
    x_offset = (size - new_cw) // 2

    if y_offset + new_ch <= size and x_offset + new_cw <= size:
        canvas[y_offset:y_offset + new_ch, x_offset:x_offset + new_cw] = resized

    return canvas


def process_all_images(src_dir, out_dir, n_cols=3, cell_size=CELL_SIZE):
    src_dir = Path(src_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(exist_ok=True)

    meta_path = out_dir.parent / f"cell_positions_{out_dir.name}.json"

    jpg_files = sorted([
        f for f in src_dir.glob("*.jpg")
        if f.stem not in EXCLUDE_FILES
    ])
    print(f"Found {len(jpg_files)} source images")

    old_files = list(out_dir.glob("*.jpg"))
    for f in old_files:
        f.unlink()
    print(f"Cleared {len(old_files)} old files")

    global_idx = 0
    all_meta = []
    skipped_seals = 0
    skipped_background = 0

    for img_path in jpg_files:
        stem = img_path.stem
        print(f"\n{'=' * 50}")
        print(f"[{stem}] Processing...")

        try:
            img = read_image_unicode(img_path)
        except Exception as e:
            print(f"  FAIL: {e}")
            continue

        col_splits = get_col_splits(img, n_cols)

        for ci, (cx0, cx1) in enumerate(col_splits):
            col_img = img[:, cx0:cx1]
            est_char_h = estimate_char_height(col_img)
            char_boxes = split_column_chars(col_img)
            print(f"  Col {ci + 1}: {len(char_boxes)} chars")

            for ri, (x1, y1, x2, y2, area) in enumerate(char_boxes):
                raw_cell = col_img[y1:y2, x1:x2]

                if is_seal(raw_cell):
                    skipped_seals += 1
                    print(f"    Skip seal at row {ri + 1}")
                    continue

                char_img = tight_crop_char(raw_cell)

                if char_img.shape[0] < 10 or char_img.shape[1] < 10:
                    skipped_background += 1
                    print(f"    Skip tiny at row {ri + 1}")
                    continue

                if is_background(char_img):
                    skipped_background += 1
                    std = cv2.cvtColor(char_img, cv2.COLOR_BGR2GRAY).std()
                    print(f"    Skip background at row {ri + 1} (std={std:.1f})")
                    continue

                final = make_square(char_img, size=cell_size)

                global_idx += 1
                fname = f"pos_{global_idx:04d}"
                out_path = out_dir / f"{fname}.jpg"

                rgb = cv2.cvtColor(final, cv2.COLOR_BGR2RGB)
                Image.fromarray(rgb).save(str(out_path), "JPEG", quality=95)

                meta = {
                    "pos": global_idx,
                    "img_file": stem,
                    "col": ci + 1,
                    "row": ri + 1,
                    "col_range": [int(cx0), int(cx1)],
                    "row_range": [int(y1), int(y2)],
                    "char_range": [int(x1), int(x2)],
                    "area": int(area),
                }
                all_meta.append(meta)

    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(all_meta, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 50}")
    print(f"DONE: {global_idx} cells extracted")
    print(f"Skipped seals: {skipped_seals}")
    print(f"Skipped background: {skipped_background}")
    print(f"Output dir: {out_dir}")
    print(f"Metadata:   {meta_path}")
    return all_meta


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_chars.py <图片目录> [列数] [输出尺寸]")
        print("Example: python extract_chars.py ./书法图片/ 3 512")
        sys.exit(1)

    src_dir = sys.argv[1]
    n_cols = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    cell_size = int(sys.argv[3]) if len(sys.argv) > 3 else 512

    CELL_SIZE = cell_size

    src_path = Path(src_dir)
    out_dir = src_path / f"单字_v{cell_size}"

    process_all_images(src_dir, out_dir, n_cols, cell_size)
