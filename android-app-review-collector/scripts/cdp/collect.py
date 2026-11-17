"""Attach, observe, collect visible review cards. Never replay authenticated APIs."""
import argparse
import csv
import hashlib
import itertools
import json
import pathlib
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def clean_url(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc.split('@')[-1], p.path, '', ''))


def local_endpoint(url):
    p = urlsplit(url)
    if p.scheme != 'http' or p.hostname not in {'localhost', '127.0.0.1', '::1'} or p.username or p.password or p.query or p.fragment:
        raise ValueError('CDP端点必须是无凭据的本机 http://127.0.0.1:端口')
    return url


def validate_config(cfg):
    for key in ('platform', 'target_id', 'sort_filter', 'page_url_contains', 'card_selector', 'fields'):
        if not cfg.get(key):
            raise ValueError('配置缺少有效字段: ' + key)
    if cfg.get('verified') is not True or not cfg['fields'].get('text', {}).get('selector'):
        raise ValueError('先观察并核验页面，填写正文选择器，再设 verified=true')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


SENSITIVE = re.compile(r'cookie|token|password|authorization|secret|session|email|phone|mobile|address|nickname|username|avatar|userid|user_id|openid', re.I)


def redact(v):
    if isinstance(v, dict):
        return {k: '[REDACTED]' if SENSITIVE.search(k) else redact(x) for k, x in v.items()}
    if isinstance(v, list):
        return [redact(x) for x in v]
    if isinstance(v, str):
        v = re.sub(r'(?i)Bearer\s+[A-Za-z0-9._~+/=-]+', '[REDACTED]', v)
        v = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[EMAIL]', v)
        # URLs in payloads can carry signed query parameters.
        return re.sub(r'https?://[^\s"<>]+', lambda m: clean_url(m.group()), v)
    return v


def export_csv(out, rows):
    fields = ['key', 'platform', 'target_id', 'sort_filter', 'review_id', 'text', 'rating_raw', 'date_raw', 'sku_raw', 'author_key', 'source_url', 'captured_at', 'image_source', 'evidence']
    with (out / 'reviews.csv').open('w', newline='', encoding='utf-8-sig') as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for row in rows:
            safe = dict(row)
            for k, v in safe.items():
                if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')):
                    safe[k] = "'" + v
            w.writerow(safe)


def read_card(card, cfg):
    v = {}
    for key, spec in cfg['fields'].items():
        loc = card.locator(spec['selector'])
        v[key] = ((loc.first.get_attribute(spec['attribute']) if spec.get('attribute') else loc.first.inner_text()) or '').strip() if loc.count() else ''
        if spec.get('pattern'):
            match = re.search(spec['pattern'], v[key], re.S)
            v[key] = match.group(spec.get('group', 1)).strip() if match else ''
    author = v.pop('author', '')
    v['author_key'] = digest(cfg['platform'] + '|' + cfg['target_id'] + '|' + author)[:20] if author else ''
    v['review_id'] = (card.get_attribute(cfg['id_attribute']) or '') if cfg.get('id_attribute') else ''
    fingerprint = [v['review_id']] if v['review_id'] else [v.get('text',''), v.get('date_raw', ''), v['author_key'], v.get('sku_raw', '')]
    v['key'] = digest(json.dumps([cfg['platform'], cfg['target_id']] + fingerprint, ensure_ascii=False))
    return v


def collect(page, cfg, out, max_pages=None, max_minutes=None, limit=None):
    out.mkdir(parents=True, exist_ok=True)
    identity = {k: cfg[k] for k in ('platform', 'target_id', 'sort_filter')}
    identity['adapter_hash'] = digest(json.dumps(cfg, sort_keys=True, ensure_ascii=False))
    statefile = out / 'state.json'
    previous = json.loads(statefile.read_text(encoding='utf-8')) if statefile.exists() else {}
    if previous and previous['identity'] != identity:
        raise ValueError('输出目录属于其他任务或适配器已改变，请使用新目录')
    rows = []
    datafile = out / 'reviews.jsonl'
    if datafile.exists():
        rows = [json.loads(x) for x in datafile.read_text(encoding='utf-8').split('\n') if x.strip()]
    keys = {r['key'] for r in rows}
    offset = previous.get('pages_saved', 0)
    # Avoid overwriting page evidence from a run interrupted before its checkpoint.
    offset = max([offset] + [int(p.stem.split('-')[0]) for p in (out / 'pages').iterdir()
                            if p.suffix in ('.json', '.png') and p.stem.split('-')[0].isdigit()]) if (out / 'pages').exists() else offset
    started = time.monotonic()
    reason = 'RUNNING'
    pages_saved = offset
    response_count = len(list((out / 'responses').glob('*.json')))
    queue = []
    allow = cfg.get('response_allowlist', [])

    def on_response(r):
        p = urlsplit(r.url)
        if r.request.resource_type in {'xhr', 'fetch'} and any(p.hostname == a['host'] and p.path.startswith(a['path_prefix']) for a in allow):
            if len(queue) < 100:
                queue.append(r)

    def drain():
        nonlocal response_count
        while queue:
            r = queue.pop(0)
            if r.status in (401, 403, 429):
                raise RuntimeError('HTTP_' + str(r.status))
            if 'json' not in r.headers.get('content-type', ''):
                continue
            raw = r.body()
            if len(raw) > cfg.get('max_response_bytes', 2000000):
                continue
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                continue
            response_count += 1
            dest = out / 'responses' / f'{response_count:06}.json'
            write(dest, {'url': clean_url(r.url), 'status': r.status, 'captured_at': stamp(), 'redacted': True, 'data': redact(value)})
            write(dest.with_suffix('.sha.json'), {'sha256': hashlib.sha256(dest.read_bytes()).hexdigest()})

    def guard():
        if cfg.get('page_url_contains') and cfg['page_url_contains'] not in page.url:
            raise RuntimeError('PAGE_CHANGED')
        if max_minutes is not None and time.monotonic() - started >= max_minutes * 60:
            raise RuntimeError('TIME_LIMIT')
        texts = []
        for frame in page.frames:
            for selector in cfg.get('guard_selectors', []):
                loc = frame.locator(selector)
                if any(loc.nth(i).is_visible() for i in range(loc.count())):
                    raise RuntimeError('WAIT_HUMAN')
            try:
                texts.append(frame.locator('body').inner_text(timeout=1500))
            except Exception:
                continue
        if any(word in '\n'.join(texts) for word in cfg.get('guard_text', [])):
            raise RuntimeError('WAIT_HUMAN')

    def root():
        needle = cfg.get('frame_url_contains')
        if not needle:
            return page
        hits = [x for x in page.frames if needle in x.url]
        if len(hits) != 1:
            raise RuntimeError('FRAME_NOT_UNIQUE')
        return hits[0]

    def extract():
        cards = root().locator(cfg['card_selector'])
        values = []
        viewport = root().locator(cfg['capture_viewport']).bounding_box() if cfg.get('capture_viewport') else None
        for n in range(cards.count()):
            card = cards.nth(n)
            if not card.is_visible():
                continue
            if viewport:
                box = card.bounding_box()
                if not box or box['y'] < viewport['y'] + cfg.get('viewport_top_inset', 0) - 1 or box['y'] + box['height'] > viewport['y'] + viewport['height'] + 1:
                    continue
            v = read_card(card, cfg)
            if not v.get('text'):
                continue
            values.append((n, v))
        return values

    def signature():
        keys_now = [v['key'] for _, v in extract()]
        if cfg.get('capture_viewport'):
            keys_now.append(str(root().locator(cfg['capture_viewport']).evaluate('(e)=>e.scrollTop')))
        return keys_now

    def end_reached():
        return any(root().locator(s).count() and root().locator(s).first.is_visible()
                   for s in cfg.get('end_selectors', []))

    page.on('response', on_response)
    stagnant = 0
    try:
        for batch in (range(max_pages) if max_pages is not None else itertools.count()):
            if limit is not None and len(rows) >= limit:
                reason = 'LIMIT_REACHED'
                break
            guard()
            values = extract()
            if not values and not cfg.get('capture_viewport'):
                reason = 'END_MARKER' if end_reached() else 'NO_REVIEW_TEXT'
                break
            fresh = [(n, v) for n, v in values if v['key'] not in keys]
            stagnant = stagnant + 1 if not fresh else 0
            if not fresh and (not cfg.get('capture_viewport') or stagnant >= 6):
                reason = 'END_MARKER' if end_reached() else 'NO_NEW_REVIEWS'
                break
            number = offset + batch + 1
            evidence_dir = out / 'pages'
            evidence_dir.mkdir(exist_ok=True)
            saved = []
            checksums = {}
            for n, v in fresh:
                if limit is not None and len(rows) >= limit:
                    break
                if v['key'] in keys:
                    continue
                dest = evidence_dir / f'{number:06}-{n:04}.png'
                card = root().locator(cfg['card_selector']).nth(n)
                if read_card(card, cfg) != v:
                    raise RuntimeError('CARD_CHANGED_BEFORE_CAPTURE')
                if cfg.get('media_selector'):
                    for attempt in range(10):
                        if card.locator(cfg['media_selector']).evaluate_all('(els)=>els.every(e=>e.complete && e.naturalWidth>0)'):
                            break
                        page.wait_for_timeout(300)
                    else:
                        raise RuntimeError('MEDIA_NOT_READY')
                card.screenshot(path=str(dest), timeout=10000)
                if read_card(card, cfg) != v:
                    raise RuntimeError('CARD_CHANGED_DURING_CAPTURE')
                checksums[dest.name] = hashlib.sha256(dest.read_bytes()).hexdigest()
                row = {**v, **{k: cfg[k] for k in ('platform', 'target_id', 'sort_filter')}, 'source_url': clean_url(page.url), 'captured_at': stamp(), 'evidence': dest.relative_to(out).as_posix(), 'image_source': '页面截图，非原图'}
                with datafile.open('a', encoding='utf-8') as h:
                    h.write(json.dumps(row, ensure_ascii=False) + '\n')
                keys.add(v['key'])
                rows.append(row)
                saved.append(row)
            write(evidence_dir / f'{number:06}.json', {'rows': saved, 'screenshots_sha256': checksums})
            pages_saved = number
            drain()
            write(statefile, {'identity': identity, 'pages_saved': pages_saved, 'unique_reviews': len(rows), 'reason': 'RUNNING', 'updated_at': stamp()})
            print(json.dumps({'page': number, 'unique_reviews': len(rows)}, ensure_ascii=False), flush=True)
            if limit is not None and len(rows) >= limit:
                reason = 'LIMIT_REACHED'
                break
            if end_reached():
                reason = 'END_MARKER'
                break
            if max_pages is not None and batch + 1 == max_pages:
                reason = 'MAX_PAGES'
                break
            pagination = cfg.get('pagination', {'mode': 'none'})
            mode = pagination.get('mode', 'none')
            old_sig = signature()
            guard()
            if mode == 'none':
                reason = 'SINGLE_PAGE'
                break
            if mode == 'next':
                loc = root().locator(pagination['selector'])
                if loc.count() != 1 or not loc.is_visible():
                    reason = 'NO_NEXT_CONTROL'
                    break
                if loc.is_disabled() or loc.get_attribute('aria-disabled') == 'true':
                    reason = 'NEXT_DISABLED'
                    break
                loc.click(timeout=10000)
            elif mode == 'scroll':
                if pagination.get('selector'):
                    root().locator(pagination['selector']).evaluate('(e,step) => {e.scrollTop=step ? e.scrollTop+step : e.scrollHeight}', pagination.get('step_px', 0))
                else:
                    root().evaluate('window.scrollTo(0,document.documentElement.scrollHeight)')
            else:
                raise ValueError('pagination.mode must be next, scroll or none')
            page.wait_for_timeout(max(1000, cfg.get('wait_ms', 3000)))
            until = time.monotonic() + cfg.get('change_timeout_ms', 15000) / 1000
            while signature() == old_sig and time.monotonic() < until:
                guard()
                page.wait_for_timeout(500)
            drain()
            if signature() == old_sig:
                reason = 'CONTENT_UNCHANGED'
                break
    except KeyboardInterrupt:
        reason = 'INTERRUPTED'
    except Exception as e:
        # No exception text: browser errors may include signed URLs or payloads.
        reason = str(e) if isinstance(e, RuntimeError) else 'ERROR_' + type(e).__name__
    finally:
        page.remove_listener('response', on_response)
        export_csv(out, rows)
        write(statefile, {'identity': identity, 'pages_saved': pages_saved, 'unique_reviews': len(rows), 'requested_limit': limit, 'collection_mode': 'all' if limit is None else 'count', 'reason': reason, 'updated_at': stamp(), 'elapsed_seconds': round(time.monotonic()-started, 1)})
    print(json.dumps({'unique_reviews': len(rows), 'reason': reason, 'output': str(out)}, ensure_ascii=False))
    return reason


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['probe', 'collect'])
    parser.add_argument('--cdp', default='http://127.0.0.1:9222', type=local_endpoint)
    parser.add_argument('--config', type=pathlib.Path)
    parser.add_argument('--out', type=pathlib.Path)
    parser.add_argument('--limit', type=int, default=None, help='省略表示全部可访问评论；指定时按唯一条数停止')
    parser.add_argument('--max-pages', type=int, default=None, help='可选页数预算，达到时属于部分完成')
    parser.add_argument('--max-minutes', type=float, default=None, help='可选时间预算，达到时属于部分完成')
    args = parser.parse_args()
    if any(v is not None and v <= 0 for v in (args.limit, args.max_pages, args.max_minutes)):
        parser.error('条数、页数和分钟数必须大于0')
    cfg = None
    if args.mode == 'collect':
        if not args.config or not args.out:
            parser.error('collect需要--config和--out')
        cfg = json.loads(args.config.read_text(encoding='utf-8-sig'))
        try:
            validate_config(cfg)
        except ValueError as e:
            parser.error(str(e))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp, timeout=15000)
        pages = [p for ctx in browser.contexts for p in ctx.pages if not p.is_closed()]
        if args.mode == 'probe':
            print(json.dumps([{'index': i, 'title': p.title(), 'url': clean_url(p.url)} for i, p in enumerate(pages)], ensure_ascii=False, indent=2))
            return
        hits = [p for p in pages if cfg['page_url_contains'] in p.url]
        if len(hits) != 1:
            parser.error('目标标签页不唯一，请收紧page_url_contains')
        hits[0].set_default_timeout(5000)
        result = collect(hits[0], cfg, args.out.resolve(), args.max_pages, args.max_minutes, args.limit)
        if result.startswith(('ERROR_', 'WAIT_', 'HTTP_', 'CARD_CHANGED_', 'MEDIA_NOT_READY', 'PAGE_CHANGED')):
            raise SystemExit(2)


if __name__ == '__main__':
    main()
