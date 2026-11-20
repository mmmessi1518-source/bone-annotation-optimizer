"""Launch GUI by default; --cli exposes the same core for repeatable automation."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor'))
os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')

if __name__ == '__main__':
    if '--self-test' in sys.argv:
        from bone_optimizer.selfcheck import main
        raise SystemExit(main())
    if '--cli' in sys.argv:
        sys.argv.remove('--cli')
        from bone_optimizer.cli import main
        raise SystemExit(main())
    try:
        from bone_optimizer.gui import main
        raise SystemExit(main())
    except Exception:
        import traceback
        log = Path(os.environ.get('LOCALAPPDATA', str(ROOT))) / 'BoneAnnotationOptimizer'
        log.mkdir(parents=True, exist_ok=True)
        (log / 'startup-error.log').write_text(traceback.format_exc(), encoding='utf-8')
        try:
            from PyQt5.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication([])
            QMessageBox.critical(None, '启动失败', f'工具启动失败，详情已保存到：\n{log / "startup-error.log"}')
        except Exception:
            pass
        raise
