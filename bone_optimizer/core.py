from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import time

import cv2
import numpy as np

from .annotation_io import Annotation, LABELS, NAMES, region_from_shapes

cv2.setNumThreads(2)
MODE_NAMES = {'auto': '自动判断', 'bone': '已画 bone，补出 none_bone',
              'none_bone': '已画 none_bone，补出 bone', 'explicit': '两类都已画，冲突和空隙转 ignore'}


@dataclass
class Prepared:
    annotation: Annotation
    base: np.ndarray
    specimen: np.ndarray
    components: np.ndarray
    areas: np.ndarray
    classes: np.ndarray
    original: np.ndarray
    report: dict


@dataclass
class Result:
    prepared: Prepared
    mask: np.ndarray
    report: dict


def prepare(annotation: Annotation, mode='auto') -> Prepared:
    start = time.perf_counter()
    if mode not in MODE_NAMES:
        raise ValueError('未知处理模式。')
    shapes = annotation.document['shapes']
    counts = Counter(s.get('label') for s in shapes)
    unknown = set(counts) - LABELS
    if unknown:
        raise ValueError(f'发现未知标签 {sorted(map(str, unknown))}；请使用 bone、none_bone、specimen、background、ignore。')
    regions = {label: region_from_shapes([s for s in shapes if s['label'] == label], annotation.size)
               for label in LABELS}
    original = np.full((annotation.size[1], annotation.size[0]), 254, dtype=np.uint8)
    original[regions['specimen']] = 3
    for value, name in NAMES.items():
        original[regions[name]] = value
    specimen = regions['specimen']
    if not specimen.any():
        raise ValueError('缺少有效 specimen 外轮廓，请先画出整个样品。')
    bone, nonbone = regions['bone'] & specimen, regions['none_bone'] & specimen
    ignore = regions['ignore'] & specimen
    if np.any(regions['background'] & specimen & ~ignore):
        raise ValueError('background 与 specimen 内部重叠，请检查外轮廓和背景图形。')
    has_bone, has_nonbone = bool(bone.any()), bool(nonbone.any())
    if mode == 'auto':
        if counts['bone'] and counts['none_bone']:
            mode = 'explicit'
        elif has_bone:
            mode = 'bone'
        elif has_nonbone:
            mode = 'none_bone'
        elif np.all(ignore[specimen]):
            mode = 'explicit'
        else:
            raise ValueError('样品内部没有有效 bone 或 none_bone 标注，无法推导类别。')
    checked_existing_complement = False
    if mode in ('bone', 'none_bone'):
        required = has_bone if mode == 'bone' else has_nonbone
        if not required:
            raise ValueError('所选相减模式与标注不符：样品内缺少指定的一类组织。')
        source = bone if mode == 'bone' else nonbone
        existing_complement = nonbone if mode == 'bone' else bone
        if existing_complement.any():
            expected_complement = specimen & ~source & ~ignore
            differences = int(np.count_nonzero((existing_complement & ~ignore) ^ expected_complement))
            if differences:
                raise ValueError(
                    f'现有另一类组织与所选相减结果有 {differences:,} 个像素不一致。'
                    '请使用「自动判断」或「两类都已画」模式复核，'
                    '以免覆盖手动修改。'
                )
            checked_existing_complement = True
    conflicts, gaps = np.zeros_like(specimen), np.zeros_like(specimen)
    if mode == 'explicit':
        conflicts = bone & nonbone & ~ignore
        gaps = specimen & ~(bone | nonbone | ignore)
        ignore |= conflicts | gaps
    elif mode == 'bone':
        nonbone = specimen & ~bone
    else:
        bone = specimen & ~nonbone
    base = np.zeros(specimen.shape, dtype=np.uint8)
    base[bone] = 1
    base[nonbone] = 2
    base[ignore] = 255
    component_ids = np.zeros(base.shape, dtype=np.int32)
    area_parts, class_parts = [np.array([0], dtype=np.int64)], [np.array([0], dtype=np.uint8)]
    offset = 0
    for value in (1, 2):
        count, labels, stats, _ = cv2.connectedComponentsWithStats((base == value).astype(np.uint8), connectivity=8)
        positive = labels > 0
        component_ids[positive] = labels[positive] + offset
        area_parts.append(stats[1:, cv2.CC_STAT_AREA].astype(np.int64))
        class_parts.append(np.full(count-1, value, dtype=np.uint8))
        offset += count-1
    warnings = list(annotation.warnings)
    if checked_existing_complement:
        warnings.append('现有另一类组织与相减结果逐像素一致，已核对并允许按所选模式重新计算。')
    if conflicts.any() or gaps.any():
        warnings.append('两类显式标注中存在交叠或未覆盖位置，已转 ignore；请查看改动高亮。')
    report = {'mode': mode, 'mode_description': MODE_NAMES[mode], 'input_shape_counts': dict(counts),
              'checked_existing_complement': checked_existing_complement,
              'clipped_tissue_pixels': int(((regions['bone'] | regions['none_bone']) & ~specimen).sum()),
              'overlap_to_ignore_pixels': int(conflicts.sum()), 'gap_to_ignore_pixels': int(gaps.sum()),
              'outside_ignore_to_background_pixels': int((regions['ignore'] & ~specimen).sum()),
              'warnings': warnings, 'prepare_seconds': round(time.perf_counter()-start, 3)}
    return Prepared(annotation, base, specimen, component_ids, np.concatenate(area_parts), np.concatenate(class_parts), original, report)


def optimize(prepared: Prepared, threshold=100) -> Result:
    start = time.perf_counter()
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 0:
        raise ValueError('小区域阈值须为非负整数；0 表示关闭。')
    small = (prepared.areas > 0) & (prepared.areas <= threshold)
    mask = prepared.base.copy()
    mask[small[prepared.components]] = 255
    changed = {NAMES[v]: {'components': int(np.count_nonzero(small & (prepared.classes == v))),
                         'pixels': int(prepared.areas[small & (prepared.classes == v)].sum())}
               for v in (1, 2)}
    report = {**prepared.report, 'threshold_original_pixels': threshold, 'connectivity': 8,
              'small_regions_to_ignore': changed,
              'pixel_counts': {name: int(np.count_nonzero(mask == v)) for v, name in NAMES.items()},
              'filter_seconds': round(time.perf_counter()-start, 3)}
    return Result(prepared, mask, report)
