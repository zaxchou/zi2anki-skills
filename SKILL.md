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
步骤 1：裁切单字图片（extract_chars.py）
步骤 2：视觉识别并重命名图片
步骤 3：生成 Anki .apkg 文件（create_anki_deck.py）
```

---

## 步骤 1：裁切单字图片

### 使用方法

```bash
python scripts/extract_chars.py <图片目录> [列数] [输出尺寸]
```

**参数：**
| 参数 | 默认值 | 说明 |
|------|---------|------|
| 图片目录 | （必填） | 包含书法图片的文件夹 |
| 列数 | `3` | 每行几个字（竖排右到左） |
| 输出尺寸 | `512` | 输出图片的像素尺寸 |

**示例：**
```bash
# 基础用法（3列，512px）
python scripts/extract_chars.py ./书法图片/

# 4列布局
python scripts/extract_chars.py ./书法图片/ 4

# 高分辨率输出（1024px）
python scripts/extract_chars.py ./书法图片/ 3 1024
```

### 输出

- 裁切结果：`单字_v<尺寸>/` 文件夹（如 `单字_v512/`）
- 位置信息：`cell_positions_单字_v<尺寸>.json`（用于调试）

### 算法说明

核心策略（v34，当前最新版本）：
1. **OTSU 二值化** + 自适应闭运算（自动尝试多种 kernel 尺寸：(5,5)→(35,70)）
2. **连通域检测** + Y 坐标聚类合并（宽松条件：`y_overlap > 5%` 或 `y_gap < 20%`，保留上方点、下方偏旁等小笔画）
3. **水平投影深谷分割**（对过高区域 `>1.3倍字高` 尝试分割，深度阈值 `>0.20`）
4. **tight crop v34**：非白像素检测（`< 235`），配合 CLAHE 对比度增强，保留淡墨笔画；`PAD_RATIO=0`，不留白边
5. **印章过滤**：HSV 色彩空间检测红色像素（红色占比 `> 3%` 判定为印章，自动跳过）
6. **背景过滤**：低对比度检测（标准差 `< 15`）或墨迹占比极低（`< 0.3%`），自动跳过空白纸区域
7. **100% 填充画布**：`TARGET_FILL=1.0`，字符完全填满 512×512 方形画布，不留白边
8. **排除非源图**：自动过滤对比图等非书法图片（如 `v29_vs_v30_comparison`）

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
| 字切得太碎（连笔字被强行拆分） | `detect_char_regions()` 中的 Y 聚类合并条件 | 放宽（`y_overlap` 阈值降低，`y_gap` 阈值升高） |
| 漏字（淡墨/细笔画被过滤） | `min_area` / `min_height` | 降低阈值 |
| 印章/背景被当成字提取出来 | `is_seal()` / `is_background()` | 调整阈值（`red_ratio` / `std_threshold` / `ink_threshold`） |
| 图片显示太小 | `CELL_SIZE` | 增大（当前 512，可改 1024） |
| 列数识别错误 | 命令行第 2 个参数 | 手动指定（如 `4` 表示 4 列） |
| 字符留白太多 | `TARGET_FILL` / `PAD_RATIO` | `TARGET_FILL=1.0` + `PAD_RATIO=0.0` = 100% 填充无白边 |

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
│   ├── extract_chars.py        # 步骤 1：裁切单字（v34）
│   ├── create_anki_deck.py   # 步骤 3：生成 .apkg
│   └── create_grid.py         # 辅助：生成缩略图网格
├── examples/                  # 示例图片
├── assets/                    # 资源文件
├── references/                # 参考文档
└── README.md                 # 用户文档
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
