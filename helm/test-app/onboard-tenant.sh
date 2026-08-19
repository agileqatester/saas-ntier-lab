#!/usr/bin/env bash
# Kubernetes onboard for tenant a or b. IAM/secrets stay in OpenTofu (for_each).
# Run from env/dev/workload after: export IRSA_A IRSA_B IRSA_MIGRATOR SECRET_A SECRET_B RDS_HOST MASTER_SECRET
set -euo pipefail

TENANT="${1:?usage: onboard-tenant.sh <a|b>}"
case "$TENANT" in
  a|b) ;;
  *)
    echo "only tenants a and b have IRSA/secrets in OpenTofu" >&2
    exit 1
    ;;
esac

ROOT="$(cd "$(dirname "$0")" && pwd)"
NODE_IP="${NODE_IP:-$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')}"
if [[ -z "${NODE_IP}" ]]; then
  echo "no Ready node. Refresh kubeconfig, wait, retry:" >&2
  echo "  aws eks update-kubeconfig --name ntier-dev-eks-cluster --region ${AWS_REGION:-us-east-1}" >&2
  echo "  kubectl wait --for=condition=Ready nodes --all --timeout=600s" >&2
  exit 1
fi
NS="tenant-${TENANT}"

if [[ "$TENANT" == "a" ]]; then
  IRSA="${IRSA_A:?set IRSA_A}"
  SECRET="${SECRET_A:?set SECRET_A}"
else
  IRSA="${IRSA_B:?set IRSA_B}"
  SECRET="${SECRET_B:?set SECRET_B}"
fi

HOST="${RDS_HOST:?set RDS_HOST}"
REGION="${AWS_REGION:-us-east-1}"
ANN="{\"eks.amazonaws.com/role-arn\":\"${IRSA}\"}"

kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
kubectl label ns "$NS" "tenant=${TENANT}" --overwrite

HELM_ARGS=(
  upgrade --install test-app "$ROOT"
  -n "$NS"
  -f "$ROOT/values-tenant-${TENANT}.yaml"
  --set-json "serviceAccount.annotations=${ANN}"
  --set database.enabled=true
  --set "database.host=${HOST}"
  --set "database.secretName=${SECRET}"
  --set "region=${REGION}"
  --set "networkPolicy.ingressCidrs={${NODE_IP}/32}"
)

if [[ "$TENANT" == "a" ]]; then
  kubectl -n "$NS" delete job test-app-migrate --ignore-not-found
  MIG_ANN="{\"eks.amazonaws.com/role-arn\":\"${IRSA_MIGRATOR:?set IRSA_MIGRATOR}\"}"
  HELM_ARGS+=(
    --set-json "database.migratorServiceAccount.annotations=${MIG_ANN}"
    --set "database.masterSecret=${MASTER_SECRET:?set MASTER_SECRET}"
    --set-json "database.tenantSecrets={\"a\":\"${SECRET_A}\",\"b\":\"${SECRET_B:?set SECRET_B}\"}"
  )
fi

helm "${HELM_ARGS[@]}"

if [[ "$TENANT" == "a" ]]; then
  kubectl -n "$NS" wait --for=condition=complete "job/test-app-migrate" --timeout=300s
fi

echo "onboarded ${NS} (node ${NODE_IP})"
