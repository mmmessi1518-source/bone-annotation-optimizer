# 骨样标注优化工具

本地 Windows 图形工具：导入手动 Labelme 标注，补全组织类别和背景，将小独立区域转为 ignore，导出可继续编辑的 Polygon JSON。

## 使用

1. 在 Labelme 中标出样品外轮廓 `specimen`，再标 `bone` 或 `none_bone`；不确定区域标 `ignore`。
2. 添加 JSON 或导入整个标注目录，在优化预览中调整小区域面积和推导细缝宽度（各自设为 0 可关闭）。
3. 选择输出目录，导出当前图或勾选的批次。输出保持子目录，原稿不覆盖；同名文件自动另存。
4. 用 Labelme 打开结果继续编辑。第一次可通过「设置 Labelme」指定已有的 Labelme 程序或其 Python 解释器。

所有计算在本机完成。源文件不依赖固定盘符，目录选择保存在当前用户设置中。工具本身不包含 Labelme 或 AI 模型。

## 处理规则

- specimen 外部为 background；内部 ignore 优先。
- 仅画 bone 时补 none_bone，仅画 none_bone 时补 bone。
- 两类均已画时，交叠及内部未覆盖部分转 ignore。
- 手选相减模式且已有另一类时，逐像素验证另一类确实等于补集；不一致则提示复核。
- bone 和 none_bone 的小独立区域均按原图像素面积、8 连通、`面积 <= 阈值` 转 ignore。
- 推导类别中夹在两种不同类别之间的窄条可按宽度转 ignore，默认最大宽度为 4 个原图像素。手绘类别仅应用原有的小独立区域规则。
- 内部使用像素数组运算，出口全部为可编辑多边形。逐类别回读检查完全一致后才写出。

请在「优化预览」勾选「原图精度」复核细缝。宽度判定基于像素几何，实际组织类别仍由人工复核。有孔区域会拆分为同标签多边形，可能显示分区接缝。

## 从源码运行

Python 3.11，Windows x64：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python start.py
```

自动处理入口与界面共用同一套规则：

```powershell
python start.py --cli "D:\实验\手动标注版" --output "D:\实验\优化版" --threshold 100
```

当前验证的 Labelme 6.3.1 在外部照片和 JSON 跨盘保存时存在限制，建议输出与照片位于同一磁盘。

## 自动测试

```powershell
./scripts/test.ps1 -Python .venv\Scripts\python.exe
```

核心测试包括孔洞、碎片、相减、冲突、阈值往返、图像方向、写入保护与重新编辑；GUI 测试使用合成数据，不需要实验照片。每次 GitHub push/PR 自动运行 Windows 测试。

安装了 Labelme 的 Python 环境可额外运行：

```powershell
./scripts/test.ps1 -Python python -Labelme
```

## 打包

```powershell
.venv\Scripts\python -m pip install -r requirements-build.txt
./scripts/build.ps1 -Python .venv\Scripts\python.exe -Installer
```

安装包还需安装 Inno Setup 6 或 7；也可用 `-Iscc "编译器路径\ISCC.exe"` 指定。生成：

- `releases/<版本>/...portable-win64.zip`：自带运行环境，解压后运行 GUI 或 CLI exe。
- `releases/<版本>/...setup-win64.exe`：可选安装目录，支持快捷方式、升级和卸载。
- 版本来源清单和 SHA256 校验文件。

构建前源码必须有 Git 提交且工作区干净。发布包不含实验数据、标注 JSON、个人设置、Miniconda 或 Labelme。

GitHub Actions 的「Build Windows packages」可手动触发同一脚本，生成可下载构建产物；不会自动修改软件或上传实验数据。

## 维护

用户指定的唯一源码是 Codex `outputs/骨样标注优化工具`；已安装副本只负责运行。修改版本号 `bone_optimizer/__init__.py`，更新 `CHANGELOG.md`，测试、提交、构建、安装验证后再发布。详见 [维护流程](docs/maintenance.md) 和 [使用说明](使用说明.md)。
