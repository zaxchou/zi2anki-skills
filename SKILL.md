---
name: calligraphy-extractor
description: >
  书法单字提取 + Anki 记忆卡生成工具。
  从竖排书法图片中自动裁切单字/字组，用多模态视觉识别命名，
  生成可直接导入 Anki 的 .apkg 文件。
  适用场景：草书/行书图片、诗词书法、碑帖单字提取、Anki 记忆卡制作。
  触发词："提取书法单字"、"制作书法记忆卡"、"帮我裁切草书"。
---

# 书法单字提取 + Anki 记忆卡生成

## 工作流程

分三步，依次执行：

```
步骤 1：裁切单字图片（推荐 v48：scripts/extract_chars_v48.py）
步骤 2：视觉识别并重命名图片
步骤 3：生成 Anki .apkg 文件（create_anki_deck.py）
```

> **版本选择**：推荐使用 `extract_chars_v48.py`（v48 算法）。
> v48 相比 v44 的核心改进：
> - 增强印章检测（HSV 红色 + 形状宽高比检查，减少漏检）
> - 小孤立笔画归并（上方小点如"生"、"空"的头部自动归并到下方字符）
> - 保留 v44 的核心：字符 + 外扩 → 方形 + 真实背景
>
> v44（`extract_chars_v44.py`）是上一版本：印章检测较弱（仅 HSV 红色比例）。
> v34（`extract_chars.py`）是早期版本：使用固定 235 阈值 + CLAHE，会有白边。仅在兼容性需要时使用。

---

## 步骤 1：裁切单字图片

### 推荐：v48 版本

```bash
python scripts/extract_chars_v48.py <图片目录> [列数] [输出尺寸] [外扩像素] [小笔画阈值]
```

**参数：**
| 参数 | 默认值 | 说明 |
|------|---------|------|
| 图片目录 | （必填） | 包含书法图片的文件夹 |
| 列数 | `3` | 每行几个字（竖排右到左） |
| 输出尺寸 | `512` | 输出图片的像素尺寸 |
| 外扩像素 | `10` | 字符四周外扩像素（用于扩成方形） |
| 小笔画阈值 | `100` | 小于此像素的孤立笔画会尝试归并到下方字符 |

**示例：**
```bash
# 基础用法（3列，512px，10px外扩）
python scripts/extract_chars_v48.py ./书法图片/

# 4列布局
python scripts/extract_chars_v48.py ./书法图片/ 4

# 高分辨率输出（1024px, 20px外扩）
python scripts/extract_chars_v48.py ./书法图片/ 3 1024 20
```

**输出：**
- 裁切结果：`单字_v<尺寸>_v48/` 文件夹（如 `单字_v512_v48/`）
- 位置信息：`cell_positions_单字_v<尺寸>_v48.json`（用于调试）

**v48 算法说明：**
1. OTSU 二值化 + 闭运算（连通域检测）
2. Y 坐标聚类合并（宽松条件：保留点/偏旁等小笔画）
3. **小孤立笔画归并**：宽/高 < 100px 的孤立 group 自动归并到下方字符
4. 印章过滤（HSV 红色 + 形状宽高比检测）
5. **核心：从整张原图取字符 + 周围背景 → 扩成方形（max char dim + 2*外扩px）**
6. **居中放 512x512，100% 填充**
7. **背景从原图取真实纸纹**（不是 paper_color 也不是纯白）
8. 越界部分用边像素平铺
9. 背景过滤（低墨迹比例/低对比度）

### 旧版：v44（不推荐，印章检测较弱）

```bash
python scripts/extract_chars_v44.py <图片目录> [列数] [输出尺寸] [外扩像素]
```

v44 算法与 v48 类似，但：
- 印章检测仅用 HSV 红色比例（无形状检查），可能漏检黑色/深色印章
- 无小孤立笔画归并，可能出现"生"字被拆成两半的情况

---

## 步骤 2：视觉识别并重命名

裁切完成后，会得到一批 `pos_XXXX.jpg` 文件。需要用多模态视觉能力识别每个图片的内容，然后重命名。

### 操作方法

1. 用 `scripts/create_grid.py` 生成缩略图网格（方便批量查看）
   ```bash
   python scripts/create_grid.py ./单字_v512/ 20
   ```
   生成 `grid_overview.jpg`，在对话中查看并识别所有单元。

2. 按**从右到左、从上到下**的顺序，逐个识别图片内容：
   - 单字：直接命名为 `春.jpg`、`江.jpg`
   - 连笔字组（不强行拆分）：命名为 `江月.jpg`、`流照.jpg`
   - 重复字：加数字后缀 `月_1.jpg`、`月_2.jpg`
   - 跳过：印章、落款、空白碎片

3. 写 Python 脚本批量重命名（参考下面的命名脚本模板）

### 命名脚本模板

```python
import os
from pathlib import Path

# 手动整理的 位置 -> 字符名 映射
naming_map = {
    'pos_0001': '照',
    'pos_0002': '人',
    # ... 按实际识别结果填写
}

src_dir = Path('单字_v512')
dst_dir = Path('单字_命名')
dst_dir.mkdir(exist_ok=True)

for pos_name, char_name in naming_map.items():
    src = src_dir / f'{pos_name}.jpg'
    dst = dst_dir / f'{char_name}.jpg'

    # 处理重复名
    counter = 1
    while dst.exists():
        dst = dst_dir / f'{char_name}_{counter}.jpg'
        counter += 1

    shutil.copy2(src, dst)
    print(f'{pos_name}.jpg -> {dst.name}')
```

---

## 步骤 3：生成 Anki .apkg 文件

### ⚠️ 关键：图片显示原理

Anki 显示图片的正确方式是：
- **模板**里写 `<img src="{{BackFile}}">`
- **字段**里只放文件名（如 `char_0000.jpg`）
- Anki 渲染顺序：先替换字段 → 再渲染 HTML → 显示图片

**不要**在字段里直接写 `<img>` 标签（会被当纯文本显示）。

### 使用方法

```bash
python scripts/create_anki_deck.py <图片目录> [输出.apkg]
```

**示例：**
```bash
# 基础用法
python scripts/create_anki_deck.py ./单字_命名/ 书法记忆卡.apkg

# 指定输出文件名
python scripts/create_anki_deck.py ./单字_命名/ 春江花月夜.apkg
```

### 实现原理

脚本内部做了三件事：
1. **图片重命名为 ASCII**（`char_0000.jpg`）：避免中文/特殊字符编码问题
2. **模板写 `<img>` 标签**：`{{Front}}<hr id=answer><img src="{{BackFile}}">`
3. **用 genanki 生成 .apkg**：自动打包媒体文件到 ZIP

### 安装依赖

```bash
pip install genanki
```

### 导入 Anki

1. 确保已安装 Anki
2. **先删除之前导入的同名卡组**（避免模板冲突）
3. 双击 `.apkg` 文件，或 Anki 菜单「文件」→「导入」
4. 导入后点「浏览」验证：背面应该显示图片，不是文件名

---

## 参数调优

| 问题 | 调什么 | 方向 |
|------|---------|------|
| 字切得太碎（连笔字被强行拆分） | `detect_char_regions_v48()` 中的 Y 聚类合并条件 | 放宽（`y_overlap` 阈值降低，`y_gap` 阈值升高） |
| 漏字（淡墨/细笔画被过滤） | `min_area` / `min_height` | 降低阈值 |
| 印章/背景被当成字提取出来 | `is_seal()` / `is_background()` | 调整阈值（`red_ratio` / `std_threshold` / `ink_threshold`） |
| 图片显示太小 | `CELL_SIZE` | 增大（当前 512，可改 1024） |
| 列数识别错误 | 命令行第 2 个参数 | 手动指定（如 `4` 表示 4 列） |
| 字符留白太多 | `TARGET_FILL` / `PAD_RATIO` | `TARGET_FILL=1.0` + `PAD_RATIO=0.0` = 100% 填充无白边（v34） |
| 字符有白边（v34 问题） | 改用 v48 | v48 字符 + 外扩 = 方形 + 真实背景 |
| 外扩范围不够（v48） | `EXPAND_PX` | 增大到 15~20（v48 默认 10） |
| 上方小点未归并到字符 | `SMALL_THR` | 调整小笔画阈值（默认 100px） |

---

## 常见问题

### Q：背面显示 `<img src="xxx.jpg">` 而不是图片？
**A**：模板里没有写 `<img>` 标签。用 `create_anki_deck.py`（最新版本），它会自动在模板里写正确的标签。

### Q：背面显示纯文件名（如 `char_0000.jpg`）？
**A**：导入时选了错误的「类型」（Model）。删除卡组后重新导入，选择「基本（正面-背面）」或者让 .apkg 自动创建新 Model。

### Q：中文文件名导致图片不显示？
**A**：`create_anki_deck.py` 内部会自动把图片重命名为 `char_XXXX.jpg`（ASCII），无需手动处理。

### Q：Windows 控制台乱码？
**A**：脚本已用 UTF-8 编码，但 Windows 控制台默认 GBK。不影响实际功能，忽略即可。

### Q：印章被当成字提取出来了？
**A**：`is_seal()` 函数用 HSV 检测红色像素。如果印章颜色特殊，可以调整 `red_ratio` 阈值（当前 `0.03` = 3%）。

### Q：背景纸图（空白）被提取出来了？
**A**：`is_background()` 函数检测低对比度（标准差 `< 15`）或墨迹占比极低（`< 0.3%`）。可以调整这两个阈值。

---

## 项目文件结构

```
skills/calligraphy-extractor/
├── SKILL.md                    # 本文档
├── scripts/
│   ├── extract_chars.py        # 步骤 1：裁切单字（v34 旧版，仅作兼容性保留）
│   ├── extract_chars_v44.py   # 步骤 1：裁切单字（v44 上一版）
│   ├── extract_chars_v48.py    # 步骤 1：裁切单字（v48 推荐版）✅
│   ├── create_anki_deck.py     # 步骤 3：生成 .apkg
│   └── create_grid.py          # 辅助：生成缩略图网格
├── examples/                   # 示例图片
├── assets/                     # 资源文件
├── references/                 # 参考文档
└── README.md                   # 用户文档
```

---

## 踩坑记录（供参考，不需要复现）

1. **OTSU 二值化阈值约 85**：淡墨笔画会被当成背景过滤 → 解决：v32 改用非白像素检测（`< 235`）+ CLAHE 对比度增强
2. **均匀分割兜底会切碎连笔字**：v5 有此问题 → 解决：v26 去掉均匀分割，改用宽松 Y 聚类
3. **`<img>` 标签写在字段里不渲染**：Anki 会把字段内容当纯文本 → 解决：写在模板里
4. **中文/特殊字符文件名导致媒体文件无法加载**：`江 (2).jpg` → 解决：内部重命名为 `char_XXXX.jpg`
5. **Windows 自动重命名 ` (2)` 格式**：脚本只处理 `_2` 后缀 → 解决：全部重命名为 ASCII
6. **tight_crop 用 OTSU 会切掉淡墨笔画**：v30 及之前版本有此问题 → 解决：v32 改用非白像素检测
7. **上方点/下方偏旁被裁掉**：Y 聚类合并条件太严格 → 解决：v32 放宽条件（`y_gap < min_h * 0.20`）
8. **印章被当成字提取**：没有印章过滤 → 解决：v32 新增 `is_seal()` 函数（HSV 检测红色）
9. **背景纸图被当成字提取**：没有背景过滤 → 解决：v33 新增 `is_background()` 函数（低对比度 + 墨迹占比）
10. **非源图（如对比图）被处理**：没有排除机制 → 解决：v34 新增 `EXCLUDE_FILES` 配置
11. **输出图片留白太多**：`TARGET_FILL=0.80` + `PAD_RATIO=0.08` → 解决：v33 改为 `TARGET_FILL=1.0` + `PAD_RATIO=0.0`（100% 填充无白边）
12. **v34 100% 填充但字符有白边**：紧贴墨色 bbox 后缩放到 512x100%，扁矩形字符会留白 → 解决：v44 改为字符 + 10px 外扩 → 扩成方形 → 居中放 512x512
13. **v44 误用 paper_color 填充**：v40/v41 用原图最亮区均值作为背景色，会出现"色块"边界 → 解决：v44 直接从原图取真实背景（不只是颜色）
14. **中文路径写入失败**：`cv2.imwrite` 不支持中文路径 → 解决：用 `cv2.imencode + buf.tofile`（v44 统一）
