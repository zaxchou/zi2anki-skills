#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最终版：模板里写 <img> 标签，字段只放文件名
Anki 会先替换字段，再渲染 HTML
"""

import sys
import os
import shutil
import zipfile
import json
from pathlib import Path

def create_deck_v4(img_dir, output_apkg='output_v4.apkg'):
    import genanki
    
    img_dir = Path(img_dir)
    if not img_dir.exists():
        print(f'错误：目录不存在 - {img_dir}')
        return
    
    # 只收集 jpg 文件（不重复）
    img_files = sorted([f for f in img_dir.glob('*.jpg') if not f.name.startswith('char_')])
    if not img_files:
        print(f'警告：{img_dir} 中没有找到 jpg 文件')
        return
    
    print(f'找到 {len(img_files)} 张图片')
    
    # 创建临时目录存放 ASCII 命名图片
    temp_dir = img_dir.parent / '_temp_ascii'
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    
    # 建立映射
    ascii_paths = []   # 临时图片完整路径（给 genanki.media_files）
    ascii_to_char = {}  # ascii_filename -> 中文字符名
    
    for i, img_path in enumerate(img_files):
        ascii_name = f'char_{i:04d}.jpg'
        temp_path = temp_dir / ascii_name
        shutil.copy2(img_path, temp_path)
        
        ascii_paths.append(str(temp_path.absolute()))
        ascii_to_char[ascii_name] = img_path.stem
    
    print(f'临时图片已保存到：{temp_dir}')
    print(f'示例：{list(ascii_to_char.items())[:3]}')
    
    # === 创建 Model（关键：模板里写 <img> 标签）===
    MODEL = genanki.Model(
        2018190001,
        '书法单字记忆卡',
        fields=[
            {'name': 'Front'},   # 中文字符
            {'name': 'BackFile'}, # 图片文件名（如 char_0000.jpg）
        ],
        templates=[{
            'name': '正面-背面',
            'qfmt': '{{Front}}',
            # 关键：在模板里写 <img> 标签，BackFile 字段放文件名
            'afmt': '{{Front}}<hr id=answer><img src="{{BackFile}}">',
        }],
        css='.card { font-family: KaiTi, STKaiti, serif; font-size: 120px; text-align: center; }'
    )
    
    DECK = genanki.Deck(2018190001, '春江花月夜·书法单字')
    
    for ascii_name, char_name in ascii_to_char.items():
        # 正面：中文字符
        # 背面：ASCII 文件名（模板里的 <img src="{{BackFile}}"> 会渲染成图片）
        note = genanki.Note(MODEL, [char_name, ascii_name])
        DECK.add_note(note)
    
    # 生成 .apkg
    pkg = genanki.Package(DECK)
    pkg.media_files = ascii_paths
    pkg.write_to_file(output_apkg)
    
    print(f'\n完成！')
    print(f'  卡组名称：春江花月夜·书法单字')
    print(f'  卡片数量：{len(img_files)} 张')
    print(f'  输出文件：{output_apkg}')
    print(f'\n导入方法：')
    print(f'  1. 确保已安装 Anki')
    print(f'  2. 双击 {output_apkg} 即可自动导入')
    print(f'  3. 或在 Anki 中点击 文件 -> 导入，选择该文件')
    print(f'\n临时图片保留在：{temp_dir}')
    print(f'（如果导入成功，可以手动删除此目录）')
    
    return output_apkg, temp_dir

if __name__ == '__main__':
    img_dir = sys.argv[1] if len(sys.argv) > 1 else r'E:\下载\春江花明月\单字_命名 - 副本'
    output_apkg = sys.argv[2] if len(sys.argv) > 2 else r'E:\下载\春江花明月\春江花月夜_书法记忆卡_v4.apkg'
    create_deck_v4(img_dir, output_apkg)
