"""Regression checks for export on a Python-only computer, with no Node runtime."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile, ZIP_DEFLATED

from PIL import Image
from openpyxl import load_workbook
from export_reviews_portable import export_workbook, verify_workbook, load_collection, SPEC


class PortableExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / '原始数据'
        self.source.mkdir()
        for name, color in [('first.png', 'red'), ('middle.png', 'green'), ('last.png', 'blue')]:
            Image.new('RGB', (260, 600), color).save(self.source / name)
        self.output = self.root / '交付' / '评论.xlsx'

    def android(self):
        data = dict(product_name='测试商品', source_url='https://example.com/product', platform='抖音', sort='综合', filters='全部款式',
                    captured_at='2026-11-17T10:00:00+08:00', count=2, status='达到目标数量', reviews=[
            dict(text='=HYPERLINK("https://example.com")', sku_raw='001', date_raw='1个月前', author='买家-001', id='review-001', screenshots=['first.png','middle.png','last.png']),
            dict(text='+原文\n第二行', sku_raw='@规格', date_raw='03-24', screenshots=['last.png'])])
        (self.source/'reviews.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')

    def cdp(self):
        config = dict(platform='京东', target_id='001', sort_filter='默认；当前商品', product_name='测试商品', source_url='https://example.com/product')
        configfile = self.root/'adapter.json'
        configfile.write_text(json.dumps(config),encoding='utf-8')
        row = dict(platform='京东',target_id='001',sort_filter='默认；当前商品',key='key-1',text='原文，不补写年份。',sku_raw='001',date_raw='03-24',evidence='first.png',author_key='',review_id='00002')
        (self.source/'reviews.jsonl').write_text(json.dumps(row)+'\n',encoding='utf-8')
        (self.source/'state.json').write_text(json.dumps(dict(unique_reviews=1,updated_at='2026-11-17T01:00:00Z',reason='LIMIT_REACHED')),encoding='utf-8')
        return configfile

    def test_android_embeds_first_last_and_preserves_literal_text(self):
        self.android()
        result=export_workbook(self.source,self.output)
        self.assertEqual(result['embedded_previews'],3)
        wb=load_workbook(self.output)
        ws=wb.active
        self.assertEqual([ws.cell(6,c).value for c in range(1,10)],SPEC['headings'])
        self.assertEqual(ws['E7'].data_type,'s')
        self.assertEqual(ws['E7'].value,'=HYPERLINK("https://example.com")')
        self.assertEqual(ws['D7'].value,'001')
        self.assertEqual(ws['I7'].value,'未提供')  # local id is not a platform id
        self.assertEqual(ws['H7'].value,'first.png\nmiddle.png\nlast.png')
        self.assertEqual(ws.freeze_panes,'C7')
        wb.close()
        # The transferred XLSX remains self-contained without any source images.
        moved=self.root/'另一台电脑.xlsx'
        moved.write_bytes(self.output.read_bytes())
        for f in self.source.glob('*.png'): f.unlink()
        with ZipFile(moved) as z:
            media=[n for n in z.namelist() if n.startswith('xl/media/')]
            self.assertEqual(len(media),3)
            self.assertTrue(all(z.read(n).startswith(b'\xff\xd8') for n in media))

    def test_cdp_and_stdlib_verifier_without_site_packages(self):
        config=self.cdp()
        self.assertEqual(export_workbook(self.source,self.output,config)['reviews'],1)
        env=dict(os.environ,PATH='')  # This execution has no Node/Excel command.
        process=subprocess.run([sys.executable,'-S',str(Path(__file__).with_name('export_reviews_portable.py')),str(self.source),str(self.output),'--config',str(config),'--verify-only'],env=env,text=True,capture_output=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertTrue(json.loads(process.stdout)['verified'])

    def test_missing_image_preserves_existing_output(self):
        self.android()
        self.output.parent.mkdir()
        self.output.write_bytes(b'existing-good-file')
        (self.source/'last.png').unlink()
        with self.assertRaisesRegex(ValueError,'screenshot'):
            export_workbook(self.source,self.output)
        self.assertEqual(self.output.read_bytes(),b'existing-good-file')

    def test_wrong_product_identity_is_rejected(self):
        config=self.cdp()
        data=json.loads(config.read_text())
        data['target_id']='002'
        config.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'identity'):
            export_workbook(self.source,self.output,config)

    def test_missing_embedded_bytes_is_rejected(self):
        self.cdp_config=self.cdp()
        export_workbook(self.source,self.output,self.cdp_config)
        broken=self.root/'broken.xlsx'
        with ZipFile(self.output) as original, ZipFile(broken,'w',ZIP_DEFLATED) as modified:
            for n in original.namelist():
                if not n.startswith('xl/media/'):
                    modified.writestr(n,original.read(n))
        with self.assertRaisesRegex(ValueError,'image bytes'):
            verify_workbook(self.source,broken,self.cdp_config)

    def test_csv_only_cannot_claim_pictures(self):
        (self.source/'reviews.csv').write_text('text,evidence\n正文,first.png\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'CSV cannot hold images'):
            load_collection(self.source)

    def test_outside_evidence_is_rejected(self):
        self.android()
        data=json.loads((self.source/'reviews.json').read_text(encoding='utf-8'))
        data['reviews'][0]['screenshots']=['../outside.png']
        Image.new('RGB',(20,20)).save(self.root/'outside.png')
        (self.source/'reviews.json').write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'out-of-scope'):
            load_collection(self.source)


if __name__=='__main__':
    unittest.main()
