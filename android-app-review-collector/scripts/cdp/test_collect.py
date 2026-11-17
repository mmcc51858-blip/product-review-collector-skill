"""Isolated CDP regression tests against a local fixture, never a shopping account.

Requires the packaged Python dependencies and an installed Chrome/Edge.
Run: python -m unittest discover -s scripts/cdp -p test_*.py
"""
import csv,json,os,pathlib,socket,subprocess,tempfile,threading,time,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from collect import collect,local_endpoint,validate_config,read_card

HTML='''<!doctype html><meta charset="utf-8"><style>
.review{padding:16px;border:1px solid #ddd;width:500px;margin:10px}
.picture{background:#f3dfc0;width:90px;height:40px}
</style><main></main><button id="next" onclick="current++;render()">Next</button>
<script>let current=0;async function render(){
let data=await(await fetch('/comments?page='+current)).json();
document.querySelector('main').replaceChildren();
for(let r of data.rows){let card=document.createElement('article');
card.className='review';card.dataset.reviewId=r.id;
for(let [key,value] of Object.entries(r)){let p=document.createElement('p');p.className=key;p.textContent=value;card.append(p)}
let img=document.createElement('div');img.className='picture';img.textContent='Test picture';card.append(img);document.querySelector('main').append(card)}
document.querySelector('#next').disabled=data.last;
if(data.last){let p=document.createElement('p');p.id='end';p.textContent='Fixture end';document.querySelector('main').append(p)}}render();</script>'''

def row(i):
    return dict(id='r'+str(i),text='=1+1' if i==2 else 'Fixture review '+str(i),rating='5 stars',date='2026-11-16',sku='test SKU',author='test buyer '+str(i))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/comments'):
            from urllib.parse import parse_qs,urlsplit
            number=int(parse_qs(urlsplit(self.path).query).get('page',['0'])[0])
            payload=dict(rows=[[row(1),row(2)],[row(2),row(3)],[row(4)]][min(number,2)],last=number>=2,token='fixture-secret',email='fixture@example.invalid')
            content=json.dumps(payload).encode();kind='application/json'
        else:content=HTML.encode();kind='text/html; charset=utf-8'
        self.send_response(200);self.send_header('Content-Type',kind);self.end_headers();self.wfile.write(content)
    def log_message(self,*args):pass

class CDPCollector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        paths=[pathlib.Path(os.environ.get('ProgramFiles',''))/'Google/Chrome/Application/chrome.exe',
               pathlib.Path(os.environ.get('ProgramFiles(x86)',''))/'Microsoft/Edge/Application/msedge.exe']
        binary=next((p for p in paths if p.is_file()),None)
        if not binary:raise unittest.SkipTest('Chrome/Edge not installed')
        cls.tmp=tempfile.TemporaryDirectory(prefix='cdp-review-fixture-')
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
        cls.url=f'http://127.0.0.1:{cls.server.server_port}/fixture?id=test-item'
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        cls.endpoint=f'http://127.0.0.1:{port}'
        cls.proc=subprocess.Popen([str(binary),'--headless=new','--disable-gpu','--disable-extensions','--disable-background-networking','--no-first-run',
            '--remote-debugging-address=127.0.0.1',f'--remote-debugging-port={port}',f'--user-data-dir={cls.tmp.name}/profile','about:blank'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        cls.pw=sync_playwright().start()
        for _ in range(30):
            try:cls.browser=cls.pw.chromium.connect_over_cdp(cls.endpoint,timeout=1000);break
            except Exception:time.sleep(.2)
        else:cls.proc.terminate();cls.pw.stop();cls.server.shutdown();cls.tmp.cleanup();raise RuntimeError('Fixture browser did not start')
    @classmethod
    def tearDownClass(cls):
        try:cls.browser.new_browser_cdp_session().send('Browser.close')
        except Exception:pass
        cls.pw.stop()
        try:cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:cls.proc.terminate();cls.proc.wait(timeout=5)
        cls.server.shutdown();cls.server.server_close();cls.tmp.cleanup()
    def setUp(self):
        self.page=self.browser.contexts[0].new_page();self.page.goto(self.url)
        self.page.locator('.review').first.wait_for()
        self.out=pathlib.Path(self.tmp.name)/self._testMethodName
        self.cfg=dict(platform='LOCAL_FIXTURE',target_id='test-item',sort_filter='default;all',
            page_url_contains='/fixture',
            card_selector='.review',id_attribute='data-review-id',fields={
                'text':{'selector':'.text'},'rating_raw':{'selector':'.rating'},'date_raw':{'selector':'.date'},
                'sku_raw':{'selector':'.sku'},'author':{'selector':'.author'}},
            pagination={'mode':'next','selector':'#next'},end_selectors=['#end'],guard_text=['Fixture login required'],
            response_allowlist=[{'host':'127.0.0.1','path_prefix':'/comments'}],wait_ms=1000)
    def tearDown(self):self.page.close()
    def records(self):return [json.loads(s) for s in (self.out/'reviews.jsonl').read_text(encoding='utf-8').splitlines()]
    def test_all_until_observed_end_and_redacted_evidence(self):
        self.assertEqual(collect(self.page,self.cfg,self.out),'END_MARKER')
        rows=self.records();self.assertEqual([r['review_id'] for r in rows],['r1','r2','r3','r4'])
        self.assertTrue(all((self.out/r['evidence']).is_file() for r in rows))
        self.assertTrue(all(r['rating_raw']=='5 stars' and r['date_raw']=='2026-11-16' for r in rows))
        response_files=list((self.out/'responses').glob('[0-9]'*6+'.json'));self.assertTrue(response_files)
        self.assertTrue(all(json.loads(f.read_text())['data']['token']=='[REDACTED]' for f in response_files))
        with (self.out/'reviews.csv').open(encoding='utf-8-sig',newline='') as f:
            csv_rows=list(csv.DictReader(f))
        self.assertEqual(csv_rows[1]['text'],"'=1+1")
        self.assertEqual(rows[1]['text'],'=1+1')
    def test_limit_is_exact_and_overlapping_page_deduplicates(self):
        self.assertEqual(collect(self.page,self.cfg,self.out,limit=3),'LIMIT_REACHED')
        self.assertEqual(len(self.records()),3)
        state=json.loads((self.out/'state.json').read_text())
        self.assertEqual(state['requested_limit'],3)
        self.assertEqual(state['collection_mode'],'count')
    def test_explicit_page_budget_and_resume(self):
        self.assertEqual(collect(self.page,self.cfg,self.out,max_pages=1),'MAX_PAGES')
        self.assertEqual(len(self.records()),2)
        self.page.locator('#next').click();self.page.locator('[data-review-id="r3"]').wait_for()
        self.assertEqual(collect(self.page,self.cfg,self.out,limit=3),'LIMIT_REACHED')
        self.assertEqual(len(self.records()),3)
    def test_visible_login_prompt_stops_before_extract(self):
        self.page.evaluate("document.body.append(Object.assign(document.createElement('p'),{textContent:'Fixture login required'}))")
        self.assertEqual(collect(self.page,self.cfg,self.out),'WAIT_HUMAN')
        self.assertFalse((self.out/'reviews.jsonl').exists())
    def test_changed_identity_rejects_resume(self):
        collect(self.page,self.cfg,self.out,max_pages=1)
        with self.assertRaises(ValueError):collect(self.page,dict(self.cfg,target_id='different-item'),self.out)
    def test_nonlocal_endpoint_rejected(self):
        for url in ['http://example.com:9222','http://user:pass@127.0.0.1:9222','https://127.0.0.1:9222']:
            with self.assertRaises(ValueError):local_endpoint(url)
    def test_unverified_adapter_rejected(self):
        cfg=dict(self.cfg,page_url_contains='/fixture',verified=False)
        with self.assertRaises(ValueError):validate_config(cfg)
        validate_config(dict(cfg,verified=True))
    def test_unexpected_navigation_stops_before_extract(self):
        self.page.goto(self.url.replace('/fixture','/different-product'))
        self.assertEqual(collect(self.page,self.cfg,self.out),'PAGE_CHANGED')
        self.assertFalse((self.out/'reviews.jsonl').exists())
    def test_incomplete_checkpoint_does_not_overwrite_evidence(self):
        collect(self.page,self.cfg,self.out,max_pages=1)
        original={r['evidence']:(self.out/r['evidence']).read_bytes() for r in self.records()}
        (self.out/'pages/000001.json').unlink()
        state_path=self.out/'state.json';state=json.loads(state_path.read_text());state['pages_saved']=0
        state_path.write_text(json.dumps(state),encoding='utf-8')
        self.page.locator('#next').click();self.page.locator('[data-review-id="r3"]').wait_for()
        collect(self.page,self.cfg,self.out,limit=3)
        self.assertNotIn(self.records()[-1]['evidence'],original)
        self.assertTrue(all((self.out/name).read_bytes()==data for name,data in original.items()))
    def test_combined_purchase_metadata_is_separated_without_inventing_date(self):
        card=self.page.locator('.review').first
        card.locator('.date').evaluate("e=>e.textContent='2026年10月19日已购：【轻享装】猫犬洁齿水237ml'")
        cfg=dict(self.cfg,fields=dict(self.cfg['fields'],
            date_raw={'selector':'.date','pattern':r'(\d{4}年\d{1,2}月\d{1,2}日)'},
            sku_raw={'selector':'.date','pattern':r'已购[:：]\s*(.*)'}))
        parsed=read_card(card,cfg)
        self.assertEqual(parsed['date_raw'],'2026年10月19日')
        self.assertEqual(parsed['sku_raw'],'【轻享装】猫犬洁齿水237ml')
    def test_recycled_card_during_screenshot_is_not_saved_as_original(self):
        self.page.evaluate('''()=>{let spacer=document.createElement('div');spacer.style.height='1200px';document.body.prepend(spacer);window.scrollTo(0,0);window.addEventListener('scroll',()=>{document.querySelector('.text').textContent='Recycled review'}, {once:true})}''')
        # Review ID is absent in this case, so the changed text must be detected.
        cfg=dict(self.cfg,id_attribute=None)
        self.assertEqual(collect(self.page,cfg,self.out,limit=1),'CARD_CHANGED_DURING_CAPTURE')
        self.assertFalse((self.out/'reviews.jsonl').exists())
    def test_viewport_scroll_captures_visible_cards_without_skipping_overlap(self):
        self.page.locator('main').evaluate("e=>{e.style.height='400px';e.style.overflowY='auto'}")
        cfg=dict(self.cfg,capture_viewport='main',pagination={'mode':'scroll','selector':'main','step_px':150})
        self.assertEqual(collect(self.page,cfg,self.out,limit=2),'LIMIT_REACHED')
        self.assertEqual([r['review_id'] for r in self.records()],['r1','r2'])

if __name__=='__main__':unittest.main()
