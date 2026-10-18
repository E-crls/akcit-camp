BEGIN{FS=";"
 F["Investimento|Pecuário(a)|AQUISIÇÃO DE ANIMAIS"]=1
 F["Investimento|Pecuário(a)|SERVIÇOS PROFISSIONAIS/TÉCNICOS"]=1
 F["Custeio|Pecuário(a)|AQUISIÇÃO E MANUTENÇÃO DE ANIMAIS"]=1
 F["Custeio|Pecuário(a)|BOVINOCULTURA"]=1
 F["Investimento|Agrícola|MÁQUINAS, EQUIPAMENTOS, MATERIAIS E UTENSÍLIOS"]=1
 F["Investimento|Pecuário(a)|MÁQUINAS, EQUIPAMENTOS, MATERIAIS E UTENSÍLIOS"]=1
}
FNR==NR{ if(FNR>1){c=$1; gsub(/"/,"",c); f=$4; a=$5; m=$6; gsub(/"/,"",f); gsub(/"/,"",a); gsub(/"/,"",m); k=f"|"a"|"m; if(k in F) fis[c]=1} next }
FNR==1{next}
{
  if1=$3; cad=$43; val=$28+0
  sys[if1]=cad
  n[if1]++; v[if1]+=val
  if($1!=last[if1]){ops[if1]++; last[if1]=$1}
  if(($13 in fis) && val>=20000) nf[if1]++
  if($10=="GO"){ngo[if1]++; if(($13 in fis) && val>=20000) nfgo[if1]++}
}
END{ for(i in n) printf "%s\t%s\t%d\t%d\t%.0f\t%d\t%d\t%d\n", i, sys[i], n[i], ops[i], v[i], nf[i], ngo[i], nfgo[i] }
