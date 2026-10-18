# Agrega microdados SICOR_OPERACAO_BASICA_ESTADO por categoria de empreendimento
# FNR==NR: tabela de empreendimentos (utf8, ; , aspas)
BEGIN{FS=";"}
FNR==NR{ if(FNR>1){c=$1; gsub(/"/,"",c); f=$4; a=$5; m=$6; gsub(/"/,"",f); gsub(/"/,"",a); gsub(/"/,"",m); cat[c]=f"|"a"|"m; prod[c]=$7} next }
FNR==1{next}
{
  c=$13; k=(c in cat)?cat[c]:"?|?|?";
  cad=$43; sys="outros";
  if(cad=="02038232") sys="sicoob"; else if(cad=="01181521") sys="sicredi"; else if(cad=="00000000") sys="bb"; else if(cad=="01401771") sys="cresol?";
  n[k]++; v[k]+=$28; q[k]+=$26;
  ns[k"#"sys]++; vs[k"#"sys]+=$28;
  N++; V+=$28;
  if($9=="1" || $9=="0") {} 
  if($1!=last){ops++; last=$1}
  if($27!="") {}
  if($10!="") uf[$10]++;
}
END{
  printf "TOTAL_LINHAS\t%d\tVALOR\t%.0f\tOPS_APROX\t%d\n", N, V, ops;
  for(k in n) printf "CAT\t%s\t%d\t%.0f\t%.0f\n", k, n[k], v[k], q[k];
  for(k in ns) printf "SYS\t%s\t%d\t%.0f\n", k, ns[k], vs[k];
}
