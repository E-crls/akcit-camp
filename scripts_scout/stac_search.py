import json, urllib.request, time
url='https://earth-search.aws.element84.com/v1/search'
body={"collections":["sentinel-2-l2a"],"intersects":{"type":"Point","coordinates":[-50.95,-17.85]},
      "datetime":"2025-01-01T00:00:00Z/2026-10-08T23:59:59Z","query":{"eo:cloud_cover":{"lt":20}},"limit":200,
      "sortby":[{"field":"properties.datetime","direction":"desc"}]}
t=time.time(); items=[]; nxt=(url,body)
while nxt:
    u,b=nxt
    req=urllib.request.Request(u,data=json.dumps(b).encode(),headers={'Content-Type':'application/json'})
    d=json.load(urllib.request.urlopen(req,timeout=60)); items+=d['features']
    nxt=None
    for l in d.get('links',[]):
        if l.get('rel')=='next': nxt=(l['href'],l.get('body',b))
print('itens',len(items),'tempo %.1fs'%(time.time()-t))
for it in items[:8]:
    p=it['properties']; print(it['id'],p['datetime'][:10],'nuvem',round(p['eo:cloud_cover'],1),p.get('s2:mgrs_tile') or p.get('grid:code'))
print('mais antigo',items[-1]['id'],items[-1]['properties']['datetime'][:10])
it=items[0]
for k in ['red','nir','scl','visual']:
    a=it['assets'].get(k); print(k,a['href'] if a else None, a.get('type') if a else None)
print(list(it['assets'].keys()))
json.dump(items[:3],open('stac_items_sample.json','w'))
import collections
print(collections.Counter(i['properties']['datetime'][:7] for i in items))
