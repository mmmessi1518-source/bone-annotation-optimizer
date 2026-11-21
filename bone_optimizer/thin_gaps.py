"""Find narrow inferred strips between different raster classes."""
import cv2
import numpy as np

DEFAULT_THIN_GAP_WIDTH = 4
MAX_THIN_GAP_WIDTH = 16


def _first_other_label(padded, tissue, margin, height, width, dy, dx, steps):
    distance = np.zeros(tissue.shape, dtype=np.uint8)
    neighbor = np.zeros(tissue.shape, dtype=np.uint8)
    pending = tissue.copy()
    for step in range(1, steps + 1):
        y, x = margin + step * dy, margin + step * dx
        labels = padded[y:y+height, x:x+width]
        found = pending & (labels != 1)
        distance[found] = step
        neighbor[found] = labels[found]
        pending[found] = False
    return distance, neighbor


def thin_gap_roi(mask, tissue_value, max_width):
    """Return a bounding slice and a boolean mask of uncertain tissue pixels.

    A pixel qualifies when a short run of that tissue ends at two different
    classes. Measure across horizontal, vertical and diagonal directions.
    A same-class neighbor on both ends does not identify a class interface.
    """
    x, y, width, height = cv2.boundingRect((mask == tissue_value).astype(np.uint8))
    if not width or not height:
        return None
    # Include the neighboring classes around the bounding box.
    x0, y0 = max(0, x-1), max(0, y-1)
    x1, y1 = x+width+1, y+height+1
    region = np.s_[y0:y1, x0:x1]
    classes = mask[region].copy()
    tissue = classes == tissue_value
    # Normalize the searched tissue to 1 and the other tissue to 2.
    classes[(classes == 1) | (classes == 2)] = 2
    classes[tissue] = 1
    height, width = tissue.shape
    padded = np.pad(classes, max_width, constant_values=0)
    gaps = np.zeros(tissue.shape, dtype=bool)
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        # The span of N pixel centers is (N-1) steps, plus one pixel.
        steps = int((max_width-1) / np.hypot(dy, dx)) + 1
        front, front_label = _first_other_label(padded, tissue, max_width, height, width, dy, dx, steps)
        back, back_label = _first_other_label(padded, tissue, max_width, height, width, -dy, -dx, steps)
        gaps |= ((front > 0) & (back > 0) & (front + back - 1 <= steps)
                 & (front_label != back_label))
    return region, gaps
