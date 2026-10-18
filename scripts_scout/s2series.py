import json, urllib.request, time, sys
import numpy as np
sys.path.insert(0,'.')
import cogwindow as cw
lon,lat,size=-50.95,-17.85,128
body={"collections":["sentinel-2-l2a"],"intersects":{"type":"Point","coordinates":[lon,lat]},
 "datetime":"2025-10-01T00:00:00Z/2026-06-30T23:59:59Z","query":{"eo:cloud_cover":{"lt":20},"grid:code":{"eq":"MGRS-22KEF"}},"limit":100,
 "sortby":[{"field":"properties.datetime","direction":"asc"}]}
req=urllib.request.Request('https://earth-search.aws.element84.com/v1/search',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
items=json.load(urllib.request.urlopen(req,timeout=60))['features']; print('cenas safra 25/26 tile KEF nuvem<20%:',len(items))
t0=time.time(); rows=[]
for it in items[:12]:
    red=cw.COG(it['assets']['red']['href']); nir=cw.COG(it['assets']['nir']['href']); scl=cw.COG(it['assets']['scl']['href'])
    x,y=cw.utm(lon,lat,red.epsg-32700); X0,sx,Y0,sy=red.gt; col=int((x-X0)/sx)-size//2; row=int((y-Y0)/sy)-size//2
    R=red.window(col,row,size,size).astype('f4')/1e4; N=nir.window(col,row,size,size).astype('f4')/1e4
    X0s,sxs,Y0s,sys_=scl.gt; cs=int((x-X0s)/sxs)-size//4; rs=int((y-Y0s)/sys_)-size//4
    S=scl.window(cs,rs,size//2,size//2).repeat(2,0).repeat(2,1)
    ok=np.isin(S,[4,5])  # vegetacao / solo exposto
    nd=(N-R)/np.clip(N+R,1e-6,None)
    rows.append((it['properties']['datetime'][:10],round(float(np.nanmean(np.where(ok,nd,np.nan))),3),round(float(ok.mean()),2)))
    print(rows[-1])
dt=time.time()-t0
print('cenas',len(rows),'requests',cw.STATS['requests'],'bytes',cw.STATS['bytes'],'tempo %.1fs'%dt,'por cena %.0f KB %.1fs'%(cw.STATS['bytes']/len(rows)/1024,dt/len(rows)))
json.dump(rows,open(sys.argv[1],'w'))
