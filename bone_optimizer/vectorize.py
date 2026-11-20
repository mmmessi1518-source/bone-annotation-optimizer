"""Pixel-exact, editable polygon export; no base64 masks or bounding boxes."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw

from . import __version__
from .annotation_io import NAMES, region_from_shapes

MAX_SHAPES = 6000
MAX_VERTICES = 300000


def _draw(points, size):
    image = Image.new('1', size)
    ImageDraw.Draw(image).polygon([tuple(p) for p in points], fill=1, outline=1)
    return np.asarray(image)


def _thin_polygons(contour):
    """Give zero-area pixel lines real editable area without adding pixels."""
    x, y, w, h = cv2.boundingRect(contour)
    p = contour.reshape(-1, 2)-[x, y]
    if len(p) < 3:
        p = np.concatenate((p, np.repeat(p[-1:], 3-len(p), axis=0)))
    pixels = _draw(p, (w, h))
    active, output = {}, []
    for row in range(h+1):
        runs = []
        if row < h:
            edges = np.flatnonzero(np.diff(np.pad(pixels[row].astype(np.int8), (1,1))))
            runs = list(zip(edges[::2], edges[1::2]))
        keys = set(runs)
        for span in list(active):
            if span not in keys:
                begin = active.pop(span)
                left, right = span
                output.append([[x+int(left), y+begin], [x+int(right)-0.51, y+begin],
                               [x+int(right)-0.51, y+row-0.51], [x+int(left), y+row-0.51]])
        for span in runs:
            active.setdefault(span, row)
    return output


def _compact_exact(contour):
    x, y, w, h = cv2.boundingRect(contour)
    points = contour.reshape(-1, 2)
    original = _draw(points-[x, y], (w, h))
    # Approximation is accepted ONLY when the Labelme rasterization is identical.
    for epsilon in (1.0, 0.75, 0.5, 0.35):
        candidate = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
        if len(candidate) >= 3 and len(candidate) < len(points):
            if np.array_equal(original, _draw(candidate-[x, y], (w, h))):
                return candidate.tolist()
    return points.tolist()


def editable_polygons(pixels):
    """Cut through holes on integer pixel boundaries, trace each disjoint piece.

    CHAIN_APPROX_SIMPLE removes only horizontal/vertical/45-degree collinear
    points. Its fill agrees with Pillow at integer coordinates. Splitting uses
    half-open array slices, so adjacent pieces never share a classified pixel.
    """
    stack = [(pixels, 0, 0)]
    output = []
    vertices = 0
    while stack:
        tile, ox, oy = stack.pop()
        contours, hierarchy = cv2.findContours(tile.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if hierarchy is None:
            continue
        holes = [i for i, entry in enumerate(hierarchy[0]) if entry[3] >= 0]
        if holes:
            # A balanced cut avoids recursion and works for multiple nested holes.
            hole = contours[holes[len(holes)//2]].reshape(-1, 2)
            left, right = int(hole[:, 0].min()), int(hole[:, 0].max())
            cut = (left+right)//2
            if not 0 < cut < tile.shape[1]:
                raise ValueError('无法安全分解有孔区域；未写出文件。')
            stack.append((tile[:, cut:], ox+cut, oy))
            stack.append((tile[:, :cut], ox, oy))
            continue
        for contour in contours:
            if cv2.contourArea(contour) == 0:
                pieces = _thin_polygons(contour)
            else:
                pieces = [_compact_exact(contour)]
            for points in pieces:
                shifted = [[px+ox, py+oy] for px, py in points]
                output.append(shifted)
                vertices += len(shifted)
        if len(output) > MAX_SHAPES or vertices > MAX_VERTICES:
            raise ValueError('图形碎片过多，超过安全导出上限。请提高小区域阈值或检查原始标注。')
    return output


def export_document(result, destination: Path):
    start = time.perf_counter()
    annotation = result.prepared.annotation
    document = deepcopy(annotation.document)
    # Preserve the user-authored specimen helper, but do not retain stale class
    # polygons, masks, or per-shape generated_by filters from earlier tools.
    specimen_shapes = [s for s in document['shapes'] if s['label'] == 'specimen']
    if any(s.get('shape_type') != 'polygon' for s in specimen_shapes):
        specimen_shapes = [make_shape('specimen', p) for p in editable_polygons(result.prepared.specimen)]
    shapes = specimen_shapes
    for value, label in NAMES.items():
        shapes.extend(make_shape(label, p) for p in editable_polygons(result.mask == value))
    if len(shapes) > MAX_SHAPES or sum(len(s['points']) for s in shapes) > MAX_VERTICES:
        raise ValueError('输出图形复杂度过高，请检查原稿或增大小区域阈值。')
    document['shapes'] = shapes
    document['version'] = '6.3.1'
    if annotation.image_path:
        try:
            document['imagePath'] = os.path.relpath(annotation.image_path, destination.parent).replace('\\', '/')
        except ValueError:  # Cross-drive relative paths are undefined on Windows.
            document['imagePath'] = str(annotation.image_path)
        if not annotation.use_embedded:
            document['imageData'] = None
    elif annotation.use_embedded:
        document['imagePath'] = Path(str(document.get('imagePath') or 'embedded.png')).name
    # Test each label independently, so a later polygon cannot conceal an error.
    for value, label in NAMES.items():
        actual = region_from_shapes([s for s in shapes if s['label'] == label], annotation.size)
        if not np.array_equal(actual, result.mask == value):
            raise ValueError(f'{label} 多边形回读校验失败，已停止导出以保护标注。')
    report = {**result.report, 'output_shapes': len(shapes),
              'output_vertices': sum(len(s['points']) for s in shapes),
              'roundtrip_pixel_differences': 0,
              'vectorize_and_validate_seconds': round(time.perf_counter()-start, 3)}
    document['bone_optimizer'] = {
        'version': __version__, 'created_at': datetime.now(timezone.utc).isoformat(),
        'source_sha256': annotation.digest, 'source_name': annotation.path.name,
        'format': 'editable-polygons', 'report': report,
    }
    return document, report


def make_shape(label, points):
    return {'label': label, 'points': points, 'group_id': None,
            'description': '', 'shape_type': 'polygon', 'flags': {}, 'mask': None}
