"""Resume one already-open shopping app via a verified task card, never start an intent."""
import argparse,pathlib,re,subprocess,xml.etree.ElementTree as ET

def find_task(root,title):
    matches=[n for n in root.iter('node') if n.get('package')=='com.android.launcher' and n.get('content-desc')==title and n.get('clickable')=='true']
    if len(matches)!=1:raise ValueError('Shopping task card missing or ambiguous; user must open the app')
    b=list(map(int,re.findall(r'\d+',matches[0].get('bounds',''))))
    if len(b)!=4 or b[2]-b[0]<100 or b[3]-b[1]<200:raise ValueError('Task card is not sufficiently visible')
    return (b[0]+b[2])//2,(b[1]+b[3])//2

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('adb','serial','package','title','out'):p.add_argument('--'+k,required=True)
    p.add_argument('action',choices=['background','resume'])
    a=p.parse_args();out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
    def adb(*args):
        r=subprocess.run([a.adb,'-s',a.serial,*args],capture_output=True,timeout=30)
        if r.returncode:raise RuntimeError(r.stderr.decode('utf-8','replace'))
        return r.stdout
    status=adb('shell','dumpsys','activity','activities').decode('utf-8','replace')
    lines=[l for l in status.splitlines() if 'topResumedActivity=' in l or 'mResumedActivity:' in l]
    foreground='\n'.join(lines)
    if a.action=='background':
        if a.package+'/' not in foreground:raise ValueError('Expected shopping app is not foreground')
        adb('shell','input','keyevent','187')
    adb('shell','uiautomator','dump','/sdcard/review_resume.xml')
    raw=adb('shell','cat','/sdcard/review_resume.xml');root=ET.fromstring(raw)
    x,y=find_task(root,a.title)
    (out/'resume-task.xml').write_bytes(raw)
    if a.action=='resume':
        # Never choose from an animation frame; the current XML task card supplies coordinates.
        adb('shell','input','tap',str(x),str(y))
    print(a.action,'verified_task='+a.title)

if __name__=='__main__':main()
