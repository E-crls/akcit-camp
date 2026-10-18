BEGIN{FS=";"}
FNR==NR{ if(FNR>1){c=$1; gsub(/"/,"",c); f=$4; a=$5; m=$6; p=$7; gsub(/"/,"",f); gsub(/"/,"",a); gsub(/"/,"",m); gsub(/"/,"",p); cat[c]=f"|"a"|"m; prod[c]=p} next }
FNR==1{next}
{
  c=$13; k=(c in cat)?cat[c]:"?|?|?"; val=$28+0;
  b = (val<20000)?"a<20k":(val<100000)?"b20-100k":(val<500000)?"c100-500k":"d>=500k";
  cad=$43; sys="outros";
  if(cad=="02038232") sys="sicoob"; else if(cad=="01181521") sys="sicredi"; else if(cad=="01401771") sys="3o_sist";
  nb[k"#"b]++; vb[k"#"b]+=val;
  nc[c]++; vc[c]+=val;
  nsb[k"#"sys"#"b]++;
  if($10=="GO") { ngo[k]++; vgo[k]+=val }
}
END{
  for(x in nb) printf "BKT\t%s\t%d\t%.0f\n", x, nb[x], vb[x];
  for(x in nc) printf "COD\t%s\t%s\t%s\t%d\t%.0f\n", x, cat[x], prod[x], nc[x], vc[x];
  for(x in nsb) printf "SB\t%s\t%d\n", x, nsb[x];
  for(x in ngo) printf "GO\t%s\t%d\t%.0f\n", x, ngo[x], vgo[x];
}
