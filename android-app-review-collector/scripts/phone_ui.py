"""Observe an already-open Android shopping app and operate verified visible controls.

This helper does not launch apps, open intents, change permissions, or read clipboard.
One action always produces a fresh screenshot/XML observation.
"""
import argparse, hashlib, json, pathlib, re, shlex, subprocess
import xml.etree.ElementTree as ET

BLOCKED=re.compile(r'立即购买|现在下单|提交订单|购物车|领券|抢购|去支付|确认支付|付款|客服|发送消息|收藏|点赞|有用|登录|验证码|隐私设置|系统设置')

def signature(node):
    return {k:node.get(k,'') for k in ('text','content-desc','resource-id','class','package','bounds')}

def verify_search_text(root,package,expected):
    fields=[n for n in root.iter('node') if n.get('package')==package and n.get('class','').endswith('EditText') and n.get('focused')=='true']
    if len(fields)!=1 or fields[0].get('text')!=expected:
        raise ValueError('Search text differs from requested share code; inspect input method before submitting')

def validate_target(saved, live, package):
    if live is None or signature(saved)!=signature(live):
        raise ValueError('Control changed since observation; inspect a new snapshot')
    if live.get('package')!=package:
        raise ValueError('Control is outside the configured shopping app')
    if BLOCKED.search(live.get('text','')+' '+live.get('content-desc','')):
        raise ValueError('Control is outside review-navigation scope')
    b=list(map(int,re.findall(r'\d+',live.get('bounds',''))))
    if len(b)!=4 or b[2]<=b[0] or b[3]<=b[1]: raise ValueError('Invalid control rectangle')
    if live.get('enabled')=='false': raise ValueError('Control is disabled')
    return (b[0]+b[2])//2,(b[1]+b[3])//2

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--adb',required=True);p.add_argument('--serial',required=True)
    p.add_argument('--package',required=True);p.add_argument('--out',required=True)
    p.add_argument('action',choices=['snapshot','tap','type','submit','back'])
    p.add_argument('--node',type=int);p.add_argument('--text')
    a=p.parse_args();out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
    def adb(*args):
        r=subprocess.run([a.adb,'-s',a.serial,*args],capture_output=True,timeout=35)
        if r.returncode: raise RuntimeError(r.stderr.decode('utf-8','replace'))
        return r.stdout
    def capture_xml():
        adb('shell','uiautomator','dump','/sdcard/review_navigation.xml')
        raw=adb('shell','cat','/sdcard/review_navigation.xml')
        root=ET.fromstring(raw)
        # Only operate when the visible top-level app is the specified target.
        windows=[n for n in root if n.get('package')]
        if not windows or windows[0].get('package')!=a.package:
            raise ValueError('Target app is not the observed foreground window; user must open it')
        return raw,root
    raw,root=capture_xml();statefile=out/'latest.json'
    if a.action!='snapshot':
        if not statefile.exists(): raise ValueError('Capture and inspect a snapshot first')
        old=json.loads(statefile.read_text(encoding='utf-8'))
        if old['package']!=a.package or old['serial']!=a.serial:
            raise ValueError('Observation belongs to another app or device')
        if a.action=='tap':
            if a.node is None: p.error('--node is required')
            prior=ET.parse(out/old['xml']).getroot();prior_nodes=list(prior.iter('node'))
            if not 0<=a.node<len(prior_nodes): raise ValueError('Unknown observed node')
            saved=prior_nodes[a.node]
            matches=[n for n in root.iter('node') if signature(n)==signature(saved)]
            if len(matches)!=1: raise ValueError('Control is missing or ambiguous; observe again')
            x,y=validate_target(saved,matches[0],a.package)
            adb('shell','input','tap',str(x),str(y))
        elif a.action in ('type','submit'):
            focused=[n for n in root.iter('node') if n.get('focused')=='true' and n.get('class','').endswith('EditText') and n.get('package')==a.package]
            if len(focused)!=1: raise ValueError('A single observed search input must be focused first')
            if focused[0].get('password')=='true': raise ValueError('Credential input is out of scope')
            if a.action=='type':
                if not a.text or not a.text.isascii(): raise ValueError('This input helper accepts ASCII share codes only')
                if len(a.text)>512 or '\n' in a.text: raise ValueError('Invalid search text')
                adb('shell','input','text',shlex.quote(a.text))
            else: adb('shell','input','keyevent','66')
        else: adb('shell','input','keyevent','4')
        raw,root=capture_xml()
    index=max([int(f.stem.split('-')[-1]) for f in out.glob('ui-*.xml')]+[0])+1
    stem=f'ui-{index:03}'
    (out/(stem+'.xml')).write_bytes(raw)
    png=adb('exec-out','screencap','-p')
    if not png.startswith(b'\x89PNG'): raise ValueError('Invalid screenshot')
    (out/(stem+'.png')).write_bytes(png)
    state=dict(serial=a.serial,package=a.package,xml=stem+'.xml',screenshot=stem+'.png',sha256=hashlib.sha256(raw).hexdigest())
    statefile.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    if a.action=='type':verify_search_text(root,a.package,a.text)
    visible=[]
    for i,n in enumerate(root.iter('node')):
        if n.get('text') or n.get('content-desc') or n.get('class','').endswith('EditText'):
            visible.append(dict(index=i,**signature(n),focused=n.get('focused'),clickable=n.get('clickable')))
    print(json.dumps(dict(screenshot=stem+'.png',nodes=visible),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
