import pandas as pd, sys, os; sys.stdout.reconfigure(encoding='utf-8')
A='C:/trabalho/random/etc2/akcit-camp/dados/'
# PSR 2016-2024 -> GO sem PII, em chunks
src=A+'amostras/psr_2016a2024_primeiros_512KB.csv'; out=A+'psr/psr_2016a2024_GO_sem_PII.csv'
drop=['NM_SEGURADO','NR_DOCUMENTO_SEGURADO','NR_PROPOSTA','ID_PROPOSTA','NR_APOLICE']
n=0; ngo=0; first=True; stats=[]
for ch in pd.read_csv(src,sep=';',encoding='latin-1',dtype=str,chunksize=200000):
    n+=len(ch); g=ch[ch.SG_UF_PROPRIEDADE=='GO'].drop(columns=drop); ngo+=len(g)
    g.to_csv(out,sep=';',index=False,encoding='utf-8',mode='w' if first else 'a',header=first); first=False
print('PSR 2016-24 linhas',n,'GO',ngo)
go=pd.read_csv(out,sep=';',dtype=str)
ind=go.columns[[i for i,c in enumerate(go.columns) if c.startswith('VALOR_INDENIZA')][0]]
go['ind']=pd.to_numeric(go[ind].str.replace(',','.'),errors='coerce')
print('GO por ano (apolices, indenizadas):'); print(go.groupby('ANO_APOLICE').agg(n=('ANO_APOLICE','size'),indeniz=('ind',lambda s:(s>0).sum())).to_string())
print('GO coord decimal',(go.NR_DECIMAL_LATITUDE.fillna('-')!='-').sum(),'GMS',(go.NR_GRAU_LAT.fillna('-')!='-').sum())
# ZARC 2026/27 -> GO
src2=A+'amostras/zarc_tabua_2026-2027_primeiro_1MB.csv'; out2=A+'zarc/zarc_tabua_2026-2027_GO.csv'; os.makedirs(A+'zarc',exist_ok=True)
n=0; ngo=0; first=True; cult=None
for ch in pd.read_csv(src2,sep=';',encoding='utf-8-sig',dtype=str,chunksize=200000):
    n+=len(ch); g=ch[ch.UF=='GO']; ngo+=len(g)
    g.to_csv(out2,sep=';',index=False,encoding='utf-8',mode='w' if first else 'a',header=first); first=False
print('ZARC 26/27 linhas',n,'GO',ngo)
z=pd.read_csv(out2,sep=';',dtype=str); print(z.Nome_cultura.value_counts().head(12).to_dict())
