import struct, urllib.request, time, math, collections, sys
import numpy as np
ST={'req':0,'bytes':0}
def get(u,a,b):
    r=urllib.request.urlopen(urllib.request.Request(u,headers={'Range':f'bytes={a}-{b}'}),timeout=60).read(); ST['req']+=1; ST['bytes']+=len(r); return r
def lzw(data):
    out=bytearray(); tab=[bytes([i]) for i in range(256)]+[b'',b'']; bits=9; pos=0; prev=None; n=len(data)*8
    while pos+bits<=n:
        i=pos>>3; v=int.from_bytes(data[i:i+3].ljust(3,b'\0'),'big'); code=(v>>(24-(pos&7)-bits))&((1<<bits)-1); pos+=bits
        if code==256: tab=tab[:258]; bits=9; prev=None; continue
        if code==257: break
        if prev is None: e=tab[code]; out+=e; prev=e; continue
        e=tab[code] if code<len(tab) else prev+prev[:1]
        out+=e; tab.append(prev+e[:1]); prev=e
        if len(tab)+1>=(1<<bits) and bits<12: bits+=1
    return bytes(out)
u=sys.argv[1]; lon,lat=float(sys.argv[2]),float(sys.argv[3]); t0=time.time()
h=get(u,0,16383); bo='<'
off=struct.unpack(bo+'Q',h[8:16])[0]; n=struct.unpack(bo+'Q',h[off:off+8])[0]; T={}
for k in range(n):
    e=h[off+8+k*20:off+28+k*20]; tag,typ,cnt=struct.unpack(bo+'HHQ',e[:12]); T[tag]=(typ,cnt,e[12:20])
W=struct.unpack(bo+'Q',T[256][2])[0]; H=struct.unpack(bo+'Q',T[257][2])[0]; tw=struct.unpack(bo+'H',T[322][2][:2])[0]
def arr(tag,fmt,sz):
    typ,cnt,v=T[tag]; o=struct.unpack(bo+'Q',v)[0]; return o
o1=arr(33550,'d',8); o2=arr(33922,'d',8); g=get(u,min(o1,o2),max(o1,o2)+48); ps=struct.unpack(bo+'3d',g[o1-min(o1,o2):o1-min(o1,o2)+24]); tp=struct.unpack(bo+'6d',g[o2-min(o1,o2):o2-min(o1,o2)+48])
col=int((lon-tp[3])/ps[0]); row=int((tp[4]-lat)/ps[1]); ntx=math.ceil(W/tw); tx,ty=col//tw,row//tw; k=ty*ntx+tx
oo=arr(324,'Q',8); ob=arr(325,'I',4)
to=struct.unpack(bo+'Q',get(u,oo+8*k,oo+8*k+7))[0]; tb=struct.unpack(bo+'I',get(u,ob+4*k,ob+4*k+3))[0]
raw=get(u,to,to+tb-1); a=np.frombuffer(lzw(raw)[:tw*tw],np.uint8).reshape(tw,tw); a=np.cumsum(a,axis=1,dtype=np.uint8)
print('raster',W,'x',H,'pixel %.6f graus'%ps[0],'tile',tw,'tile idx',k,'de',ntx*math.ceil(H/tw))
print('classes no tile (codigo:pixels):',dict(collections.Counter(a.ravel().tolist()).most_common(8)))
print('classe no ponto:',a[row%tw,col%tw])
print('requests',ST['req'],'bytes',ST['bytes'],'tempo %.2fs'%(time.time()-t0))
np.save(sys.argv[4],a)
