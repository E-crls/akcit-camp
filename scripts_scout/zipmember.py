"""Lista um ZIP remoto e extrai membros por HTTP Range, sem baixar o ZIP inteiro."""
import struct, urllib.request, zlib, sys, re, time
ST={'req':0,'bytes':0}
H={'User-Agent':'Mozilla/5.0'}
def get(u,a,b):
    r=urllib.request.urlopen(urllib.request.Request(u,headers={**H,'Range':f'bytes={a}-{b}'}),timeout=90).read(); ST['req']+=1; ST['bytes']+=len(r); return r
def listing(u):
    size=int(urllib.request.urlopen(urllib.request.Request(u,method='HEAD',headers=H),timeout=60).headers['Content-Length'])
    tail=get(u,size-65536,size-1); i=tail.rfind(b'PK\x05\x06')
    n,cdsize,cdoff=struct.unpack('<HII',tail[i+10:i+20])
    cd=get(u,cdoff,cdoff+cdsize-1); p=0; out=[]
    while p<len(cd) and cd[p:p+4]==b'PK\x01\x02':
        meth=struct.unpack('<H',cd[p+10:p+12])[0]; csz,usz=struct.unpack('<II',cd[p+20:p+28]); fl,el,cl=struct.unpack('<HHH',cd[p+28:p+34]); lho=struct.unpack('<I',cd[p+42:p+46])[0]
        name=cd[p+46:p+46+fl].decode('cp437'); out.append((name,meth,csz,usz,lho)); p+=46+fl+el+cl
    return size,out
def extract(u,m):
    name,meth,csz,usz,lho=m; lh=get(u,lho,lho+29); fl,el=struct.unpack('<HH',lh[26:30])
    data=get(u,lho+30+fl+el,lho+30+fl+el+csz-1)
    return zlib.decompress(data,-15) if meth==8 else data
if __name__=='__main__':
    u=sys.argv[1]; t=time.time(); size,mem=listing(u)
    print('zip',size,'membros',len(mem),'bytes lidos p/ listar',ST['bytes'])
    go=[m for m in mem if re.search(r'_GO_',m[0])]; print('membros GO',len(go),'soma comprimida GO',sum(m[2] for m in go))
    for m in go[:40]: print(' ',m[0],m[2],m[3])
    pat=sys.argv[2]; sel=[m for m in go if pat in m[0]][0]
    raw=extract(u,sel); open(sys.argv[3],'wb').write(raw)
    print('extraido',sel[0],len(raw),'bytes; total transferido',ST['bytes'],'em',ST['req'],'requests, %.1fs'%(time.time()-t))
    print(raw[:1200].decode('latin-1'))
