#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export KUBECONFIG="${HW11_KUBECONFIG:-$PWD/.kubeconfig}"
RESULTS="${HW11_RESULTS:-$PWD/results}"
K=(kubectl --context kind-hw11)
N=("${K[@]}" -n hw11)

case "${1:-}" in
  up)
    mkdir -p "$RESULTS"
    {
      date -u
      df -h .
      docker version
      docker info --format '{{.NCPU}} CPUs {{.MemTotal}} bytes RAM'
      kind version
      helm version --short
    } > "$RESULTS/environment.txt"
    if ! kind get clusters | grep -qx hw11; then
      kind create cluster --name hw11 --image kindest/node:v1.32.2@sha256:f226345927d7e348497136874b6d207e0b32cc52154ad8323129352923a3142f --wait 150s
    fi
    kind export kubeconfig --name hw11
    docker build -t hw11-lab:1.0.0 .
    kind load docker-image --name hw11 hw11-lab:1.0.0
    "${K[@]}" create namespace hw11 --dry-run=client -o yaml | "${K[@]}" apply -f -
    "${N[@]}" create configmap prometheus-config --from-file=monitoring/prometheus.yml --from-file=monitoring/alerts.yml --dry-run=client -o yaml | "${N[@]}" apply -f -
    "${N[@]}" create configmap grafana-config --from-file=monitoring/datasource.yml --from-file=monitoring/provider.yml --dry-run=client -o yaml | "${N[@]}" apply -f -
    "${N[@]}" create configmap grafana-dashboard --from-file=monitoring/dashboard.json --dry-run=client -o yaml | "${N[@]}" apply -f -
    "${N[@]}" apply -f monitoring/stack.yaml
    "${K[@]}" apply -f https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.8.0/components.yaml
    if ! "${K[@]}" -n kube-system get deploy metrics-server -o jsonpath='{.spec.template.spec.containers[0].args[*]}' | grep -Fq -- --kubelet-insecure-tls; then
      "${K[@]}" -n kube-system patch deployment metrics-server --type=json -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
    fi
    "${K[@]}" -n kube-system patch deployment metrics-server --type=strategic -p='{"spec":{"template":{"spec":{"containers":[{"name":"metrics-server","image":"registry.k8s.io/metrics-server/metrics-server:v0.8.0@sha256:89258156d0e9af60403eafd44da9676fd66f600c7934d468ccc17e42b199aee2","resources":{"requests":{"cpu":"40m","memory":"64Mi"},"limits":{"cpu":"200m","memory":"160Mi"}}}]}}}}'
    helm upgrade --install lab chart --kube-context kind-hw11 -n hw11 --wait --timeout 150s
    for i in 0 1 2 3; do
      "${N[@]}" run "client-$i" --image=hw11-lab:1.0.0 --image-pull-policy=Never --restart=Never --dry-run=client -o json --overrides='{"spec":{"automountServiceAccountToken":false}}' --command -- python -c 'import time; time.sleep(86400)' |
        python3 -c 'import sys,json; p=json.load(sys.stdin); c=p["spec"]["containers"][0]; c["env"]=[{"name":"POD_IP","valueFrom":{"fieldRef":{"fieldPath":"status.podIP"}}}]; c["resources"]={"requests":{"cpu":"15m","memory":"32Mi"},"limits":{"cpu":"250m","memory":"96Mi"}}; print(json.dumps(p))' |
        "${N[@]}" apply -f -
    done
    for target in prometheus grafana kube-state; do "${N[@]}" rollout status deployment/"$target" --timeout=180s; done
    "${K[@]}" -n kube-system rollout status deployment/metrics-server --timeout=180s
    ./lab.sh inventory
    ;;
  inventory)
    mkdir -p "$RESULTS"
    {
      "${K[@]}" version
      "${K[@]}" get nodes -o wide
      "${N[@]}" get pods -o wide
      "${K[@]}" get pods -A -o custom-columns='POD:.metadata.name,IMAGE:.spec.containers[*].image,ID:.status.containerStatuses[*].imageID'
      node_image=$(docker inspect hw11-control-plane --format '{{.Image}}')
      docker image inspect hw11-lab:1.0.0 "$node_image" --format '{{json .RepoTags}} {{.Size}} bytes {{.Id}} {{json .RepoDigests}}'
      docker exec hw11-control-plane df -h /
      docker exec hw11-control-plane du -sh /var/lib/containerd /var/lib/kubelet /var/lib/etcd /var/log/pods
      if command -v colima >/dev/null; then colima version; fi
    } > "$RESULTS/footprint.txt"
    docker exec hw11-control-plane crictl images -o json > "$RESULTS/images.json"
    ;;
  down)
    kind delete cluster --name hw11
    docker image rm hw11-lab:1.0.0
    ;;
  *) echo 'Usage: ./lab.sh up|inventory|down' >&2; exit 2 ;;
esac
