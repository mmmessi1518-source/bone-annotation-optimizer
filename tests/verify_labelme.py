"""Installed Labelme open/edit/save/reopen regression check, isolated from user data."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'vendor')]
import numpy as np
from PIL import Image
from PyQt5.QtCore import QSettings, QPointF
from PyQt5.QtWidgets import QApplication
from labelme.app import MainWindow
from labelme._label_file import read_label_file
from labelme._shape import nearest_vertex_index
from labelme.utils.shape import shapes_to_label
from bone_optimizer.annotation_io import load_annotation
from bone_optimizer.core import prepare, optimize
from bone_optimizer.vectorize import make_shape
from bone_optimizer.service import process_file


def main():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix='bone-optimizer-labelme-test-') as temp:
        root = Path(temp)
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(root))
        config = root/'labelme.yaml'
        config.write_text('auto_save: false\n', encoding='utf-8')
        Image.new('RGB',(160,120),'white').save(root/'photo.png')
        document = {'version':'6.3.1','flags':{},'imageWidth':160,'imageHeight':120,
                    'imagePath':'photo.png','imageData':None,'shapes':[
            make_shape('specimen',[[10,10],[150,10],[150,110],[10,110]]),
            make_shape('bone',[[40,40],[100,40],[100,90],[40,90]])]}
        source = root/'source.json'
        source.write_text(json.dumps(document), encoding='utf-8')
        exported,_ = process_file(source,root/'optimized.json',threshold=0)
        expected = optimize(prepare(load_annotation(source)),0).mask
        loaded = read_label_file(str(exported))
        rendered,_ = shapes_to_label(expected.shape,loaded.shapes,
                                     {'specimen':0,'background':0,'bone':1,'none_bone':2,'ignore':255})
        assert np.array_equal(expected,rendered)
        window = MainWindow(config_file=config,file_or_dir=str(exported))
        for shape in window._canvas_widgets.canvas.shapes:
            assert shape.can_add_point()
            assert nearest_vertex_index(shape=shape,point=shape.points[0],epsilon=1)==0
        bone = next(s for s in window._canvas_widgets.canvas.shapes if s.label=='bone')
        bone.points[0] += QPointF(1,1)
        edited = root/'edited.json'
        assert window.save_labels(str(edited))
        reopened = MainWindow(config_file=config,file_or_dir=str(edited))
        saved_bone = next(s for s in reopened._canvas_widgets.canvas.shapes if s.label=='bone')
        assert saved_bone.points[0] == bone.points[0]
        process_file(edited,root/'reoptimized.json',threshold=0)
        window.hide(); reopened.hide()
    print('Labelme open / editable vertices / save / reopen / reimport: PASS')


if __name__=='__main__': main()
