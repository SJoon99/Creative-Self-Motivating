# rag-strawberry

딸기 재배 RAG(`jongminpark0101/RAG_strawberry`)를 HTTP API로 띄우고,
Gemma vLLM(`gemma4-vllm.sjpark.svc.cluster.local`)을 OpenAI-compatible API로 호출한다.

## API

- `GET /healthz`
- `POST /ask`
- `POST /recommend`

기본적으로 `gemma4-vllm-api-token` Secret의 `API_TOKEN`을 RAG API 인증과 vLLM upstream 인증에 같이 쓴다.

```bash
TOKEN=$(kubectl -n sjpark get secret gemma4-vllm-api-token -o jsonpath='{.data.API_TOKEN}' | base64 -d)

kubectl -n sjpark port-forward svc/rag-strawberry 8080:8080

curl http://127.0.0.1:8080/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"봄철 딸기 온실의 적정 낮 온도와 밤 온도는?","top_k":5}'

curl http://127.0.0.1:8080/recommend \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"planting_date":"2025-09-15","date":"2025-11-15"}'
```

Cloudflare에 공개하려면 tunnel published route의 Service를
`http://rag-strawberry.sjpark.svc.cluster.local:8080`으로 추가하면 된다.


### Vision analyze

`POST /vision/analyze` accepts the OmniOps Growth Camera capture payload (`imageMimeType`, `imageBase64`, `sensorContext`, `cropContext`, `kpiContext`, and `fallbackAssessment`) and returns an `assessment` object with `growthProgressPercent`, `healthScore`, `fruitMaturityPercent`, `harvestReadinessPercent`, `diseaseRisk`, `phenotypeStage`, `traits`, and `analysisMode`.
