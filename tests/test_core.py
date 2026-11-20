import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'vendor')]
import numpy as np
from PIL import Image

from bone_optimizer.annotation_io import Annotation, load_annotation, region_from_shapes, write_new_json
from bone_optimizer.core import prepare, optimize
from bone_optimizer.vectorize import editable_polygons, make_shape, export_document
from bone_optimizer.service import process_file, plan_files


def box(label, x0, y0, x1, y1):
    return make_shape(label, [[x0,y0],[x1,y0],[x1,y1],[x0,y1]])


def annotation(shapes, size=(64,48)):
    document = {'version':'6.3.1','shapes':shapes,'imageWidth':size[0],'imageHeight':size[1],
                'imagePath':'photo.png','imageData':None,'flags':{}}
    return Annotation(Path('test.json'), document, None, Image.new('RGB',size), 'test', [])


class LogicTests(unittest.TestCase):
    def test_infer_both_directions_and_clip(self):
        for label, value, inferred in [('bone',1,2),('none_bone',2,1)]:
            a = annotation([box('specimen',10,10,50,35),box(label,0,0,20,20),box('ignore',45,30,55,40)])
            result = optimize(prepare(a),0)
            self.assertEqual(result.mask[12,12],value)
            self.assertEqual(result.mask[25,30],inferred)
            self.assertEqual(result.mask[33,48],255)
            self.assertEqual(result.mask[40,55],0)

    def test_explicit_gaps_and_overlap(self):
        a = annotation([box('specimen',0,0,60,40),box('bone',5,5,30,30),box('none_bone',20,10,40,35)])
        result = optimize(prepare(a),0)
        self.assertEqual(result.mask[15,25],255)
        self.assertEqual(result.mask[1,1],255)
        self.assertEqual(result.mask[8,8],1)
        self.assertEqual(result.mask[33,35],2)

    def test_threshold_reversible_equal_and_eight_connected(self):
        a = annotation([box('specimen',0,0,63,47),box('bone',5,5,7,7),box('bone',8,8,8,8),box('bone',25,20,45,40)])
        p = prepare(a)
        low = optimize(p,9)
        high = optimize(p,10)
        self.assertEqual(low.mask[5,5],1)
        self.assertEqual(high.mask[5,5],255)
        self.assertTrue(np.array_equal(low.mask,optimize(p,9).mask))
        self.assertEqual(optimize(p,0).mask[5,5],1)

    def test_invalid_mode_unknown_label_background(self):
        shapes = [box('specimen',0,0,50,40),box('bone',0,0,10,10)]
        with self.assertRaises(ValueError): prepare(annotation(shapes),'none_bone')
        with self.assertRaises(ValueError): prepare(annotation(shapes+[box('other',0,0,1,1)]))
        with self.assertRaises(ValueError): prepare(annotation(shapes+[box('background',2,2,3,3)]))
        with self.assertRaises(ValueError): prepare(annotation([]))

    def test_selected_subtraction_accepts_matching_existing_complement(self):
        for selected, complementary in [('bone', 'none_bone'), ('none_bone', 'bone')]:
            specimen = box('specimen', 2, 2, 50, 40)
            source = box(selected, 10, 10, 25, 25)
            first = optimize(prepare(annotation([specimen, source])), 0)
            complement_value = 1 if complementary == 'bone' else 2
            counterpart = [make_shape(complementary, p)
                           for p in editable_polygons(first.mask == complement_value)]
            for shape in counterpart:
                shape['generated_by'] = 'specimen-mask-converter'
            prepared = prepare(annotation([specimen, source, *counterpart]), selected)
            second = optimize(prepared, 0)
            self.assertTrue(np.array_equal(first.mask, second.mask))
            self.assertTrue(second.report['checked_existing_complement'])

    def test_selected_subtraction_rejects_changed_existing_complement(self):
        specimen = box('specimen', 2, 2, 50, 40)
        source = box('none_bone', 10, 10, 25, 25)
        baseline = optimize(prepare(annotation([specimen, source])), 0)
        counterpart = [make_shape('bone', p) for p in editable_polygons(baseline.mask == 1)]
        counterpart[0]['points'][0][0] += 3  # Simulate a later Labelme vertex edit.
        with self.assertRaisesRegex(ValueError, '像素不一致'):
            prepare(annotation([specimen, source, *counterpart]), 'none_bone')

    def test_holes_random_fragments_exact(self):
        rng=np.random.default_rng(941)
        fixtures=[]
        for _ in range(80): fixtures.append(rng.random((32,40))>.48)
        ring = np.ones((80,90),dtype=bool)
        ring[4:10,5:20]=False; ring[15:70,30:70]=False; ring[25:60,40:60]=True
        fixtures.extend([ring,np.eye(40,dtype=bool),np.ones((1,1),dtype=bool),np.zeros((3,4),dtype=bool)])
        for mask in fixtures:
            shapes=[make_shape('bone',p) for p in editable_polygons(mask)]
            actual=region_from_shapes(shapes,(mask.shape[1],mask.shape[0]))
            self.assertTrue(np.array_equal(mask,actual))
            self.assertTrue(all(s['shape_type']=='polygon' and len(s['points'])>=3 for s in shapes))

    def test_generated_marker_never_discards_edits(self):
        shape = box('bone',5,5,20,20)
        shape['generated_by']='specimen-mask-converter'
        a=annotation([box('specimen',0,0,40,40),shape])
        result=optimize(prepare(a),0)
        self.assertEqual(result.mask[10,10],1)
        document,_=export_document(result,Path('optimized/test.json'))
        a.document=document
        second=optimize(prepare(a),0)
        self.assertTrue(np.array_equal(result.mask,second.mask))
        # Deliberate edit adds an explicit ignore shape; it must survive reimport.
        document['shapes'].append(box('ignore',8,8,12,12))
        third=optimize(prepare(a),0)
        self.assertEqual(third.mask[10,10],255)

    def test_zero_tissue_all_ignore(self):
        a=annotation([box('specimen',0,0,20,20),box('ignore',0,0,20,20)])
        result=optimize(prepare(a),100)
        document,_=export_document(result,Path('out.json'))
        a.document=document
        self.assertTrue(np.array_equal(result.mask,optimize(prepare(a),100).mask))

    def test_legacy_mask_roundtrip(self):
        image=Image.new('L',(5,5),1); buffer=BytesIO(); image.save(buffer,format='PNG')
        a=annotation([box('specimen',0,0,40,40),{'label':'bone','shape_type':'mask','points':[[3,3],[7,7]],'mask':base64.b64encode(buffer.getvalue()).decode()}])
        result=optimize(prepare(a),0)
        self.assertEqual(int(np.count_nonzero(result.mask==1)),25)

    def test_paths_saving_and_source_protection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'photos').mkdir(); Image.new('RGB',(64,48)).save(root/'photos/photo.png')
            manual=root/'annotations/manual/group'; manual.mkdir(parents=True)
            a=annotation([box('specimen',0,0,50,40),box('bone',10,10,20,20)])
            a.document['imagePath']='../../photos/photo.png'  # old path before manual folder was added
            source=manual/'test.json'; source.write_text(json.dumps(a.document),encoding='utf-8')
            original=source.read_bytes()
            loaded=load_annotation(source)
            self.assertEqual(loaded.image_path,root/'photos/photo.png')
            out=root/'optimized/group/test.json'
            first,report=process_file(source,out)
            second,_=process_file(source,out)
            self.assertNotEqual(first,second)
            self.assertEqual(source.read_bytes(),original)
            self.assertEqual(load_annotation(first).image_path,root/'photos/photo.png')
            with self.assertRaises(ValueError): process_file(source,source)
            self.assertEqual(report['roundtrip_pixel_differences'],0)

    def test_plan_nested_and_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            jobs=plan_files([root/'input/a/x.json',root/'input/b/x.json'],root/'out',root/'input')
            self.assertEqual(jobs[0][1],root/'out/a/x.json')
            with self.assertRaises(ValueError):plan_files([root/'a/x.json',root/'b/x.json'],root/'out')

    def test_exif_and_embedded_precedence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            photo=Image.new('RGB',(20,30),'red'); exif=Image.Exif(); exif[274]=6
            photo.save(root/'photo.jpg',exif=exif)
            doc=annotation([box('specimen',0,0,29,19),box('bone',1,1,10,10)],(30,20)).document
            doc['imagePath']='photo.jpg'
            source=root/'sample.json'; source.write_text(json.dumps(doc))
            loaded=load_annotation(source)
            self.assertEqual(loaded.size,(30,20))
            data=BytesIO();Image.new('RGB',(30,20),'blue').save(data,format='PNG')
            doc['imageData']=base64.b64encode(data.getvalue()).decode()
            source.write_text(json.dumps(doc))
            loaded=load_annotation(source)
            self.assertEqual(loaded.image.getpixel((0,0)),(0,0,255))
            optimized,_=export_document(optimize(prepare(loaded),0),root/'out/sample.json')
            self.assertEqual(optimized['imageData'],doc['imageData'])

    def test_failed_write_leaves_no_partial_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); dest=root/'test.json'
            with self.assertRaises(ValueError):write_new_json({'invalid':float('nan')},dest,root/'source.json')
            self.assertFalse(dest.exists())
            self.assertEqual(list(root.iterdir()),[])


if __name__=='__main__': unittest.main(verbosity=2)
