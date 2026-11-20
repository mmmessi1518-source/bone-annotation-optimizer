from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import numpy as np
from PIL import Image
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings, QUrl
from PyQt5.QtGui import QColor, QImage, QPixmap, QDesktopServices, QIcon
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QLineEdit, QSpinBox, QComboBox, QCheckBox,
    QListWidget, QListWidgetItem, QGraphicsView, QGraphicsScene, QFrame,
    QSplitter, QPlainTextEdit, QProgressBar, QMessageBox, QGroupBox, QScrollArea,
)

from . import __version__
from .annotation_io import load_annotation, COLORS
from .core import prepare, optimize, MODE_NAMES
from .service import plan_files, export_result, process_file
from .launchers import find_labelme_launcher, labelme_command

DEFAULT_INPUT = Path.home()


class Worker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(object)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.done.emit(self.operation(self.progress.emit))
        except Exception as exc:
            self.failed.emit(str(exc))


class Preview(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setDragMode(self.ScrollHandDrag)
        self.setTransformationAnchor(self.AnchorUnderMouse)
        self.setBackgroundBrush(QColor('#e9eef3'))
        self.setMinimumSize(360, 280)
        self.item = None
        self.image_key = None

    def show_image(self, pixels, key):
        pixels = np.ascontiguousarray(pixels)
        h, w, _ = pixels.shape
        image = QImage(pixels.data, w, h, pixels.strides[0], QImage.Format_RGB888).copy()
        self.scene().clear()
        self.item = self.scene().addPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(self.item.boundingRect())
        if key != self.image_key:
            self.fit()
        self.image_key = key

    def fit(self):
        if self.item:
            self.fitInView(self.item, Qt.KeepAspectRatio)

    def wheelEvent(self, event):
        if not self.item:
            return
        factor = 1.22 if event.angleDelta().y() > 0 else 1/1.22
        scale = self.transform().m11() * factor
        if 0.03 < scale < 16:
            self.scale(factor, factor)


def render_preview(result, mode, layers, full_resolution=False):
    image = result.prepared.annotation.image.copy()
    if not full_resolution:
        image.thumbnail((1800, 1400), Image.Resampling.LANCZOS)
    rgb = np.asarray(image).copy()
    if mode == '原始照片':
        return rgb
    if mode == '原始标注':
        mask = result.prepared.original
    else:
        mask = result.mask
    sampled = np.asarray(Image.fromarray(mask).resize(image.size, Image.Resampling.NEAREST))
    if mode == '改动高亮':
        # This includes inferred classes, filled gaps/conflicts, and tiny regions.
        # Background outside the specimen is intentionally not highlighted.
        changed = (result.mask != result.prepared.original) & result.prepared.specimen
        selected = np.asarray(Image.fromarray(changed).resize(image.size, Image.Resampling.NEAREST))
        rgb[selected] = (rgb[selected]*0.30 + np.array([255, 192, 20])*0.70).astype(np.uint8)
    else:
        colors = {**COLORS, 3: (159, 58, 185)}
        for value, color in colors.items():
            if value not in layers and value != 3:
                continue
            selected = sampled == value
            rgb[selected] = (rgb[selected]*0.57 + np.array(color)*0.43).astype(np.uint8)
    return rgb


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings('BoneResearch', 'AnnotationOptimizer')
        self.sources = []
        self.input_root = None
        self.prepared = None
        self.result = None
        self.last_output = None
        self.worker = None
        self.cancel_event = threading.Event()
        self.setWindowTitle(f'骨样标注优化工具  {__version__}')
        self.resize(1330, 890)
        self.setMinimumSize(1030, 730)
        self.setAcceptDrops(True)
        icon = Path(__file__).parent.parent / 'app.ico'
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self._build()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.preview_current)
        self.threshold.valueChanged.connect(self._schedule)
        self.mode.currentIndexChanged.connect(self._schedule)
        self.view_mode.currentIndexChanged.connect(self._schedule)
        for check in self.layers.values():
            check.toggled.connect(self._schedule)

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(13)
        title = QLabel('骨样标注优化工具')
        title.setObjectName('title')
        subtitle = QLabel('手动原稿 → 规则优化 → 可编辑 JSON    ·    本地处理 / 原稿保留 / 导出前逐像素核对')
        subtitle.setObjectName('subtitle')
        layout.addWidget(title)
        layout.addWidget(subtitle)
        split = QSplitter(Qt.Horizontal)
        layout.addWidget(split, 1)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.addWidget(QLabel('1  导入手动标注'))
        row = QHBoxLayout()
        self.add_files_button = QPushButton('添加 JSON')
        self.add_folder_button = QPushButton('导入文件夹')
        row.addWidget(self.add_files_button)
        row.addWidget(self.add_folder_button)
        left_layout.addLayout(row)
        self.add_files_button.clicked.connect(self.choose_files)
        self.add_folder_button.clicked.connect(self.choose_folder)
        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(125)
        self.file_list.setMaximumHeight(170)
        self.file_list.setMaximumHeight(130)
        self.file_list.currentRowChanged.connect(self.selection_changed)
        left_layout.addWidget(self.file_list, 1)
        self.file_count = QLabel('可拖入 JSON 或文件夹；支持勾选后批量导出')
        self.file_count.setWordWrap(True)
        left_layout.addWidget(self.file_count)
        buttons = QHBoxLayout()
        self.select_all = QPushButton('全选')
        self.clear_button = QPushButton('清空')
        buttons.addWidget(self.select_all)
        buttons.addWidget(self.clear_button)
        self.select_all.clicked.connect(self.check_all)
        self.clear_button.clicked.connect(self.clear_files)
        left_layout.addLayout(buttons)
        box = QGroupBox('2  处理规则')
        rules = QVBoxLayout(box)
        self.mode = QComboBox()
        self.mode.setMinimumHeight(34)
        self.mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mode.setMinimumContentsLength(14)
        for key, value in MODE_NAMES.items():
            self.mode.addItem(value, key)
        rules.addWidget(QLabel('类别推导'))
        rules.addWidget(self.mode)
        threshold_label = QLabel('小独立区域 → ignore\n面积 ≤ 原图像素数；0 表示关闭')
        threshold_label.setWordWrap(True)
        rules.addWidget(threshold_label)
        self.threshold = QSpinBox()
        self.threshold.setRange(0, 10_000_000)
        self.threshold.setValue(int(self.settings.value('threshold', 100)))
        self.threshold.setSuffix(' 像素')
        self.threshold.setSpecialValueText('关闭小区域过滤')
        self.threshold.setToolTip('8 连通；bone 与 none_bone 使用相同阈值。0=关闭。调节后始终从当前导入原稿重新计算。')
        rules.addWidget(self.threshold)
        note = QLabel('默认 100 只是起点，可按预览调整。\n与大区域相连的细缝不会被此阈值删除。')
        note.setWordWrap(True)
        note.setMinimumHeight(44)
        note.setObjectName('muted')
        rules.addWidget(note)
        left_layout.addWidget(box)
        output = QGroupBox('3  导出位置')
        out_layout = QVBoxLayout(output)
        self.output = QLineEdit(str(self.settings.value('output', '')))
        self.output.setPlaceholderText('导入后选择优化版文件夹')
        self.output.setToolTip('保留输入子目录；已有同名文件时另存 __2、__3，不覆盖。')
        self.output_button = QPushButton('选择优化版文件夹…')
        self.output_button.clicked.connect(self.choose_output)
        out_layout.addWidget(self.output)
        out_layout.addWidget(self.output_button)
        self.image_root = QLineEdit(str(self.settings.value('images', '')))
        self.image_button = QPushButton('照片目录（引用失效时查找）…')
        self.image_button.clicked.connect(self.choose_images)
        self.image_options = QCheckBox('手动指定照片搜索目录')
        out_layout.addWidget(self.image_options)
        out_layout.addWidget(self.image_root)
        out_layout.addWidget(self.image_button)
        self.image_root.hide()
        self.image_button.hide()
        self.image_options.toggled.connect(self.image_root.setVisible)
        self.image_options.toggled.connect(self.image_button.setVisible)
        left_layout.addWidget(output)
        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setFrameShape(QFrame.NoFrame)
        self.left_scroll.setWidget(left)
        self.left_scroll.setMinimumWidth(340)
        self.left_scroll.setMaximumWidth(420)
        split.addWidget(self.left_scroll)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 0, 0, 0)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('预览'))
        self.view_mode = QComboBox()
        self.view_mode.addItems(['优化预览', '原始标注', '原始照片', '改动高亮'])
        toolbar.addWidget(self.view_mode)
        self.refresh_button = QPushButton('更新预览')
        self.refresh_button.clicked.connect(self.preview_current)
        toolbar.addWidget(self.refresh_button)
        fit = QPushButton('适应窗口')
        fit.clicked.connect(lambda: self.preview.fit())
        toolbar.addWidget(fit)
        self.full_resolution = QCheckBox('原图精度')
        self.full_resolution.setToolTip('勾选后按原始像素预览，可放大复核细小区域。默认缩略预览更快。')
        self.full_resolution.toggled.connect(self._schedule)
        toolbar.addWidget(self.full_resolution)
        toolbar.addStretch()
        right_layout.addLayout(toolbar)
        layer_row = QHBoxLayout()
        self.layers = {}
        for value, caption in [(1, 'bone'), (2, 'none_bone'), (255, 'ignore'), (0, 'background')]:
            check = QCheckBox(caption)
            check.setChecked(True)
            color = COLORS[value]
            check.setStyleSheet(f'color: rgb{color}; font-weight: 600;')
            self.layers[value] = check
            layer_row.addWidget(check)
        layer_row.addStretch()
        right_layout.addLayout(layer_row)
        self.preview = Preview()
        right_layout.addWidget(self.preview, 1)
        hint = QLabel('滚轮缩放 · 按住鼠标拖动平移 · 黄色高亮表示推导或调整位置 · 图层勾选只影响预览')
        hint.setObjectName('muted')
        right_layout.addWidget(hint)
        self.summary = QLabel('导入一张 JSON 开始。照片仍使用原文件，优化结果不重复复制照片。')
        self.summary.setWordWrap(True)
        self.summary.setMinimumHeight(70)
        self.summary.setObjectName('summary')
        right_layout.addWidget(self.summary)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(130)
        self.details.setPlaceholderText('这里显示处理模式、调整面积和需复核的位置。')
        right_layout.addWidget(self.details)
        split.addWidget(right)
        split.setSizes([390, 910])
        bottom = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        bottom.addWidget(self.progress, 1)
        self.cancel_button = QPushButton('停止批次')
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_event.set)
        bottom.addWidget(self.cancel_button)
        self.open_button = QPushButton('用 Labelme 检查结果')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_labelme)
        bottom.addWidget(self.open_button)
        self.labelme_button = QPushButton('设置 Labelme')
        self.labelme_button.clicked.connect(self.choose_labelme)
        bottom.addWidget(self.labelme_button)
        self.export_one = QPushButton('导出当前 JSON')
        self.export_one.clicked.connect(self.export_current)
        bottom.addWidget(self.export_one)
        self.export_batch = QPushButton('导出勾选文件')
        self.export_batch.setObjectName('primary')
        self.export_batch.clicked.connect(self.export_checked)
        bottom.addWidget(self.export_batch)
        layout.addLayout(bottom)
        self.statusBar().showMessage('就绪 · 输出全部为 Polygon；照片分辨率保持不变')
        self.controls = [self.add_files_button, self.add_folder_button, self.file_list,
                         self.select_all, self.clear_button, self.mode, self.threshold,
                         self.output, self.output_button, self.image_root, self.image_button,
                         self.view_mode, self.full_resolution, self.refresh_button, self.export_one, self.export_batch] + list(self.layers.values())

    def busy(self):
        return self.worker is not None

    def run_work(self, operation, success, batch=False):
        if self.busy():
            return
        self.timer.stop()
        for widget in self.controls:
            widget.setEnabled(False)
        self.cancel_event.clear()
        self.cancel_button.setEnabled(batch)
        self.progress.setRange(0, 0)
        self.statusBar().showMessage('正在处理…')
        self.worker = Worker(operation, self)
        self.worker.done.connect(success)
        self.worker.failed.connect(self.show_error)
        self.worker.progress.connect(self.batch_progress)
        self.worker.finished.connect(self.work_finished)
        self.worker.start()

    def work_finished(self):
        finished = self.worker
        self.worker = None
        finished.deleteLater()
        for widget in self.controls:
            widget.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.statusBar().showMessage('就绪')

    def show_error(self, message):
        self.details.appendPlainText('处理未完成：' + message)
        QMessageBox.warning(self, '请检查标注', message)

    def _schedule(self):
        if self.sources and not self.busy():
            self.timer.start()

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, '选择手动标注 JSON', str(self.settings.value('input', str(DEFAULT_INPUT))), 'Labelme JSON (*.json)')
        if files:
            self.set_files([Path(p) for p in files])

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '选择手动标注文件夹', str(self.settings.value('input', str(DEFAULT_INPUT))))
        if folder:
            self.import_folder(Path(folder))

    def import_folder(self, folder):
        self.set_files(sorted(folder.rglob('*.json')), folder)

    def set_files(self, paths, root=None):
        if self.busy():
            return
        if not paths:
            self.show_error('所选目录没有 JSON 文件。')
            return
        self.sources = list(dict.fromkeys(p.resolve() for p in paths))
        try:
            self.input_root = Path(root).resolve() if root else Path(os.path.commonpath([str(p.parent) for p in self.sources]))
        except ValueError:
            self.input_root = None
        if self.input_root:
            self.settings.setValue('input', str(self.input_root))
            if not self.output.text().strip():
                self.output.setText(str(self.input_root.parent / '优化版'))
        self.prepared = None
        self.result = None
        self.file_list.blockSignals(True)
        self.file_list.clear()
        for path in self.sources:
            item = QListWidgetItem(str(path.relative_to(self.input_root)) if self.input_root else path.name)
            item.setToolTip(str(path))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.file_list.addItem(item)
        self.file_list.blockSignals(False)
        self.file_count.setText(f'已导入 {len(paths)} 个文件 · 勾选决定批次范围')
        self.file_list.setCurrentRow(0)
        QTimer.singleShot(0, lambda: self.left_scroll.verticalScrollBar().setValue(0))

    def clear_files(self):
        self.sources = []
        self.input_root = None
        self.prepared = self.result = None
        self.file_list.clear()
        self.preview.scene().clear()
        self.preview.item = None
        self.preview.image_key = None
        self.file_count.setText('可拖入 JSON 或文件夹')
        self.summary.setText('导入一张 JSON 开始。')
        self.details.clear()

    def check_all(self):
        for i in range(self.file_list.count()):
            self.file_list.item(i).setCheckState(Qt.Checked)

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, '选择优化输出目录', self.output.text())
        if path:
            self.output.setText(path)

    def choose_images(self):
        path = QFileDialog.getExistingDirectory(self, '选择原始照片目录', self.image_root.text())
        if path:
            self.image_root.setText(path)
            self.prepared = None
            self.preview_current()

    def selection_changed(self, row):
        if row >= 0:
            self.preview_current()

    def selected_source(self):
        row = self.file_list.currentRow()
        return self.sources[row] if 0 <= row < len(self.sources) else None

    def preview_current(self):
        source = self.selected_source()
        if source is None or self.busy():
            return
        mode, threshold = self.mode.currentData(), self.threshold.value()
        image_root = Path(self.image_root.text()) if self.image_root.text().strip() else None
        cached = self.prepared
        view = self.view_mode.currentText()
        full_resolution = self.full_resolution.isChecked()
        layers = [v for v, check in self.layers.items() if check.isChecked()]
        try:
            signature = (source, source.stat().st_mtime_ns, source.stat().st_size, mode, str(image_root))
        except OSError as exc:
            self.show_error(f'无法读取原稿：{exc}')
            return
        def work(_):
            started = time.perf_counter()
            if cached is not None and getattr(cached, '_signature', None) == signature:
                prepared = cached
            else:
                prepared = prepare(load_annotation(source, image_root), mode)
                prepared._signature = signature
            result = optimize(prepared, threshold)
            pixels = render_preview(result, view, layers, full_resolution)
            return result, pixels, round(time.perf_counter()-started, 2)
        self.run_work(work, self.preview_done)

    def preview_done(self, payload):
        self.result, pixels, duration = payload
        self.prepared = self.result.prepared
        self.preview.show_image(pixels, (str(self.prepared.annotation.path), pixels.shape[:2]))
        r = self.result.report
        small = r['small_regions_to_ignore']
        count = sum(v['components'] for v in small.values())
        area = sum(v['pixels'] for v in small.values())
        self.summary.setText(f"{self.prepared.annotation.path.name}  ·  {r['mode_description']}\n"
                             f'小独立区域：{count} 个 / {area:,} 像素转 ignore   ·   本次预览 {duration:.2f} 秒')
        lines = [f"交叠 → ignore：{r['overlap_to_ignore_pixels']:,} 像素；空隙 → ignore：{r['gap_to_ignore_pixels']:,} 像素。",
                 f"裁掉外轮廓外的组织：{r['clipped_tissue_pixels']:,} 像素。",
                 '外轮廓外全部 background；内部 ignore 优先。', *r['warnings']]
        self.details.setPlainText('\n'.join(lines))

    def output_jobs(self, sources):
        text = self.output.text().strip()
        if not text:
            raise ValueError('请选择优化输出目录。')
        target = Path(text).resolve()
        if self.input_root and (target == self.input_root or target.is_relative_to(self.input_root)):
            raise ValueError('请把优化版文件夹放在手动原稿文件夹之外，避免下次批量导入时混入优化结果。')
        self.settings.setValue('output', text)
        self.settings.setValue('images', self.image_root.text())
        self.settings.setValue('threshold', self.threshold.value())
        return plan_files(sources, target, self.input_root)

    def export_current(self):
        source = self.selected_source()
        if source is None or self.busy():
            return
        self._export([source])

    def export_checked(self):
        sources = [p for i, p in enumerate(self.sources) if self.file_list.item(i).checkState() == Qt.Checked]
        if not sources:
            self.show_error('请至少勾选一个 JSON 文件。')
            return
        self._export(sources)

    def _export(self, sources):
        try:
            jobs = self.output_jobs(sources)
        except Exception as exc:
            self.show_error(str(exc))
            return
        threshold, mode, images = self.threshold.value(), self.mode.currentData(), self.image_root.text().strip() or None
        def work(progress):
            records = []
            for index, (source, destination) in enumerate(jobs):
                if self.cancel_event.is_set():
                    break
                try:
                    path, report = process_file(source, destination, threshold, mode, images)
                    record = {'ok': True, 'input': str(source), 'output': str(path), 'report': report}
                except Exception as exc:
                    record = {'ok': False, 'input': str(source), 'error': str(exc)}
                records.append(record)
                progress((index+1, len(jobs), record))
            return records, len(jobs)
        self.details.clear()
        self.run_work(work, self.export_done, batch=True)

    def batch_progress(self, payload):
        current, total, record = payload
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        if record['ok']:
            self.details.appendPlainText('已导出：' + record['output'])
        else:
            self.details.appendPlainText('失败：' + record['input'] + '\n' + record['error'])

    def export_done(self, payload):
        records, requested = payload
        good = [r for r in records if r['ok']]
        failures = len(records)-len(good)
        skipped = requested-len(records)
        if good:
            self.last_output = Path(good[-1]['output'])
            self.open_button.setEnabled(True)
        self.summary.setText(f'导出结束：成功 {len(good)}，失败 {failures}，未处理 {skipped}。\n'
                             '所有成功文件均已通过逐像素回读核对；请在 Labelme 中复核组织边界。')
        if good:
            last = good[-1]['report']
            self.details.appendPlainText(f"最近文件：{last['output_shapes']} 个可编辑图形，处理耗时 {last['total_seconds']:.2f} 秒。")
        self.details.appendPlainText('背景等有孔区域会拆成多个同标签多边形；分区接缝不是新的组织边界。')

    def open_labelme(self):
        if not self.last_output:
            return
        launcher = find_labelme_launcher(str(self.settings.value('labelme', '')))
        if not launcher:
            launcher = self.choose_labelme()
        if not launcher:
            return
        try:
            command = labelme_command(launcher, self.last_output)
            subprocess.Popen(command, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, ValueError) as exc:
            self.show_error(f'无法启动 Labelme，请通过「设置 Labelme」选择其程序。\n{exc}')

    def choose_labelme(self):
        selected, _ = QFileDialog.getOpenFileName(self, '选择 Labelme.exe 或安装了 Labelme 的 pythonw.exe',
                                                str(Path.home()), '程序 (*.exe);;所有文件 (*)')
        if selected:
            self.settings.setValue('labelme', selected)
            return Path(selected)
        return None

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.busy():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if len(paths) == 1 and paths[0].is_dir():
            self.import_folder(paths[0])
        else:
            files = [p for p in paths if p.suffix.lower() == '.json' and p.is_file()]
            if files:
                self.set_files(files)

    def closeEvent(self, event):
        if self.busy():
            QMessageBox.information(self, '正在处理', '请等待当前文件处理完成。批次可先点击「停止批次」。')
            event.ignore()
        else:
            event.accept()


def configure_application(app):
    app.setStyle('Fusion')
    app.setStyleSheet('''
        QWidget { font-family: "Microsoft YaHei UI"; font-size: 10pt; color: #203249; }
        QMainWindow, QWidget#central { background: #f7f9fc; }
        QLabel#title { font-size: 22pt; font-weight: 700; color: #142b45; }
        QLabel#subtitle, QLabel#muted { color: #6c7c8f; }
        QLabel#summary { background: #edf3fb; border-radius: 7px; padding: 10px; }
        QGroupBox { border: 1px solid #d7e0eb; border-radius: 8px; margin-top: 10px; padding-top: 12px; font-weight: 600; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; }
        QPushButton { background: white; border: 1px solid #cbd7e5; border-radius: 6px; padding: 7px 10px; }
        QPushButton:hover { background: #e9f1fc; border-color: #6296db; }
        QPushButton:disabled { color: #a0acba; background: #eef1f5; }
        QPushButton#primary { background: #245fbc; color: white; border: none; font-weight: 600; }
        QPushButton#primary:disabled { background: #a7bad6; }
        QLineEdit, QSpinBox, QComboBox { background: white; border: 1px solid #cbd7e5; border-radius: 5px; padding: 6px; }
        QListWidget, QPlainTextEdit { background: white; border: 1px solid #d7e0eb; border-radius: 6px; }
        QListWidget::item { padding: 6px; }
        QListWidget::item:selected { background: #e0edff; color: #164f9e; }
        QProgressBar { border: 1px solid #d7e0eb; border-radius: 5px; text-align: center; min-height: 22px; }
        QProgressBar::chunk { background: #66a3d9; }
    ''')
def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    configure_application(app)
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1:
        paths = [Path(p) for p in sys.argv[1:]]
        QTimer.singleShot(0, lambda: window.import_folder(paths[0]) if len(paths) == 1 and paths[0].is_dir() else window.set_files(paths))
    return app.exec_()
