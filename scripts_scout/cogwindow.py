"""Leitura janelada de COG Sentinel-2 por HTTP Range, só com stdlib + numpy.
Uso: python cogwindow.py <lon> <lat> <tamanho_janela> <item_json_ou_id>"""
import struct, urllib.request, zlib, json, math, time, sys
import numpy as np
STATS={'requests':0,'bytes':0}
def get(url,start,end):
    req=urllib.request.Request(url,headers={'Range':f'bytes={start}-{end}'})
    b=urllib.request.urlopen(req,timeout=60).read(); STATS['requests']+=1; STATS['bytes']+=len(b); return b
TYPES={1:('B',1),2:('s',1),3:('H',2),4:('I',4),12:('d',8),16:('Q',8)}
class COG:
    def __init__(s,url):
        s.url=url; h=get(url,0,65535); s.h=h
        bo='<' if h[:2]==b'II' else '>'; s.bo=bo
        assert struct.unpack(bo+'H',h[2:4])[0]==42
        off=struct.unpack(bo+'I',h[4:8])[0]; n=struct.unpack(bo+'H',h[off:off+2])[0]; s.t={}
        for i in range(n):
            e=h[off+2+i*12:off+14+i*12]; tag,typ,cnt=struct.unpack(bo+'HHI',e[:8]); f,sz=TYPES[typ]
            if cnt*sz<=4: raw=e[8:8+cnt*sz]
            else:
                o=struct.unpack(bo+'I',e[8:12])[0]
                raw=h[o:o+cnt*sz] if o+cnt*sz<=len(h) else get(url,o,o+cnt*sz-1)
            s.t[tag]=raw if typ==2 else struct.unpack(bo+f*cnt,raw)
        s.W=s.t[256][0]; s.H=s.t[257][0]; s.tw=s.t[322][0]; s.th=s.t[323][0]
        s.comp=s.t[259][0]; s.pred=s.t.get(317,(1,))[0]
        sx,sy,_=s.t[33550]; _,_,_,X0,Y0,_=s.t[33922]; s.gt=(X0,sx,Y0,-sy)
        s.epsg=[s.t[34735][i+3] for i in range(4,len(s.t[34735]),4) if s.t[34735][i] in (3072,2048)][0]
        s.ntx=math.ceil(s.W/s.tw)
    def tile(s,tx,ty):
        k=ty*s.ntx+tx; o=s.t[324][k]; n=s.t[325][k]
        raw=get(s.url,o,o+n-1); assert s.comp in (8,32946)
        dt={8:np.uint8,16:np.uint16}[s.t[258][0]]
        a=np.frombuffer(zlib.decompress(raw),dtype=np.dtype(dt).newbyteorder(s.bo)).reshape(s.th,s.tw).astype(dt)
        if s.pred==2: a=np.cumsum(a,axis=1,dtype=dt)
        return a
    def window(s,col,row,w,h):
        out=np.zeros((h,w),{8:np.uint8,16:np.uint16}[s.t[258][0]])
        for ty in range(row//s.th,(row+h-1)//s.th+1):
            for tx in range(col//s.tw,(col+w-1)//s.tw+1):
                a=s.tile(tx,ty); x0=tx*s.tw; y0=ty*s.th
                c0=max(col,x0); c1=min(col+w,x0+s.tw); r0=max(row,y0); r1=min(row+h,y0+s.th)
                out[r0-row:r1-row,c0-col:c1-col]=a[r0-y0:r1-y0,c0-x0:c1-x0]
        return out
def utm(lon,lat,zone):  # WGS84 -> UTM sul (EPSG:327zz)
    a=6378137.0; f=1/298.257223563; e2=f*(2-f); k0=0.9996; ep2=e2/(1-e2)
    lon0=math.radians((zone-1)*6-180+3); phi=math.radians(lat); lam=math.radians(lon)
    N=a/math.sqrt(1-e2*math.sin(phi)**2); T=math.tan(phi)**2; C=ep2*math.cos(phi)**2; A=math.cos(phi)*(lam-lon0)
    M=a*((1-e2/4-3*e2**2/64-5*e2**3/256)*phi-(3*e2/8+3*e2**2/32+45*e2**3/1024)*math.sin(2*phi)+(15*e2**2/256+45*e2**3/1024)*math.sin(4*phi)-(35*e2**3/3072)*math.sin(6*phi))
    x=k0*N*(A+(1-T+C)*A**3/6+(5-18*T+T*T+72*C-58*ep2)*A**5/120)+500000
    y=k0*(M+N*math.tan(phi)*(A*A/2+(5-T+9*C+4*C*C)*A**4/24+(61-58*T+T*T+600*C-330*ep2)*A**6/720))
    return x, y+10000000 if lat<0 else y
if __name__=='__main__':
    lon,lat,size=float(sys.argv[1]),float(sys.argv[2]),int(sys.argv[3]); item=json.load(open(sys.argv[4]))[0]
    t0=time.time()
    red=COG(item['assets']['red']['href']); nir=COG(item['assets']['nir']['href'])
    zone=red.epsg-32700; x,y=utm(lon,lat,zone); X0,sx,Y0,sy=red.gt
    col=int((x-X0)/sx)-size//2; row=int((y-Y0)/sy)-size//2
    print('item',item['id'],'EPSG',red.epsg,'compressao',red.comp,'preditor',red.pred,'tile',red.tw,'img',red.W,'x',red.H,'janela col/row',col,row)
    hb=STATS['bytes']; R=red.window(col,row,size,size).astype('f4'); Nn=nir.window(col,row,size,size).astype('f4')
    # L2A baseline >=04.00: DN offset -1000 (BOA_ADD_OFFSET), escala 1e-4
    off=item['properties'].get('earthsearch:boa_offset_applied')
    boa=0 if off else 1000  # earth-search ja aplica o offset quando boa_offset_applied=True
    Rr=(R-boa)/1e4; Nr=(Nn-boa)/1e4
    ndvi=(Nr-Rr)/np.clip(Nr+Rr,1e-6,None); ndvi[(R==0)|(Nn==0)]=np.nan
    dt=time.time()-t0
    print('ndvi media %.3f p10 %.3f p90 %.3f'%(np.nanmean(ndvi),np.nanpercentile(ndvi,10),np.nanpercentile(ndvi,90)))
    print('requests',STATS['requests'],'bytes_total',STATS['bytes'],'(cabecalhos %d, tiles %d)'%(hb,STATS['bytes']-hb),'tempo %.2fs'%dt)
    print('tamanho arquivo B04+B08 inteiros:',sum(int(urllib.request.urlopen(urllib.request.Request(u,method='HEAD'),timeout=30).headers['Content-Length']) for u in (red.url,nir.url)))
    print('boa_offset_applied',off,'processing baseline',item['properties'].get('s2:processing_baseline'))
    np.save(sys.argv[5] if len(sys.argv)>5 else 'ndvi.npy',ndvi.astype('f4'))
