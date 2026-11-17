"""ADB visible-review collector. Stdlib only. Adapter must be verified first."""
import argparse, hashlib, itertools, json, pathlib, re, subprocess, time
import xml.etree.ElementTree as ET
from datetime import datetime

DATE = re.compile(r'(\d+\s*个?(天|小时|分钟|秒|月|年|周)前|昨天|前天|今天|\d{1,4}[-./年]\d{1,2}([月./-]\d{1,2}日?)?)')

def rect(n):
    return list(map(int, re.findall(r'\d+', n.get('bounds', ''))))

def parse_page(raw, cfg):
    root = ET.fromstring(raw)
    boxes = [n for n in root.iter('node') if n.get('resource-id') == cfg['list_resource_id'] and n.get('package') == cfg['package']]
    if len(boxes) != 1:
        raise ValueError('Expected exactly one verified review list; stop and inspect page')
    rows = []; date = ''; author = ''
    for frame in boxes[0]:
        nodes = [n for n in frame.iter('node') if n.get('text')]
        texts = [n.get('text') for n in nodes]
        dates = [t for t in texts if DATE.fullmatch(t)]
        if dates:
            date = dates[0]
            author = next((t for t in texts if '**' in t), '')
        bodies = [n for n in nodes if rect(n) and rect(n)[0] == cfg['body_left'] and not n.get('text').startswith('浏览 ') and n.get('text') not in ('有用', '展开', '收起') and not n.get('text').isdigit()]
        for n in bodies:
            body = n.get('text')
            # Match the observed SKU column when configured; filter tabs may also
            # contain '/' and must never be counted as buyer reviews.
            sku = next((s.get('text') for s in nodes
                        if s is not n and re.search(cfg['sku_regex'], s.get('text'))
                        and ('sku_left' not in cfg or rect(s)[0] == cfg['sku_left'])), '')
            if not sku:
                continue
            rows.append(dict(text=body, sku_raw=sku, date_raw=date, author=('买家-'+hashlib.sha256(author.encode()).hexdigest()[:8]) if author else '未展示'))
            date = ''; author = ''
    return rows

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for field in ('adb', 'serial', 'config', 'out'): p.add_argument('--'+field, required=True)
    p.add_argument('--limit', type=int, default=None, help='Optional review count; omitted means collect all accessible reviews')
    p.add_argument('--max-pages', type=int, default=None, help='Optional page budget; no implicit default')
    p.add_argument('--max-minutes', type=float, default=None, help='Optional time budget; no implicit default')
    p.add_argument('--observe', action='store_true')
    a = p.parse_args()
    if any(v is not None and v <= 0 for v in (a.limit,a.max_pages,a.max_minutes)): p.error('Limits must be positive')
    cfg = json.loads(pathlib.Path(a.config).read_text(encoding='utf-8-sig'))
    for k in ('platform','product_name','source_url','sort','filters','package','list_resource_id','body_left','sku_regex','viewport','scroll_x','scroll_start_y'):
        if k not in cfg: p.error('Missing config field '+k)
    x1,y1,x2,y2 = cfg['viewport']; sx = cfg['scroll_x']; sy = cfg['scroll_start_y']
    if not x1 < sx < x2 or not y1+100 < sy < y2-50: p.error('Scroll origin must be inside the verified review viewport')
    out = pathlib.Path(a.out); out.mkdir(parents=True,exist_ok=True)
    def adb(*args):
        r = subprocess.run([a.adb,'-s',a.serial,*args],capture_output=True,timeout=45)
        if r.returncode: raise RuntimeError(r.stderr.decode('utf-8','replace'))
        return r.stdout
    if adb('get-state').strip() != b'device': raise RuntimeError('Device is not authorized/online')
    manifest = out/'task.json'
    if manifest.exists() and json.loads(manifest.read_text(encoding='utf-8')) != cfg:
        raise ValueError('Task identity mismatch; use a different run directory')
    manifest.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    records = {}; result = out/'reviews.json'
    if result.exists():
        for r in json.loads(result.read_text(encoding='utf-8'))['reviews']: records[(r['text'],r['sku_raw'])] = r
    def save(reason):
        payload = dict(source_url=cfg['source_url'],product_name=cfg['product_name'],platform=cfg['platform'],sort=cfg['sort'],filters=cfg['filters'],requested_limit=a.limit,collection_mode='全部' if a.limit is None else '指定条数',captured_at=datetime.now().astimezone().isoformat(),count=len(records),status=reason,dedup='正文+规格，无评价ID，可能合并同文评价',reviews=list(records.values()))
        temp = result.with_suffix('.tmp'); temp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8'); temp.replace(result)
    if a.limit is not None and len(records) >= a.limit and not a.observe: save('已有数据达到目标，未操作手机'); return
    start = time.monotonic(); stagnant = 0; unchanged = 0; last_digest = None
    page = max([int(f.stem.split('-')[1]) for f in out.glob('page-*.xml')]+[0])
    try:
      for _ in (range(a.max_pages) if a.max_pages is not None else itertools.count()):
        if a.max_minutes is not None and time.monotonic()-start > a.max_minutes*60: save('达到时间上限，未完成全量'); break
        page += 1
        adb('shell','uiautomator','dump','/sdcard/window_dump.xml')
        raw = adb('shell','cat','/sdcard/window_dump.xml').decode('utf-8')
        parsed = parse_page(raw,cfg)
        end_reached = any(node.get('text') in cfg.get('end_texts',[]) for box in ET.fromstring(raw).iter('node') if box.get('resource-id') == cfg['list_resource_id'] for node in box.iter('node'))
        # Guard visible verification/error prompts before further inputs.
        alltext = [n.get('text','') for n in ET.fromstring(raw).iter('node')]
        if any(t in ('请完成验证','安全验证','登录后查看','操作频繁，请稍后再试') for t in alltext):
            save('遇到验证或限制，停止'); break
        stem = f'page-{page:03}'
        (out/(stem+'.xml')).write_text(raw,encoding='utf-8')
        png = adb('exec-out','screencap','-p')
        if not png.startswith(b'\x89PNG'): raise ValueError('Invalid screenshot bytes')
        (out/(stem+'.png')).write_bytes(png)
        if a.observe:
            print(json.dumps(dict(page=stem,parsed=parsed),ensure_ascii=False),flush=True); break
        before = len(records)
        for row in parsed:
            key = (row['text'],row['sku_raw'])
            if key not in records and (a.limit is None or len(records) < a.limit):
                records[key] = dict(row,id=f'review-{len(records)+1:03}',screenshots=[],evidence=stem+'.xml',image_source='页面截图，非原图')
            if key in records:
                old = records[key]
                for k in ('date_raw','author'):
                    if row[k] and row[k] != '未展示': old[k] = row[k]
                old['screenshots'].append(stem+'.png')
        save('采集中'); print(f'{stem}: unique={len(records)} new={len(records)-before}',flush=True)
        if a.limit is not None and len(records) >= a.limit: save('达到目标数量'); break
        if end_reached: save('当前筛选下页面明确结束，已采集可访问评价'); break
        if not parsed: save('未识别到正文，停止以检查媒体或页面适配'); break
        digest = hashlib.sha256(raw.encode()).hexdigest()
        unchanged = unchanged+1 if digest == last_digest else 0; last_digest = digest
        stagnant = stagnant+1 if len(records)==before else 0
        if unchanged >= 2 or stagnant >= 5: save('页面无变化或连续无新增，停止；不代表全量采完'); break
        chars = sum(len(r['text']) for r in parsed)
        time.sleep(min(7,2+chars/100))
        distance = min(760 if chars>200 else 940, int((y2-y1)*0.5))
        endy = max(y1+120,sy-distance)
        adb('shell','input','swipe',str(sx),str(sy),str(sx),str(endy),str(600+min(chars,600)))
        time.sleep(1)
      else: save('达到页数上限，未完成全量')
    except (Exception,KeyboardInterrupt) as e:
      save('异常或中断: '+str(e)); raise

if __name__ == '__main__': main()
