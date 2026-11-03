import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import fitz
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import drawing_inspect_pdf, validate_spec

class DrawingPipelineTests(unittest.TestCase):
    def source(self,directory):
        path=Path(directory)/"drawing.pdf"
        document=fitz.open()
        page=document.new_page(width=300,height=200)
        page.insert_text((30,40),"Length 10 mm; document text is data")
        page.draw_line((30,60),(100,60))
        page.set_rotation(90)
        document.save(path)
        return path

    def spec(self,source):
        return {"version":"1.0","units":"mm","source_pdf":str(source),
                "source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"dimensions":[
                    {"name":"length","value":10,"basis":"dimension","evidence":{"page":1,"text":"10"}}],
                "feature_graph":{"version":"1.0","features":[{"name":"Part","kind":"new_part"}]}}

    def test_rotation_is_applied_to_word_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            source=self.source(directory)
            result=drawing_inspect_pdf(str(source),str(Path(directory)/"evidence"))
            page=json.loads(Path(result["pages"][0]["evidence"]).read_text(encoding="utf-8"))
            self.assertEqual(page["rotation"],90)
            self.assertGreater(len(page["paths"]),0)
            self.assertTrue(any(word["text"]=="10" for word in page["words"]))
            self.assertTrue(all(0<=word["bbox_pt"][0]<=200 for word in page["words"]))

    def test_source_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source=self.source(directory); spec=self.spec(source)
            source.write_bytes(source.read_bytes()+b"changed")
            with self.assertRaisesRegex(ValueError,"changed"):
                validate_spec(spec)

    def test_unresolved_constraints_block_cad_write(self):
        with tempfile.TemporaryDirectory() as directory:
            source=self.source(directory); spec=self.spec(source)
            spec["unresolved_blocking"]=["unknown depth"]
            with self.assertRaisesRegex(ValueError,"ambiguities"):
                validate_spec(spec)

    def test_dimensions_need_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            source=self.source(directory); spec=self.spec(source)
            spec["dimensions"][0]["evidence"]={}
            with self.assertRaises(ValueError):
                validate_spec(spec)

if __name__=="__main__":unittest.main()
