from __future__ import annotations

from pathlib import Path
import time

from .annotation_io import load_annotation, assert_source_unchanged, write_new_json
from .core import prepare, optimize
from .vectorize import export_document


def export_result(result, destination):
    start = time.perf_counter()
    annotation = result.prepared.annotation
    destination = Path(destination)
    if destination.resolve() == annotation.path.resolve():
        raise ValueError('优化输出不能与手动原稿相同。')
    if annotation.image_path and annotation.image_path.anchor.casefold() != destination.resolve().anchor.casefold():
        raise ValueError(f'当前 Labelme 版本无法跨磁盘保存编辑。请把优化版放在照片所在的 {annotation.image_path.anchor} 磁盘。')
    assert_source_unchanged(annotation)
    document, report = export_document(result, destination)
    assert_source_unchanged(annotation)
    written = write_new_json(document, destination, annotation.path)
    report['export_seconds'] = round(time.perf_counter()-start, 3)
    return written, report


def process_file(source, destination, threshold=100, mode='auto', image_root=None):
    start = time.perf_counter()
    annotation = load_annotation(Path(source), Path(image_root) if image_root else None)
    result = optimize(prepare(annotation, mode), threshold)
    written, report = export_result(result, Path(destination))
    report['total_seconds'] = round(time.perf_counter()-start, 3)
    return written, report


def plan_files(sources, output_root, input_root=None):
    """Preserve relative directories; reject ambiguous duplicate output names."""
    output_root = Path(output_root).resolve()
    input_root = Path(input_root).resolve() if input_root else None
    jobs, seen = [], set()
    for source in sources:
        source = Path(source).resolve()
        relative = source.relative_to(input_root) if input_root else Path(source.name)
        target = output_root / relative
        if source == target.resolve():
            raise ValueError('输出目录与输入目录相同，请选择优化版文件夹。')
        key = str(target).casefold()
        if key in seen:
            raise ValueError('所选文件有同名路径冲突，请通过「导入文件夹」保留目录层级。')
        seen.add(key)
        jobs.append((source, target))
    return jobs
