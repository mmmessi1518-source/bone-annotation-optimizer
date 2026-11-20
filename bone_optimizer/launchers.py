"""Locate a separately installed Labelme without depending on machine paths."""
from pathlib import Path
import importlib.util
import shutil
import sys


def find_labelme_launcher(configured=''):
    if configured and Path(configured).is_file():
        return Path(configured)
    command = shutil.which('labelme')
    if command:
        return Path(command)
    if not getattr(sys, 'frozen', False) and importlib.util.find_spec('labelme'):
        return Path(sys.executable).with_name('pythonw.exe') if sys.platform == 'win32' else Path(sys.executable)
    # Discover the commonly used local Conda environment without storing its
    # username or absolute path in source or in the distributed application.
    candidate = Path.home()/'miniconda3/envs/bone_label/pythonw.exe'
    return candidate if candidate.is_file() else None


def labelme_command(launcher, annotation):
    launcher = Path(launcher)
    if getattr(sys, 'frozen', False) and launcher.resolve() == Path(sys.executable).resolve():
        raise ValueError('请选择 Labelme 的程序或其 Python 解释器，不能选择优化工具本身。')
    if launcher.stem.lower() in ('python', 'pythonw', 'python3', 'python3.11'):
        return [str(launcher), '-s', '-m', 'labelme', str(annotation)]
    return [str(launcher), str(annotation)]
