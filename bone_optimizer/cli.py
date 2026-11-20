"""Stable machine-callable interface, shared with the desktop application."""
import argparse
import json
from pathlib import Path

from .service import plan_files, process_file


def main():
    parser = argparse.ArgumentParser(description='骨样标注优化：输出可编辑 Labelme JSON，保留原稿。')
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', required=True, type=Path, help='输出目录')
    parser.add_argument('--threshold', type=int, default=100, help='原图像素面积，<= 阈值转 ignore；0 关闭')
    parser.add_argument('--mode', choices=['auto', 'bone', 'none_bone', 'explicit'], default='auto')
    parser.add_argument('--image-root', type=Path)
    parser.add_argument('--report', type=Path, help='可选汇总报告（不覆盖已有文件）')
    args = parser.parse_args()
    if args.threshold < 0:
        parser.error('threshold 不能为负数')
    root = args.input.resolve() if args.input.is_dir() else None
    if root and (args.output.resolve() == root or args.output.resolve().is_relative_to(root)):
        parser.error('批处理输出目录必须放在输入目录以外')
    sources = sorted(root.rglob('*.json')) if root else [args.input]
    if not sources:
        parser.error('输入目录没有 JSON 文件')
    jobs = plan_files(sources, args.output, root)
    reports, failures = [], 0
    for source, target in jobs:
        try:
            written, details = process_file(source, target, args.threshold, args.mode, args.image_root)
            report = {'input': str(source), 'output': str(written), 'status': 'success', **details}
        except Exception as exc:
            report = {'input': str(source), 'status': 'error', 'error': str(exc)}
            failures += 1
        reports.append(report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
    if args.report:
        with args.report.open('x', encoding='utf-8') as handle:
            json.dump(reports, handle, ensure_ascii=False, indent=2)
    return 1 if failures else 0
