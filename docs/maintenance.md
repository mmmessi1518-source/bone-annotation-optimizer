# 维护和发布流程

## 唯一源码

用户指定 Codex 的 `outputs/骨样标注优化工具` 为唯一源码工作区，也是 Git 仓库根目录。所有代码、测试、依赖、版本说明及打包脚本都在这里维护。安装目录属于发布后的运行副本，不直接修改其中的 Python 文件。

本地 `vendor` 是旧运行依赖，已被 Git 忽略；新构建使用单独环境安装固定依赖。实验数据、个人验收记录、快捷方式及安装包也被忽略。

## 一次升级

1. 用 `git status` 确认当前状态；在本地新分支修改，保留能够回退的提交。
2. 修改共享处理服务，GUI 和 CLI 使用同一规则。处理规则的改变必须更新相应测试。
3. 运行 `scripts/test.ps1`；改动 JSON/轮廓时，在现有 Labelme 环境加 `-Labelme`。
4. 提升 `bone_optimizer/__init__.py` 的版本号，更新 CHANGELOG，提交修改。
5. 在干净的 Python 3.11 环境运行 `scripts/build.ps1 -Installer`；构建要求 Git 工作区干净。
6. 在独立安装目录验证打开、导出、Labelme 编辑和升级设置保留，核对版本清单与源码提交。
7. 推送 GitHub。核对 Tests 工作流，再创建版本标签/发布说明和需要分享的安装包。

源码快照由 Git 保留；安装包保存在 `releases/版本号`。退回旧版时安装已验证的旧版本，实验原稿和历史优化结果继续保留，避免用新版输出覆盖手动原稿。

## 自动化

- `scripts/test.ps1`：核心和 GUI 回归，出错立即返回失败。
- `scripts/build.ps1`：测试 → 源码状态检查 → 独立打包 → exe 自检 → ZIP/安装包 → 来源清单和哈希。
- GitHub `Tests`：每次推送/PR 检查。
- GitHub `Build Windows packages`：手动构建便携版、安装包，保存为工作流产物。

当前用户设置保存在 QSettings `BoneResearch/AnnotationOptimizer`。安装和卸载脚本不清除这些设置，数据文件在软件目录之外。
