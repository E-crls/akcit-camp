import zipfile, re, json, urllib.request, urllib.parse, time, sys
import pandas as pd, geopandas as gpd
from shapely.geometry import shape
sys.stdout.reconfigure(encoding='utf-8')
z=zipfile.ZipFile(sys.argv[1]); df=pd.read_csv(z.open(z.namelist()[0]),sep=';',decimal=',',encoding='utf-8-sig',low_memory=False)
go=df[(df.uf=='GO')&(df.municipio.isin(['Rio Verde','Jataí','Mineiros','Montividiu','Caiapônia']))].sort_values('soma_desmat',ascending=False)
sel=pd.concat([go.head(3),go[go.soma_desmat.between(5,15)].head(3)])
def wfs(base,params):
    import subprocess
    q=urllib.parse.urlencode(params); out=subprocess.run(['curl','-s','-m','120','--data',q,base],capture_output=True,check=True).stdout; return json.loads(out)
feats=[]; t0=time.time(); rows=[]
for _,r in sel.iterrows():
    car=wfs('https://geoserver.car.gov.br/geoserver/sicar/ows',{'service':'WFS','version':'2.0.0','request':'GetFeature','typeNames':'sicar:sicar_imoveis_go','outputFormat':'application/json','CQL_FILTER':f"cod_imovel='{r.cod_imovel}'"})['features']
    uu=re.findall(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',str(r.uuid_prodes))
    pr=wfs('https://terrabrasilis.dpi.inpe.br/geoserver/ows',{'service':'WFS','version':'2.0.0','request':'GetFeature','typeNames':'prodes-cerrado-nb:yearly_deforestation','outputFormat':'application/json','srsName':'EPSG:4674','CQL_FILTER':"uuid IN ("+",".join(f"'{u}'" for u in uu)+")"})['features'] if uu else []
    if not car: rows.append((r.cod_imovel,'CAR nao encontrado')); continue
    cg=gpd.GeoSeries([shape(car[0]['geometry'])],crs=4674).to_crs('ESRI:102033')
    pg=gpd.GeoSeries([shape(f['geometry']) for f in pr],crs=4674).to_crs('ESRI:102033') if pr else gpd.GeoSeries([],crs='ESRI:102033')
    inter=pg.intersection(cg.iloc[0]).area.sum()/1e4 if len(pg) else 0
    rows.append((r.cod_imovel[:20]+'...',r.municipio,round(r.m_fiscal,1),round(r.soma_desmat,1),len(uu),len(pr),round(inter,1)))
    for f in car: f['properties']={'camada':'CAR','cod_imovel':r.cod_imovel,'m_fiscal':r.m_fiscal,'status':f['properties']['status_imovel']}; feats.append(f)
    for f in pr: f['properties']={'camada':'PRODES','cod_imovel':r.cod_imovel,'uuid':f['properties']['uuid'],'year':f['properties']['year'],'image_date':f['properties']['image_date'],'area_km':f['properties']['area_km']}; feats.append(f)
print('cod | municipio | MF | soma_desmat MMA (ha) | n uuids | n poligonos PRODES achados | intersecao recalculada (ha)')
for x in rows: print(x)
print('tempo %.1fs'%(time.time()-t0))
json.dump({'type':'FeatureCollection','features':feats},open(sys.argv[2],'w',encoding='utf-8'))
