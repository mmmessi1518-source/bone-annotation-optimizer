from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageOps

NAMES = {0: 'background', 1: 'bone', 2: 'none_bone', 255: 'ignore'}
COLORS = {0: (180, 160, 50), 1: (224, 66, 73), 2: (40, 174, 100), 255: (70, 110, 240)}
LABELS = set(NAMES.values()) | {'specimen'}
MAX_PIXELS = 80_000_000


@dataclass
class Annotation:
    path: Path
    document: dict
    image_path: Path | None
    image: Image.Image
    digest: str
    warnings: list[str]
    use_embedded: bool = False

    @property
    def size(self):
        return self.image.size


def locate_image(source: Path, image_ref: str, image_root: Path | None = None):
    reference = Path(image_ref.replace('\\', '/'))
    exact = (source.parent / reference).resolve()
    if exact.is_file():
        return exact, False
    # A moved annotation directory often introduces one more parent component.
    candidates = set()
    tail = [part for part in reference.parts if part not in ('..', '.', reference.anchor)]
    for parent in source.parents:
        for candidate in (parent / reference, parent.joinpath(*tail)):
            if candidate.is_file():
                candidates.add(candidate.resolve())
    if len(candidates) == 1:
        return candidates.pop(), True
    if not candidates and image_root and image_root.is_dir():
        candidates = {p.resolve() for p in image_root.rglob(reference.name) if p.is_file()}
    if len(candidates) == 1:
        return candidates.pop(), True
    if len(candidates) > 1:
        raise ValueError(f'找到多张同名照片，无法确定对应关系：{reference.name}。请修正 JSON 的 imagePath。')
    return None, False


def load_annotation(path: Path, image_root: Path | None = None):
    path = path.resolve()
    raw = path.read_bytes()
    document = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(document, dict) or not isinstance(document.get('shapes'), list):
        raise ValueError('文件不是 Labelme 标注 JSON（缺少 shapes）。')
    width, height = document.get('imageWidth'), document.get('imageHeight')
    if not all(isinstance(n, int) and n > 0 for n in (width, height)) or width * height > MAX_PIXELS:
        raise ValueError('图像尺寸无效，或超过本工具的 8000 万像素处理上限。')
    image_path, repaired = locate_image(path, str(document.get('imagePath') or ''), image_root)
    warnings = []
    embedded = bool(document.get('imageData'))
    if embedded:
        # Labelme gives embedded imageData precedence over the external file.
        with Image.open(BytesIO(base64.b64decode(document['imageData'], validate=True))) as original:
            image = original.convert('RGB')
        warnings.append('使用 JSON 内嵌照片；导出会保留内嵌照片。')
    elif image_path:
        with Image.open(image_path) as original:
            image = ImageOps.exif_transpose(original).convert('RGB')
        if repaired:
            warnings.append('原照片引用已失效；已唯一定位照片，导出时修正引用，原稿不变。')
    else:
        raise ValueError('找不到对应照片。请设置「照片目录」，或在 Labelme 中重新保存正确的图片引用。')
    if image.size != (width, height):
        raise ValueError(f'照片尺寸 {image.size} 与 JSON 尺寸 {(width, height)} 不符。')
    if any(s.get('shape_type') == 'mask' for s in document['shapes']):
        warnings.append('输入包含旧版 Mask；导出会转换为可编辑的多边形。')
    if document.get('bone_optimizer'):
        warnings.append('正在处理已优化文件：保留其中的人工修改和 ignore；需要恢复细节时请重新导入手动原稿。')
    return Annotation(path, document, image_path, image, hashlib.sha256(raw).hexdigest(), warnings, embedded)


def region_from_shapes(shapes, size):
    """Match Labelme/Pillow rasterization, including polygon outline pixels."""
    raster = Image.new('1', size)
    draw = ImageDraw.Draw(raster)
    for shape in shapes:
        kind = shape.get('shape_type') or 'polygon'
        points = np.asarray(shape.get('points', []), dtype=float)
        if points.ndim != 2 or points.shape[1:] != (2,) or not np.isfinite(points).all():
            raise ValueError('图形含无效坐标。')
        xy = [tuple(p) for p in points]
        if kind in ('polygon', 'oriented_rectangle'):
            if len(xy) < 3:
                raise ValueError('多边形至少需要 3 个节点。')
            draw.polygon(xy, outline=1, fill=1)
        elif kind == 'rectangle' and len(xy) == 2:
            (x0, y0), (x1, y1) = xy
            draw.rectangle((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), outline=1, fill=1)
        elif kind == 'circle' and len(xy) == 2:
            (cx, cy), (px, py) = xy
            radius = math.hypot(px-cx, py-cy)
            draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), outline=1, fill=1)
        elif kind == 'mask' and len(xy) == 2:
            (x0, y0), (x1, y1) = points.astype(int)
            if not (0 <= x0 <= x1 < size[0] and 0 <= y0 <= y1 < size[1]):
                raise ValueError('Mask 范围越过图像边界。')
            with Image.open(BytesIO(base64.b64decode(shape['mask'], validate=True))) as image:
                a = np.asarray(image)
                if a.ndim != 2 or a.shape != (y1-y0+1, x1-x0+1):
                    raise ValueError('Mask 尺寸与边框不一致。')
                piece = Image.fromarray((a != 0).astype(np.uint8)*255).convert('1')
            raster.paste(1, (int(x0), int(y0), int(x1)+1, int(y1)+1), piece)
        else:
            raise ValueError(f'不支持区域类型 {kind}。请用闭合多边形标注组织。')
    return np.asarray(raster, dtype=bool)


def assert_source_unchanged(annotation):
    if hashlib.sha256(annotation.path.read_bytes()).hexdigest() != annotation.digest:
        raise ValueError('原 JSON 在处理期间被修改，请重新导入后再导出。')


def write_new_json(document, destination: Path, source: Path):
    destination = destination.resolve()
    if destination == source.resolve():
        raise ValueError('输出不能覆盖输入原稿，请选择优化版目录。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent,
                                         suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(document, handle, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        # Syntax validation is additional to the semantic round-trip check.
        json.loads(temporary.read_text('utf-8'))
        # On Windows rename fails when the destination exists. Do not reserve
        # an empty JSON: a crash must never leave a partial annotation behind.
        base, number = destination, 1
        while True:
            try:
                if os.name == 'nt':
                    os.rename(temporary, destination)
                else:
                    os.link(temporary, destination)
                break
            except FileExistsError:
                number += 1
                destination = base.with_name(f'{base.stem}__{number}{base.suffix}')
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return destination
