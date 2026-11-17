"""Write user-provided share text through scrcpy 5.0.1's documented control protocol.

No clipboard reads, video/audio capture, application launching, or permission changes.
Uses only SET_CLIPBOARD and its sequence ACK, with clipboard autosync disabled.
Protocol: https://github.com/Genymobile/scrcpy/blob/v5.0.1/app/src/control_msg.c
"""
import argparse,hashlib,json,pathlib,secrets,socket,struct,subprocess,time

SERVER_SHA256='764eb6f79811d5211fe9df341120882ba9994c7a61b897d7bf3fb662e53bc536'

def clipboard_packet(text,sequence=1):
    payload=text.encode('utf-8')
    if not payload or len(payload)>(1<<18)-14: raise ValueError('Invalid clipboard payload size')
    # SET_CLIPBOARD = 9; sequence uint64; paste=false; byte length uint32.
    return struct.pack('>BQBI',9,sequence,0,len(payload))+payload

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('adb','serial','server','text-file','out'):p.add_argument('--'+key,required=True)
    a=p.parse_args();server=pathlib.Path(a.server)
    if hashlib.sha256(server.read_bytes()).hexdigest()!=SERVER_SHA256:raise ValueError('Unverified scrcpy server')
    text=pathlib.Path(a.text_file).read_text(encoding='utf-8-sig').strip();packet=clipboard_packet(text)
    out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
    def adb(*args):
        r=subprocess.run([a.adb,'-s',a.serial,*args],capture_output=True,timeout=30)
        if r.returncode:raise RuntimeError(r.stderr.decode('utf-8','replace'))
        return r.stdout
    scid=f'{secrets.randbits(31):08x}';port=None;proc=None;sock=None
    try:
        adb('push',str(server),'/data/local/tmp/scrcpy-server.jar')
        port=adb('forward','tcp:0','localabstract:scrcpy_'+scid).decode().strip()
        command=[a.adb,'-s',a.serial,'shell','CLASSPATH=/data/local/tmp/scrcpy-server.jar','app_process','/','com.genymobile.scrcpy.Server','5.0.1','scid='+scid,'log_level=warn','video=false','audio=false','control=true','tunnel_forward=true','clipboard_autosync=false','send_device_meta=false','send_dummy_byte=false','power_on=false','cleanup=true']
        proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        time.sleep(2)
        sock=socket.create_connection(('127.0.0.1',int(port)),timeout=8)
        sock.settimeout(8);sock.sendall(packet)
        ack=b''
        while len(ack)<9:
            piece=sock.recv(9-len(ack))
            if not piece:raise RuntimeError('Control socket closed before clipboard acknowledgement')
            ack+=piece
        if ack!=struct.pack('>BQ',1,1):raise RuntimeError('Unexpected clipboard acknowledgement')
        receipt=dict(operation='SET_CLIPBOARD',server_version='5.0.1',server_sha256=SERVER_SHA256,clipboard_autosync=False,paste=False,utf8_bytes=len(text.encode()),text_sha256=hashlib.sha256(text.encode()).hexdigest(),acknowledged=True)
        (out/'clipboard-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        print(json.dumps(receipt))
    finally:
        if sock:sock.close()
        if proc:
            try:proc.wait(timeout=4)
            except subprocess.TimeoutExpired:proc.terminate();proc.wait(timeout=4)
        if port:adb('forward','--remove','tcp:'+port)

if __name__=='__main__':main()
