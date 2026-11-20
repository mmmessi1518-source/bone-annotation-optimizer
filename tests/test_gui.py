import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'vendor')]
from PIL import Image
from PyQt5.QtCore import QSettings, QTimer
from PyQt5.QtWidgets import QApplication
from bone_optimizer.gui import MainWindow, configure_application
from bone_optimizer.launchers import labelme_command
from bone_optimizer.vectorize import make_shape


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application(cls.app)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.prior_format = QSettings.defaultFormat()
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(self.root))
        self.window = MainWindow()
        self.errors = []
        self.window.show_error = self.errors.append
        self.window.show()
        self.manual = self.root/'manual'
        self.manual.mkdir()
        Image.new('RGB', (80,60), 'white').save(self.root/'photo.png')
        doc = {'version':'6.3.1','imageWidth':80,'imageHeight':60,'imagePath':'../photo.png',
               'imageData':None,'flags':{},'shapes':[
                   make_shape('specimen',[[1,1],[78,1],[78,58],[1,58]]),
                   make_shape('none_bone',[[10,10],[60,10],[60,45],[10,45]])]}
        self.source = self.manual/'sample.json'
        self.source.write_text(json.dumps(doc), encoding='utf-8')

    def tearDown(self):
        self.window.timer.stop()
        self.wait()
        self.window.close()
        self.app.processEvents()
        QSettings.setDefaultFormat(self.prior_format)
        self.temp.cleanup()

    def wait(self):
        deadline = time.monotonic()+15
        while self.window.busy() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.002)
        self.assertFalse(self.window.busy(), 'background worker timed out')

    def test_preview_filter_batch_and_partial_failure(self):
        self.window.set_files([self.source], self.manual)
        self.wait()
        self.assertFalse(self.errors)
        self.assertEqual(self.window.result.report['mode'], 'none_bone')
        self.assertEqual(Path(self.window.output.text()), self.root/'优化版')
        self.window.threshold.setValue(200)
        self.window.timer.stop()
        self.window.preview_current()
        self.wait()
        self.assertEqual(self.window.result.report['threshold_original_pixels'], 200)
        invalid = self.manual/'invalid.json'
        invalid.write_text('{broken',encoding='utf-8')
        self.window.set_files([self.source,invalid], self.manual)
        self.wait()
        self.window.export_checked()
        self.wait()
        self.assertTrue((self.root/'优化版/sample.json').exists())
        self.assertFalse((self.root/'优化版/invalid.json').exists())
        self.assertIn('失败 1',self.window.summary.text())
        self.assertTrue(self.window.open_button.isEnabled())
        self.assertEqual(self.source.read_text('utf-8')[0], '{')

    def test_frozen_launcher_does_not_execute_optimizer_as_python(self):
        with patch.object(sys,'frozen',True,create=True):
            with self.assertRaises(ValueError):
                labelme_command(sys.executable,self.source)
        command=labelme_command(self.root/'pythonw.exe',self.source)
        self.assertEqual(command[1:4],['-s','-m','labelme'])
        direct=labelme_command(self.root/'labelme.exe',self.source)
        self.assertEqual(len(direct),2)
