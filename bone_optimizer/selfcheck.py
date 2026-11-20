"""Synthetic end-to-end check available inside the frozen application."""
import json
from pathlib import Path
import tempfile
from PIL import Image
from PyQt5.QtWidgets import QApplication
from .gui import MainWindow, configure_application
from .service import process_file
from .vectorize import make_shape


def main():
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    window = MainWindow()
    with tempfile.TemporaryDirectory(prefix='bone-optimizer-selfcheck-') as directory:
        root = Path(directory)
        Image.new('RGB', (32, 32), 'white').save(root/'image.png')
        doc = {'version': '6.3.1', 'imagePath': 'image.png', 'imageData': None,
               'imageWidth': 32, 'imageHeight': 32, 'flags': {}, 'shapes': [
                   make_shape('specimen', [[1,1],[30,1],[30,30],[1,30]]),
                   make_shape('bone', [[4,4],[24,4],[24,24],[4,24]])]}
        source = root/'source.json'
        source.write_text(json.dumps(doc), encoding='utf-8')
        _, report = process_file(source, root/'output.json')
        assert report['roundtrip_pixel_differences'] == 0
    window.close()
    return 0
