"""Portable XLSX fallback when the Codex artifact runtime is unavailable.

Both collection formats use assets/workbook-format.json. --verify-only needs
only Python's standard library and also verifies workbooks from the JS exporter.
"""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path, PurePosixPath
import tempfile
import unicodedata
from xml.etree import ElementTree as ET
from zipfile import ZipFile


SPEC = json.loads((Path(__file__).resolve().parent.parent / 'assets' / 'workbook-format.json').read_text(encoding='utf-8'))
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'd': 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}


def evidence_path(source, relative):
    normalized = str(relative).replace('\\', '/')
    if not normalized or PurePosixPath(normalized).is_absolute() or ':' in normalized:
        raise ValueError('Evidence must be a relative path: ' + normalized)
    target = (source / normalized).resolve()
    if not target.is_relative_to(source) or not target.is_file():
        raise ValueError('Missing or out-of-scope screenshot: ' + normalized)
    return target


def load_collection(source, config=None):
    source = Path(source).resolve()
    if (source / 'reviews.jsonl').exists():
        if config is None:
            raise ValueError('CDP export requires --config <adapter.json>')
        cfg = json.loads(Path(config).read_text(encoding='utf-8-sig'))
        state = json.loads((source / 'state.json').read_text(encoding='utf-8-sig'))
        raw = [json.loads(s) for s in (source / 'reviews.jsonl').read_text(encoding='utf-8-sig').splitlines() if s.strip()]
        placeholders = {hashlib.sha256((cfg['platform']+'|'+cfg['target_id']+'|'+name).encode()).hexdigest()[:20]
                        for name in ('匿名买家', '匿名用户', '匿名', '用户已注销')}
        rows = []
        for r in raw:
            if any(r.get(k) != cfg[k] for k in ('platform', 'target_id', 'sort_filter')):
                raise ValueError('Collection identity mismatch')
            author = r.get('author_key', '')
            label = '匿名买家（页面未区分）' if author in placeholders else '买家-'+author[:10] if author else '未展示'
            rows.append(dict(r, author_label=label, screenshots=[r['evidence']]))
        keys = [r.get('key') for r in rows]
        if any(not k for k in keys) or len(set(keys)) != len(keys):
            raise ValueError('Missing or duplicated review fingerprint')
        if state.get('unique_reviews') != len(rows):
            raise ValueError('Checkpoint count does not match records')
        meta = dict(product_name=cfg.get('product_name') or cfg['platform']+'商品',
                    source_url=cfg.get('source_url') or (rows[0].get('source_url') if rows else ''),
                    target_id=cfg['target_id'], sort_filter=cfg['sort_filter'],
                    captured_at=state.get('updated_at', ''), reason=state.get('reason', '未记录'))
    elif (source / 'reviews.json').exists():
        data = json.loads((source / 'reviews.json').read_text(encoding='utf-8-sig'))
        rows = [dict(r, author_label=r.get('author') or '未展示', screenshots=list(dict.fromkeys(r.get('screenshots', [])))) for r in data['reviews']]
        keys = [(r.get('text'), r.get('sku_raw')) for r in rows]
        if len(set(keys)) != len(keys) or data.get('count') != len(rows):
            raise ValueError('Duplicate reviews or checkpoint count mismatch')
        meta = dict(product_name=data.get('product_name') or '商品', source_url=data.get('source_url', ''),
                    target_id=data.get('target_id', ''), sort_filter='；'.join(str(data.get(k, '')) for k in ('sort', 'filters')),
                    captured_at=data.get('captured_at', ''), reason=data.get('status', '未记录'))
    else:
        raise ValueError('Need reviews.jsonl or reviews.json AND original screenshots. CSV cannot hold images.')
    if not rows:
        raise ValueError('No reviews to export')
    if len(rows) > 1048570:
        raise ValueError('Excel row limit exceeded; split by product or batch without dropping reviews')
    for r in rows:
        if not isinstance(r.get('text'), str) or not r['text'].strip() or not r['screenshots']:
            raise ValueError('Review has no text or screenshot')
        for item in r['screenshots']:
            evidence_path(source, item)
    return source, meta, rows


def display_rows(rows):
    return [[i+1, r['author_label'], r.get('date_raw') or '未展示', r.get('sku_raw') or '未展示',
             r['text'], r.get('rating_raw') or '未展示文字星级', '', '\n'.join(r['screenshots']), r.get('review_id') or '未提供']
            for i, r in enumerate(rows)]


def metadata_lines(meta, count):
    moment = meta['captured_at']
    try:
        moment = datetime.fromisoformat(moment.replace('Z', '+00:00')).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')+'（北京时间）'
    except (ValueError, TypeError):
        pass
    return [meta['product_name']+'买家评价',
            f"本次采集 {count} 条。{meta['sort_filter']}。采集时间：{moment}。停止原因：{meta['reason']}。",
            '来源：'+meta['source_url']+('。商品ID：'+meta['target_id'] if meta['target_id'] else ''), SPEC['note']]


def text_lines(value, width):
    return sum(max(1, math.ceil(sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in line)/width))
               for line in str(value).split('\n'))


def verify_workbook(source, output, config=None):
    _, _, rows = load_collection(source, config)
    expected = display_rows(rows)
    with ZipFile(output) as z:
        if z.testzip() is not None:
            raise ValueError('Broken XLSX ZIP')
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            shared = [''.join(n.itertext()) for n in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si', NS)]
        sheet = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        cells = {}
        for c in sheet.findall('.//s:sheetData/s:row/s:c', NS):
            if c.find('s:f', NS) is not None or c.get('t') == 'e':
                raise ValueError('Unexpected formula/error in a literal review workbook')
            if c.get('t') == 'inlineStr':
                value = ''.join(n.text or '' for n in c.findall('.//s:t', NS))
            else:
                value = c.findtext('s:v', '', NS)
                if c.get('t') == 's':
                    value = shared[int(value)]
            cells[c.attrib['r']] = value
        for col, value in enumerate(SPEC['headings']):
            if cells.get(chr(65+col)+'6') != value:
                raise ValueError('Workbook columns do not match standard')
        for row, values in enumerate(expected, 7):
            for col, value in enumerate(values):
                actual = cells.get(chr(65+col)+str(row), '')
                # Artifact Tool stores a protective apostrophe for literal formulas.
                if actual != str(value) and not (str(value).startswith('=') and actual == "'"+str(value)):
                    raise ValueError(f'Workbook source mismatch at {chr(65+col)}{row}')
        pane = sheet.find('s:sheetViews/s:sheetView/s:pane', NS)
        if pane is None or pane.get('topLeftCell') != 'C7':
            raise ValueError('Expected frozen headers and two identifying columns')
        embedded_rows = set()
        pictures = 0
        for name in z.namelist():
            if name.startswith('xl/drawings/') and name.endswith('.xml') and '/_rels/' not in name:
                drawing = PurePosixPath(name)
                relname = str(drawing.parent / '_rels' / (drawing.name+'.rels'))
                rels = {rel.get('Id'): rel for rel in ET.fromstring(z.read(relname))}
                for anchor in ET.fromstring(z.read(name)):
                    if anchor.find('d:pic', NS) is None:
                        continue
                    if anchor.findtext('d:from/d:col', namespaces=NS) != '6':
                        raise ValueError('Preview is outside column G')
                    embedded_rows.add(int(anchor.findtext('d:from/d:row', namespaces=NS)))
                    pictures += 1
                    blip = anchor.find('.//a:blip', NS)
                    if blip is None or not blip.get('{'+NS['r']+'}embed') or blip.get('{'+NS['r']+'}link'):
                        raise ValueError('Preview must be embedded, not an external image link')
                    rel = rels.get(blip.get('{'+NS['r']+'}embed'))
                    if rel is None or rel.get('TargetMode') == 'External':
                        raise ValueError('Missing or external image relationship')
                    import posixpath
                    target = rel.get('Target', '')
                    mediafile = target.lstrip('/') if target.startswith('/') else posixpath.normpath(str(drawing.parent / target))
                    if mediafile not in z.namelist() or not z.read(mediafile):
                        raise ValueError('Missing embedded image bytes')
        if embedded_rows != set(range(6, len(rows)+6)):
            raise ValueError('Some reviews have no embedded preview')
        if pictures != sum(min(2, len(r['screenshots'])) for r in rows):
            raise ValueError('Wrong number of screenshot previews')
        media = [n for n in z.namelist() if n.startswith('xl/media/')]
        if not media:
            raise ValueError('No embedded image data')
    return dict(reviews=len(rows), embedded_previews=pictures, format_version=SPEC['version'], verified=True)


def export_workbook(source, output, config=None):
    # Kept lazy so --verify-only works without any third-party dependencies.
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
    from openpyxl.drawing.xdr import XDRPositiveSize2D
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.table import Table, TableStyleInfo
    from openpyxl.utils.units import pixels_to_EMU
    from PIL import Image, ImageOps

    source, meta, rows = load_collection(source, config)
    output = Path(output).resolve()
    if output.suffix.lower() != '.xlsx':
        raise ValueError('Output must end in .xlsx; CSV cannot embed images')
    output.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = SPEC['sheet']
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = 'C7'
    for i, width in enumerate(SPEC['widths'], 1):
        ws.column_dimensions[chr(64+i)].width = width
    font = Font(name=SPEC['font'], size=SPEC['font_size'], color=SPEC['text_color'])

    def literal(cell, value):
        if isinstance(value, str) and (len(value) > 32767 or any(ord(c)<32 and c not in '\t\n\r' for c in value)):
            raise ValueError('Source text exceeds Excel cell limits; do not truncate original text')
        cell.value = value
        if isinstance(value, str):
            cell.data_type = 's'  # Preserve =,+,-,@ verbatim as text.
        cell.font = font
        cell.alignment = Alignment(vertical='top', wrap_text=True)

    for row, line in enumerate(metadata_lines(meta, len(rows)), 2):
        literal(ws.cell(row, 1), line)
        ws.cell(row, 1).alignment = Alignment(vertical='center', wrap_text=False)
    ws['A2'].font = Font(name=SPEC['font'], size=16, bold=True, color=SPEC['text_color'])
    ws.row_dimensions[2].height = 27
    for col, name in enumerate(SPEC['headings'], 1):
        cell = ws.cell(6, col, name)
        cell.font = Font(name=SPEC['font'], size=SPEC['font_size'], bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor=SPEC['header_color'])
        cell.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[6].height = 30
    buffers = []
    for i, (r, values) in enumerate(zip(rows, display_rows(rows)), 7):
        for col, value in enumerate(values, 1):
            literal(ws.cell(i, col), value)
            if i % 2 == 0:
                ws.cell(i, col).fill = PatternFill('solid', fgColor=SPEC['stripe_color'])
        picks = r['screenshots'][:1] if len(r['screenshots']) == 1 else [r['screenshots'][0], r['screenshots'][-1]]
        max_width = SPEC['image_max_width'] if len(picks) == 1 else (SPEC['image_max_width']-8)//2
        height = 136
        x = 4
        for relative in picks:
            with Image.open(evidence_path(source, relative)) as image:
                image = ImageOps.exif_transpose(image).convert('RGB')
                factor = min(1, max_width/image.width, SPEC['image_max_height']/image.height)
                width_px, height_px = max(1, round(image.width*factor)), max(1, round(image.height*factor))
                image = image.resize((width_px, height_px), Image.Resampling.LANCZOS)
                buffer = BytesIO()
                image.save(buffer, format='JPEG', quality=88)
            buffer.seek(0)
            buffers.append(buffer)
            preview = XLImage(buffer)
            preview.anchor = OneCellAnchor(_from=AnchorMarker(col=6, row=i-1, colOff=pixels_to_EMU(x), rowOff=pixels_to_EMU(4)),
                                           ext=XDRPositiveSize2D(pixels_to_EMU(width_px), pixels_to_EMU(height_px)))
            ws.add_image(preview)
            height = max(height, height_px+12)
            x += width_px+8
        height = max(height, text_lines(r['text'], 74)*18+16, text_lines(r.get('sku_raw') or '', 38)*18+16,
                     text_lines('\n'.join(r['screenshots']), 28)*18+16)
        if height > 540:
            raise ValueError(f'Review {i-6} needs a multirow layout; do not crop text or screenshots')
        ws.row_dimensions[i].height = height*0.75
    table = Table(displayName='Reviews', ref=f'A6:I{len(rows)+6}')
    table.tableStyleInfo = TableStyleInfo(name='TableStyleMedium2', showRowStripes=False)
    ws.add_table(table)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.xlsx', prefix='.review-', dir=output.parent, delete=False) as f:
            temp = Path(f.name)
        wb.save(temp)
        result = verify_workbook(source, temp, config)
        temp.replace(output)
        return result
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
        wb.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Collection directory, including original screenshots')
    parser.add_argument('output', type=Path, help='Embedded-image .xlsx')
    parser.add_argument('--config', type=Path, help='Required for CDP reviews.jsonl')
    parser.add_argument('--verify-only', action='store_true', help='Standard-library XLSX validation, no export')
    args = parser.parse_args()
    try:
        result = verify_workbook(args.source, args.output, args.config) if args.verify_only else export_workbook(args.source, args.output, args.config)
    except ImportError:
        parser.exit(2, 'Portable export dependencies missing. Use this Python interpreter to install scripts/export-requirements.txt in a task-local virtual environment. XLSX NOT delivered.\n')
    except (ValueError, OSError, KeyError) as e:
        parser.exit(2, str(e)+'\nXLSX NOT delivered; keep existing records and fix export.\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
