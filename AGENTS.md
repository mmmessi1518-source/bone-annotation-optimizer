# Maintenance and repeated use

The ONLY canonical source is this Codex outputs directory and its Git repository.
Do not edit the E-drive installed copy. Build/deploy from committed source using
scripts/build.ps1; keep installed applications as runtime artifacts.
Before publishing, exclude local experiment screenshots, JSON, personal paths,
credentials, vendor runtimes and build artifacts. Read docs/maintenance.md.

This is the user's reusable local Labelme optimizer. Reuse `start.py --cli` and
`bone_optimizer.service.process_file`; do not reproduce annotation algorithms in
ad-hoc scripts. Read 使用说明.md for exact semantics and installed paths.

Protect manually authored inputs. Default outputs are separate editable Polygon
JSON files. Preserve manual edits on reimport, including generated shapes and
ignore regions. Never silently skip generated_by shapes. All class masks must
match after polygon round-trip. Do not remove holes or apply unrequested smoothing.

Changes to core processing require `tests/test_core.py` and the installed Labelme
open/edit/save/reopen check. Keep GUI and CLI on the same service. Output artifacts
must remain compatible with Labelme 6.3.1 and current Python 3.11 bone_label runtime.
The private vendor OpenCV dependency must not upgrade the user's Conda environments.
