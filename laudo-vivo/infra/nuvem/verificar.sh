#!/usr/bin/env bash
# Conferência da demo pública depois de cada `terraform apply` (só lê; não cria nem muda nada):
#   1. o Terraform não tem diferença pendente (nada criado fora dele, nada a meio);
#   2. inventário do projeto: cada recurso existe uma vez só (sem duplicata) e com a etiqueta de custo;
#   3. o Cloud Run está com a configuração de custo (cobrança por requisição, teto de instâncias);
#   4. o site responde (/api/saude e a página) e o caso de demonstração abre;
#   5. custo estimado das últimas 24 h (Cloud Run + Gemini + registro).
# Uso: bash verificar.sh            (sai com 1 se algum item falhar)
set -uo pipefail
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
cd "$(dirname "${BASH_SOURCE[0]}")"
PROJ=$(sed -n 's/^projeto *= *"\(.*\)"/\1/p' terraform.tfvars)
NOME=${NOME:-laudo-vivo-demo}
REG=${REGIAO:-southamerica-east1}
FALHAS=0
TMPD=$(mktemp -d); trap 'rm -rf "$TMPD"' EXIT
ok() { printf '  ok    %s\n' "$*"; }
ruim() { printf '  FALHA %s\n' "$*"; FALHAS=$((FALHAS + 1)); }
export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)
TOKEN=$GOOGLE_OAUTH_ACCESS_TOKEN
g() { gcloud --project "$PROJ" "$@" 2>/dev/null; }

echo "1. Terraform sem diferença"
terraform plan -input=false -no-color -detailed-exitcode >$TMPD/plan.txt 2>&1
case $? in
  0) ok "plan: nenhuma mudança pendente" ;;
  2) ruim "plan com mudança pendente:"; grep -E "will be|must be" $TMPD/plan.txt | sed 's/^/        /' ;;
  *) ruim "plan falhou:"; tail -5 $TMPD/plan.txt | sed 's/^/        /' ;;
esac

echo "2. Inventário (uma vez cada, com etiqueta centro-custo=$NOME)"
conta() {  # rótulo, esperado, comando que lista um por linha
  local rot=$1 esperado=$2; shift 2
  local n; n=$("$@" | grep -c . || true)
  if [ "$n" = "$esperado" ]; then ok "$rot: $n"; else ruim "$rot: $n (esperado $esperado)"; fi
}
SERVICO=$(g run services describe "$NOME" --region "$REG" --format=json)
TEM_SERVICO=$([ -n "$SERVICO" ] && echo 1 || echo 0)
conta "serviços do Cloud Run" "$TEM_SERVICO" g run services list --format="value(metadata.name)"
conta "repositórios do Artifact Registry" 1 g artifacts repositories list --location "$REG" --format="value(name)"
conta "buckets" 1 g storage buckets list --format="value(name)"
conta "contas de serviço da demo" 2 bash -c "gcloud --project $PROJ iam service-accounts list --format='value(email)' 2>/dev/null | grep '^$NOME-'"
conta "métricas de log" 4 bash -c "gcloud --project $PROJ logging metrics list --format='value(name)' 2>/dev/null | grep '^laudo_'"
conta "painéis" 1 bash -c "curl -s -H 'Authorization: Bearer $TOKEN' https://monitoring.googleapis.com/v1/projects/$PROJ/dashboards | python -c \"import json,sys; [print(d['displayName']) for d in json.load(sys.stdin).get('dashboards',[])]\""
conta "verificações de disponibilidade" "$TEM_SERVICO" bash -c "curl -s -H 'Authorization: Bearer $TOKEN' https://monitoring.googleapis.com/v3/projects/$PROJ/uptimeCheckConfigs | python -c \"import json,sys; [print(d['displayName']) for d in json.load(sys.stdin).get('uptimeCheckConfigs',[])]\""
NUM=$(g projects describe "$PROJ" --format="value(projectNumber)")
CONTA=$(sed -n 's/^conta_faturamento *= *"\(.*\)"/\1/p' terraform.tfvars)
conta "orçamentos deste projeto" 1 bash -c "gcloud billing budgets list --billing-account=$CONTA --format=json 2>/dev/null | python -c \"import json,sys; [print(b['displayName']) for b in json.load(sys.stdin) if 'projects/$NUM' in b.get('budgetFilter',{}).get('projects',[])]\""
rotulo() {  # rótulo, json com .labels (ou userLabels)
  if echo "$2" | python -c "import json,sys; d=json.load(sys.stdin); l=d.get('labels') or d.get('userLabels') or d.get('metadata',{}).get('labels') or {}; sys.exit(0 if l.get('centro-custo')=='$NOME' else 1)"; then
    ok "etiqueta de custo: $1"; else ruim "sem etiqueta de custo: $1"; fi
}
rotulo "repositório" "$(g artifacts repositories describe "$NOME" --location "$REG" --format=json)"
rotulo "painel" "$(curl -s -H "Authorization: Bearer $TOKEN" "https://monitoring.googleapis.com/v1/projects/$PROJ/dashboards" | python -c "import json,sys; d=[x for x in json.load(sys.stdin).get('dashboards',[]) if x.get('displayName','').startswith('Laudo Vivo')]; print(json.dumps(d[0] if d else {}))")"
rotulo "bucket" "$(g storage buckets describe "gs://$PROJ-$NOME-fontes" --format=json | python -c "import json,sys; d=json.load(sys.stdin); print(json.dumps({'labels': d.get('labels') or d.get('default_labels') or {}}))")"

if [ "$TEM_SERVICO" = 1 ]; then
  echo "3. Cloud Run com a configuração de custo"
  echo "$SERVICO" > "$TMPD/servico.json"
  python - "$NOME" "$TMPD/servico.json" <<'EOF' || FALHAS=$((FALHAS + 1))
import json, sys
nome = sys.argv[1]; s = json.load(open(sys.argv[2], encoding="utf-8"))
t = s["spec"]["template"]; a = t["metadata"].get("annotations", {}); c = t["spec"]["containers"][0]
lim = c.get("resources", {}).get("limits", {})
checks = [
    ("etiqueta de custo no serviço", s["metadata"].get("labels", {}).get("centro-custo") == nome),
    ("etiqueta de custo na revisão", t["metadata"].get("labels", {}).get("centro-custo") == nome),
    ("cobrança por requisição (cpu-throttling)", a.get("run.googleapis.com/cpu-throttling", "true") == "true"),
    (f"teto de instâncias = {a.get('autoscaling.knative.dev/maxScale')}", a.get("autoscaling.knative.dev/maxScale") == "1"),
    (f"mínimo de instâncias = {a.get('autoscaling.knative.dev/minScale', '0')}", a.get("autoscaling.knative.dev/minScale", "0") in ("0", "1")),
    (f"CPU {lim.get('cpu')} / memória {lim.get('memory')} / concorrência {t['spec'].get('containerConcurrency')}", True),
    ("sem GPU", "nvidia.com/gpu" not in lim),
    ("tráfego 100% na última revisão", all(x.get("latestRevision") for x in s["status"].get("traffic", []))),
    ("revisão pronta", any(x.get("type") == "Ready" and x.get("status") == "True" for x in s["status"].get("conditions", []))),
]
ruins = 0
for rot, bom in checks:
    print(("  ok    " if bom else "  FALHA ") + rot); ruins += not bom
sys.exit(1 if ruins else 0)
EOF
  URL=$(echo "$SERVICO" | python -c "import json,sys; print(json.load(sys.stdin)['status']['url'])")
  echo "4. Site em $URL"
  cod=$(curl -s -o /dev/null -w '%{http_code}' -m 60 "$URL/api/saude"); [ "$cod" = 200 ] && ok "/api/saude 200" || ruim "/api/saude $cod"
  cod=$(curl -s -o $TMPD/index.html -w '%{http_code}' -m 30 "$URL/"); [ "$cod" = 200 ] && grep -qi "laudo" $TMPD/index.html && ok "página inicial 200" || ruim "página inicial $cod"
  curl -s -m 30 "$URL/api/saude" | python -c "import json,sys; d=json.load(sys.stdin); print('        saude:', json.dumps({k: d.get(k) for k in ('ok','llm','asr','demo_publica','cfg') if k in d}, ensure_ascii=False)[:400])" 2>/dev/null
  cod=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -H "Origin: https://exemplo.invalido" -X OPTIONS "$URL/api/saude")
  echo "        CORS de origem estranha: HTTP $cod (esperado 400/403/405)"
fi

echo "5. Custo estimado (últimas 24 h)"
python - "$PROJ" "$NOME" "$TOKEN" <<'EOF'
import json, sys, urllib.parse, urllib.request
proj, nome, tok = sys.argv[1:4]
def q(expr):
    url = f"https://monitoring.googleapis.com/v1/projects/{proj}/location/global/prometheus/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"}), timeout=30) as r:
            res = json.load(r)["data"]["result"]
        return sum(float(x["value"][1]) for x in res)
    except Exception as e:  # noqa: BLE001
        return float("nan")
f = f'monitored_resource="cloud_run_revision",service_name="{nome}"'
seg = q(f'sum(increase(run_googleapis_com:container_billable_instance_time{{{f}}}[1d]))')
req = q(f'sum(increase(run_googleapis_com:request_count{{{f}}}[1d]))')
llm = q(f'sum(increase(logging_googleapis_com:user_laudo_llm_custo_usd_sum{{{f}}}[1d]))')
# tokens medidos pelo próprio Vertex AI (fonte oficial; o app estima pelo uso que a resposta informa)
v_ent = q('sum(increase(aiplatform_googleapis_com:publisher_online_serving_token_count{type="input"}[1d]))')
v_sai = q('sum(increase(aiplatform_googleapis_com:publisher_online_serving_token_count{type="output"}[1d]))')
llm_v = v_ent * 0.25e-6 + v_sai * 1.50e-6 if v_ent == v_ent and v_sai == v_sai else float("nan")
tok_ = q(f'sum(increase(logging_googleapis_com:user_laudo_llm_tokens_sum{{{f}}}[1d]))')
run = seg * (4 * 0.0000336 + 8 * 0.0000035) if seg == seg else float("nan")
cambio = 5.6
print(f"  Cloud Run: {seg:.0f} s faturáveis, {req:.0f} requisições -> US$ {run:.4f}")
print(f"  Gemini:    {tok_:.0f} tokens pelo app -> US$ {llm:.4f}; medido pelo Vertex: {v_ent:.0f} entrada + {v_sai:.0f} saída -> US$ {llm_v:.4f}")
tot = (run if run == run else 0) + max(llm if llm == llm else 0, llm_v if llm_v == llm_v else 0)
print(f"  Total estimado 24 h: US$ {tot:.4f} (~R$ {tot * cambio:.2f}; câmbio de referência {cambio})")
print("  (nan = métrica ainda sem dado; o valor oficial está no relatório de faturamento, com atraso de horas)")
EOF
SZ=$(curl -s -H "Authorization: Bearer $TOKEN" "https://artifactregistry.googleapis.com/v1/projects/$PROJ/locations/$REG/repositories/$NOME" | python -c "import json,sys; print(f\"{int(json.load(sys.stdin).get('sizeBytes') or 0)/1e9:.2f}\")")
N_IMG=$(g artifacts docker images list "$REG-docker.pkg.dev/$PROJ/$NOME" --format="value(version)" | sort -u | grep -c . || true)
echo "  Registro: $N_IMG versão(ões), ${SZ:-0} GB (0,5 GB grátis; US$ 0,10/GB-mês acima)"

echo
if [ "$FALHAS" = 0 ]; then echo "TUDO OK"; else echo "$FALHAS FALHA(S)"; fi
exit $((FALHAS > 0))
