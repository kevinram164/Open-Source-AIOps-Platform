# Bootstrap scripts

| Script | Mô tả |
|--------|-------|
| `bootstrap.sh` | Apply bootstrap Kustomize manifests |

## Usage

```bash
oc login <api-server>
./scripts/bootstrap.sh
```

## Rollback

```bash
oc delete -k bootstrap/ --ignore-not-found
```

> Lưu ý: `oc delete -k` sẽ xóa namespaces và dữ liệu PVC. Chỉ dùng trên lab, không xóa banking/movie.
