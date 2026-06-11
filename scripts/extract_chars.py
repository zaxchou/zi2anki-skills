"""
书法单字裁切脚本 v29
基于v28改进：
1. 在 split_column_chars 最终输出前，对每个区域上下扩展边距
   确保小笔画（点、挑等）不会被切掉
"""

import os
import json
import cv2
import numpy as np
from pathlib import Path
from PIL import Image

SRC_DIR = Path(r"E:\下载\春江花明月")
OUT_DIR = SRC_DIR / "单字_v29"
META_PATH = SRC_DIR / "cell_positions_v29.json"
OUT_DIR.mkdir(exist_ok=True)

CELL_SIZE = 512
PAD_RATIO = 0.08


def read_image_unicode(img_path):
    pil_img = Image.open(str(img_path)).convert("RGB")
    img = np.array(pil_img)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def get_col_splits(img, n_cols=3):
    h, w = img.shape[:2]
    col_w = w // n_cols
    splits = []
    for i in range(n_cols):
        x0 = i * col_w
        x1 = (i + 1) * col_w if i < n_cols - 1 else w
        splits.append((x0, x1))
    return splits[::-1]


def estimate_char_height(col_img):
    """估计单字高度"""
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
    """
    用指定kernel做闭运算后，连通域检测+严格Y聚类合并。
    降低小连通域过滤阈值，确保点、挑等细小笔画被保留。
    返回合并后的边界框列表 [(x1,y1,x2,y2,area), ...]
    """
    h, w = col_img.shape[:2]
    gray = cv2.cvtColor(col_img, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 闭运算
    if close_kernel[0] > 0 and close_kernel[1] > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, close_kernel)
        bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel)

    # 连通域检测
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(bw, connectivity=8)

    est_char_h = estimate_char_height(col_img)
    # 降低阈值：小笔画（如点）面积可能只有几百像素
    min_area = h * w * 0.0005  # 从 0.002 降到 0.0005
    min_height = est_char_h * 0.12  # 从 0.25 降到 0.12

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

    # 按Y中心排序
    comps.sort(key=lambda c: c['cy'])

    # Y聚类合并：收紧条件，避免误合并独立单字
    groups = []
    for comp in comps:
        merged = False
        for g in groups:
            last = g[-1]
            # 计算Y方向距离
            y_gap = max(0, max(comp['y'], last['y']) - min(comp['y2'], last['y2']))
            y_overlap = max(0, min(comp['y2'], last['y2']) - max(comp['y'], last['y']))
            cy_dist = abs(comp['cy'] - last['cy'])
            min_h = min(comp['h'], last['h'])

            # 严格合并条件：只有真正属于同一字的笔画才合并
            if (y_overlap > min_h * 0.15 or
                y_gap < min_h * 0.20 or
                cy_dist < min_h * 0.25):
                g.append(comp)
                merged = True
                break
        if not merged:
            groups.append([comp])

    # 将组合并为边界框
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


def try_split_region(roi, est_char_h):
    """
    尝试用水平投影找深谷值分割区域。
    只在找到明显深谷值时才分割，否则返回None表示不分割。
    """
    roi_h, roi_w = roi.shape[:2]
    if roi_h <= est_char_h * 1.3:
        return None  # 不够高，不需要分割

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 在中心 60% 宽度内做水平投影
    margin = int(roi_w * 0.2)
    center_bw = bw[:, margin:roi_w - margin] if roi_w > 20 else bw
    horiz_proj = center_bw.sum(axis=1).astype(float)

    if horiz_proj.max() == 0:
        return None

    # 归一化
    horiz_proj = horiz_proj / horiz_proj.max()

    # 找局部最小值（谷值），且深度要足够
    est_n = max(2, int(round(roi_h / est_char_h)))
    valleys = []
    for i in range(1, len(horiz_proj) - 1):
        if horiz_proj[i] < horiz_proj[i - 1] and horiz_proj[i] <= horiz_proj[i + 1]:
            depth = (horiz_proj[i - 1] + horiz_proj[i + 1]) / 2 - horiz_proj[i]
            valleys.append((i, depth, horiz_proj[i]))

    if not valleys:
        return None

    # 按深度排序
    valleys.sort(key=lambda v: v[1], reverse=True)

    # 只取深度 > 0.3 的谷值（要求明显的空白间隙）
    deep_valleys = [v for v in valleys if v[1] > 0.30]

    # 限制分割数量不超过估计字数
    max_splits = est_n - 1
    if len(deep_valleys) > max_splits:
        deep_valleys = deep_valleys[:max_splits]

    if not deep_valleys:
        return None  # 没有足够深的谷值，不分割

    split_points = sorted([0] + [v[0] for v in deep_valleys] + [roi_h])

    # 检查每个分段的高度是否合理（至少0.4倍字高）
    segments = []
    for i in range(len(split_points) - 1):
        sy0, sy1 = split_points[i], split_points[i + 1]
        if sy1 - sy0 >= est_char_h * 0.4:
            segments.append((sy0, sy1))

    if len(segments) < 2:
        return None  # 分不出至少两段合理的区域

    return segments


def split_column_chars(col_img):
    """
    主分割：
    1. 用严格Y聚类检测连通域
    2. 对过高区域尝试水平投影分割，只有明显深谷值才分
    3. 如果字太少，逐步增大闭运算重试
    4. 最终输出前，上下扩展边距保留小笔画
    """
    h, w = col_img.shape[:2]
    est_char_h = estimate_char_height(col_img)
    est_n = max(5, int(round(h / est_char_h)))

    # 尝试不同kernel大小，从小到大
    kernels = [(5, 5), (15, 30), (25, 50), (35, 70)]
    best_result = []

    for kw, kh in kernels:
        regions = detect_char_regions(col_img, close_kernel=(kw, kh))

        # 对过高区域尝试分割
        final_regions = []
        for r in regions:
            x1, y1, x2, y2, area = r
            ch = y2 - y1
            if ch > est_char_h * 1.5:
                # 尝试分割
                roi = col_img[y1:y2, x1:x2]
                segments = try_split_region(roi, est_char_h)
                if segments:
                    for sy0, sy1 in segments:
                        final_regions.append((x1, y1 + sy0, x2, y1 + sy1, area // len(segments)))
                else:
                    final_regions.append(r)
            else:
                final_regions.append(r)

        # 过滤过小区域
        filtered = []
        for r in final_regions:
            _, y1, _, y2, _ = r
            ch = y2 - y1
            if ch >= est_char_h * 0.3:
                filtered.append(r)

        # 选择检测结果数量最接近预期的
        if len(filtered) >= est_n * 0.5 or len(filtered) >= 5:
            best_result = filtered
            break
        elif len(filtered) > len(best_result):
            best_result = filtered

    # 上下扩展边距，确保小笔画（点、挑等）不被切掉
    margin_y = int(est_char_h * 0.30)  # 上下各扩展30%字高
    margin_x = int(w * 0.08)  # 左右各扩展8%列宽
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
    """
    对单字单元做紧裁剪，保留所有墨迹（包括小点、牵丝）。
    不再用轮廓面积过滤，直接用二值图像的整体边界框。
    """
    h, w = cell_img.shape[:2]
    gray = cv2.cvtColor(cell_img, cv2.COLOR_BGR2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # 轻微膨胀，确保牵丝被包含在内
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    bw = cv2.dilate(bw, kernel, iterations=1)

    # 找到所有非零像素的坐标
    coords = np.column_stack(np.where(bw > 0))
    if len(coords) == 0:
        return cell_img

    y_min, x_min = coords.min(axis=0)
    y_max, x_max = coords.max(axis=0)

    # 加padding
    char_h = y_max - y_min + 1
    char_w = x_max - x_min + 1
    pad = int(max(char_h, char_w) * pad_ratio)
    pad = max(pad, 8)

    x_min = max(0, x_min - pad)
    y_min = max(0, y_min - pad)
    x_max = min(w - 1, x_max + pad)
    y_max = min(h - 1, y_max + pad)

    return cell_img[y_min:y_max+1, x_min:x_max+1]


def make_square(char_img, size=CELL_SIZE, target_fill=0.80):
    """
    去掉白边，直接等比例缩放，让字占满整个图。
    长边缩放到 size，短边按比例缩放，不填充白底。
    """
    ch, cw = char_img.shape[:2]
    if ch == 0 or cw == 0:
        return np.ones((size, size, 3), dtype=np.uint8) * 255

    target_px = int(size * target_fill)
    scale = min(target_px / ch, target_px / cw)
    new_ch = int(ch * scale)
    new_cw = int(cw * scale)

    interp = cv2.INTER_CUBIC if new_ch > ch else cv2.INTER_AREA
    resized = cv2.resize(char_img, (new_cw, new_ch), interpolation=interp)

    return resized


def process_all_images():
    jpg_files = sorted([f for f in SRC_DIR.glob("*.jpg") if f.parent == SRC_DIR])
    print(f"Found {len(jpg_files)} source images")

    old_files = list(OUT_DIR.glob("*.jpg"))
    for f in old_files:
        f.unlink()
    print(f"Cleared {len(old_files)} old files")

    global_idx = 0
    all_meta = []

    for img_path in jpg_files:
        stem = img_path.stem
        print(f"\n{'='*50}")
        print(f"[{stem}] Processing...")

        try:
            img = read_image_unicode(img_path)
        except Exception as e:
            print(f"  FAIL: {e}")
            continue

        col_splits = get_col_splits(img, 3)

        for ci, (cx0, cx1) in enumerate(col_splits):
            col_img = img[:, cx0:cx1]
            char_boxes = split_column_chars(col_img)
            print(f"  Col {ci+1}: {len(char_boxes)} chars")

            for ri, (x1, y1, x2, y2, area) in enumerate(char_boxes):
                raw_cell = col_img[y1:y2, x1:x2]
                char_img = tight_crop_char(raw_cell)
                final = make_square(char_img)

                global_idx += 1
                fname = f"pos_{global_idx:04d}"
                out_path = OUT_DIR / f"{fname}.jpg"

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

    with open(META_PATH, 'w', encoding='utf-8') as f:
        json.dump(all_meta, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"DONE: {global_idx} cells extracted")
    print(f"Output dir: {OUT_DIR}")
    print(f"Metadata:   {META_PATH}")
    return all_meta


if __name__ == "__main__":
    process_all_images()
