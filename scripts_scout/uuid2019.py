import sys, zipfile, re, json, random, urllib.request, urllib.parse
import pandas as pd
z=zipfile.ZipFile(sys.argv[1]); df=pd.read_csv(z.open(z.namelist()[0]),sep=';',decimal=',',encoding='utf-8-sig',low_memory=False,usecols=['uf','uuid_prodes','sobrep_prodes_2019'])
go=df[(df.uf=='GO')&(df.sobrep_prodes_2019>0)]
print('GO imoveis com sobrep 2019:',len(go))
uu=[]
for s in go.uuid_prodes.dropna():
    for part in s.split('|'):
        part=part.strip()
        if part.startswith('2019'):
            uu+=re.findall(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',part)
print('uuids 2019 GO:',len(uu))
random.seed(1); smp=random.sample(uu,min(150,len(uu)))
cql="uuid IN ("+",".join("'%s'"%u for u in smp)+")"
q=urllib.parse.urlencode({'service':'WFS','version':'2.0.0','request':'GetFeature','typeNames':'prodes-cerrado-nb:yearly_deforestation','outputFormat':'application/json','propertyName':'uuid,year,image_date,area_km','CQL_FILTER':cql})
d=json.load(urllib.request.urlopen('https://terrabrasilis.dpi.inpe.br/geoserver/ows',data=q.encode(),timeout=120))
fs=d['features']; print('found',len(fs))
pre=sum(1 for f in fs if f['properties']['image_date']<='2019-07-31'); print('image_date<=2019-07-31:',pre,'> :',len(fs)-pre)
print(sorted(set(f['properties']['image_date'] for f in fs))[:10], '...', sorted(set(f['properties']['image_date'] for f in fs))[-5:])
