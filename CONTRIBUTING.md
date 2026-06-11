# 🤝 贡献指南 (Contributing Guide)

感谢你对 **zi2anki** 项目的关注！这份文档将帮助你了解如何参与项目开发。

---

## 🌟 如何贡献

### 报告 Bug

如果你发现了 Bug，请：

1. **搜索现有 Issue**：确认问题未被报告过
2. **创建新 Issue**：
   - 使用清晰的标题
   - 描述预期行为 vs 实际行为
   - 提供复现步骤
   - 附上错误截图/日志

### 功能建议

欢迎提出新功能建议！请：

1. **创建 Issue**，标签选择 `enhancement`
2. **描述使用场景**：为什么需要这个功能？
3. **提供示例**：如果可能，给出输入/输出示例

### 提交代码

#### 1. Fork 本仓库

```bash
# 在你的 GitHub 账号下创建 Fork
# 然后克隆到本地
git clone https://github.com/你的用户名/zi2anki.git
cd zi2anki
```

#### 2. 创建特性分支

```bash
git checkout -b feature/你的功能名
# 或
git checkout -b fix/你修复的Bug名
```

#### 3. 编写代码

**代码规范**：
- Python 代码遵循 [PEP 8](https://pep8.org/)
- 使用有意义的变量名和函数名
- 添加必要的注释（英文或中文均可）
- 更新相关文档（`README.md`、`SKILL.md` 等）

**测试要求**：
- 在提交前测试你的代码
- 如果可能，添加单元测试

#### 4. 提交更改

```bash
git add .
git commit -m "feat: 添加 XXX 功能"
# 或
git commit -m "fix: 修复 XXX Bug"
```

**Commit Message 规范**：
- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `style`: 代码格式调整（不影响功能）
- `refactor`: 重构（既不是新功能也不是 Bug 修复）
- `test`: 添加测试
- `chore`: 构建过程或辅助工具的变动

#### 5. 推送到 Fork

```bash
git push origin feature/你的功能名
```

#### 6. 创建 Pull Request

1. 访问你的 Fork 页面
2. 点击 **Compare & pull request**
3. 填写 PR 描述：
   - 解决了哪个 Issue（如有）
   - 做了哪些更改
   - 如何测试
4. 等待审核

---

## 🧪 测试指南

### 测试裁切脚本

```bash
# 准备测试图片
mkdir test_images
# 复制一张书法图片到 test_images/

# 运行裁切脚本
python scripts/extract_chars.py test_images/ 3 512

# 检查输出
ls 单字_v29/
```

### 测试 Anki 卡包生成

```bash
# 准备命名后的图片文件夹
# 运行生成脚本
python scripts/create_anki_deck.py 命名后的图片文件夹/ 测试卡包.apkg

# 检查输出
ls -lh 测试卡包.apkg
```

### 手动测试 Anki 导入

1. 双击生成的 `.apkg` 文件
2. 在 Anki 中查看卡片
3. 确认正面显示汉字，背面显示书法图片

---

## 📝 文档贡献

文档同样重要！如果你发现：

- `README.md` 有错别字或表述不清
- `SKILL.md` 缺少某些使用场景的说明
- 示例代码无法运行

欢迎提交 PR 修复！

---

## 🔍 代码审核标准

维护者会从以下角度审核你的 PR：

- ✅ **功能正确性**：代码是否实现了预期功能？
- ✅ **代码质量**：是否遵循代码规范？是否有必要的注释？
- ✅ **测试覆盖**：是否测试了主要场景？
- ✅ **文档更新**：是否更新了相关文档？
- ✅ **向后兼容**：是否破坏了现有功能？

---

## 💬 联系方式

如果你有任何疑问，可以：

- 在 [Issue](https://github.com/zaxchou/zi2anki/issues) 中提问
- 联系维护者：[@zaxchou](https://github.com/zaxchou)

---

再次感谢你的贡献！🎉