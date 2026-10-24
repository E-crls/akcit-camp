#!/usr/bin/env bash
# Publica uma versão da demo: build da imagem no Cloud Build (na região da demo, com a conta de serviço de
# build), troca da imagem pelo Terraform e conferência completa (verificar.sh). Pré-requisito: a base já
# aplicada (terraform apply sem imagem) e o gcloud logado.
# Uso: bash infra/nuvem/publicar.sh            (de qualquer pasta)
set -euo pipefail
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(cd "$AQUI/../.." && pwd)"   # laudo-vivo/: contexto do build
cd "$AQUI"
PROJ=$(sed -n 's/^projeto *= *"\(.*\)"/\1/p' terraform.tfvars)
REG=${REGIAO:-southamerica-east1}
export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)

REPO=$(terraform output -raw repositorio)
BUCKET=$(terraform output -raw bucket_fontes)
SA=$(terraform output -raw conta_build)
TAG="$(git -C "$RAIZ" rev-parse --short HEAD)-$(date -u +%Y%m%d%H%M%S)"

echo "== build $REPO/site:$TAG"
gcloud builds submit "$RAIZ" --project "$PROJ" --region "$REG" --config "$AQUI/cloudbuild.yaml" \
  --substitutions "_REPOSITORIO=$REPO,_TAG=$TAG" --service-account "$SA" \
  --gcs-source-staging-dir "gs://$BUCKET/fontes" --ignore-file .gcloudignore

# a imagem fica num tfvars próprio (fora do git): o plan seguinte não tenta tirar o serviço do ar
printf 'imagem = "%s/site:%s"\n' "$REPO" "$TAG" > imagem.auto.tfvars
echo "== terraform apply (imagem $TAG)"
terraform apply -input=false -auto-approve
echo "== conferência"
bash verificar.sh
