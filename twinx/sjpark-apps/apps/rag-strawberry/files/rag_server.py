"""Self-contained Strawberry RAG HTTP server for the ArgoCD Helm chart.

The chart clones the RAG_strawberry repository for documents/chroma_db/setpoints_table,
then runs this server with Gemma through the vLLM OpenAI-compatible endpoint.
"""
from __future__ import annotations

import base64
import binascii
import copy
import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any

import chromadb
from fastapi import FastAPI, Header, HTTPException, Request
from openai import OpenAI
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer


REPO_DIR = Path(os.getenv("RAG_REPO_DIR", "/data/repo"))
DB_DIR = Path(os.getenv("DB_DIR", str(REPO_DIR / "chroma_db")))
TABLE_PATH = Path(os.getenv("TABLE_PATH", str(REPO_DIR / "setpoints_table.json")))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "strawberry_manual")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
LLM_MODEL = os.getenv("LLM_MODEL", "gemma4")
OPENAI_BASE_URL = os.getenv(
    "OPENAI_BASE_URL",
    "http://gemma4-vllm.sjpark.svc.cluster.local:8000/v1",
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", os.getenv("VLLM_API_KEY", "EMPTY"))
VERIFY_LLM_ON_STARTUP = os.getenv("VERIFY_LLM_ON_STARTUP", "true").lower() in {"1", "true", "yes", "on"}
API_TOKEN = os.getenv("RAG_API_TOKEN", "").strip()
RAG_ALLOW_NO_AUTH = os.getenv("RAG_ALLOW_NO_AUTH", "false").lower() in {"1", "true", "yes", "on"}
DEFAULT_TOP_K = int(os.getenv("TOP_K", "5"))
logging.basicConfig(level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))
logger = logging.getLogger("rag-strawberry")


SYSTEM_PROMPT = """당신은 딸기 시설원예 전문가입니다.

규칙:
1. 반드시 한국어로 답변하세요.
2. 주어진 [참고 자료]에 근거해서만 답변하세요.
3. 참고 자료에 없는 내용은 추측하지 말고 "참고 자료에 해당 내용이 없습니다"라고 답하세요.
4. 답변 마지막에 사용한 자료의 출처(파일명과 페이지)를 [출처: ...] 형태로 적어주세요.
5. 답변은 명료하고 간결하게, 농장에서 바로 활용 가능한 형태로 작성하세요."""

EXPLAIN_SYSTEM = """당신은 딸기 시설원예 환경제어 전문가입니다.
디지털 트윈 제어기에 들어갈 '확정된 셋포인트'에 대해, 농업인이 이해할 설명만 작성합니다.

매우 중요한 규칙:
1. 셋포인트 수치는 이미 확정되어 있습니다. 절대 새로운 숫자를 만들거나 바꾸지 마세요.
2. 당신의 역할은 '이 값들이 이 생육단계/계절에 왜 적절한지'를 한국어 2~4문장으로 설명하는 것뿐입니다.
3. 설명은 주어진 [확정 셋포인트]와 [참고 자료] 범위 안에서만 작성하세요. 자료에 없는 주장은 하지 마세요.
4. 출력은 설명 문장만. 숫자 표/JSON/머리말 없이 자연스러운 문단으로 작성하세요."""

BLUEPRINT_SYSTEM = """당신은 딸기 시설원예 디지털 트윈 Blueprint 생성기입니다.
현재 Baseline Twin 상태와 문헌 RAG 근거를 보고, 트윈 시뮬레이션에 넣을 후보 제어 Blueprint만 생성합니다.

매우 중요한 규칙:
1. Baseline은 현재 상태 표현이므로 변경 대상이 아닙니다.
2. 후보는 정확히 Blueprint A/B/C 순서의 서로 다른 전략이어야 합니다.
3. 수치는 actuator bounds 안에서만 제안하세요.
4. 출력은 JSON object만 작성하세요. Markdown, 설명 문장, 코드펜스는 금지합니다.
5. JSON schema:
{"candidates":[{"id":"blueprint-a","label":"Blueprint A","intent":"...","actuatorTargets":{"ledIntensityPercent":70,"photoperiodHours":15,"waterValveOpen":true,"irrigationPulsesPerDay":3,"fanDutyPercent":55,"co2Ppm":700},"rationale":"...","tradeoff":"...","riskNotes":"..."}]}"""

VISION_SYSTEM = """You are a strawberry phenotyping vision model for a SmartFarm digital twin.
Analyze the provided greenhouse crop image and return only one JSON object.
No Markdown, no code fences, no Korean text.
Schema:
{"provider":"twinx-gemma-vision","growthProgressPercent":0,"fruitMaturityPercent":0,"fruitSetPercent":0,"canopyVigorPercent":0,"harvestReadinessPercent":0,"healthScore":0,"diseaseRisk":"low|controlled|high","phenotypeStage":"...","confidence":"gemma-vision|gemma-text-fallback","traits":["..."],"recommendation":"...","summary":"..."}
Use percentages on a 0-100 full crop-cycle scale. If fruit is not visible, infer early progress from leaves/flowers/canopy and say so in traits."""

SUBQUERY_TEMPLATES = [
    "{stage} 딸기 주간 야간 온도 관리",
    "딸기 온실 습도 CO2 탄산가스 관리",
    "딸기 전조처리 양액 EC 관수 관리",
]

app = FastAPI(
    title="Strawberry RAG API",
    description="딸기 시설원예 문서 RAG Q&A 및 디지털 트윈 셋포인트 추천 API",
    version="0.1.0",
)

embedder: SentenceTransformer | None = None
collection: Any | None = None
table: dict[str, Any] | None = None
llm: OpenAI | None = None
startup_error: str | None = None


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, description="질문")
    top_k: int = Field(DEFAULT_TOP_K, ge=1, le=20, description="검색 청크 수")
    include_contexts: bool = Field(True, description="검색된 근거 청크 포함 여부")


class RecommendRequest(BaseModel):
    planting_date: str = Field(..., description="정식일 YYYY-MM-DD")
    date: str | None = Field(None, description="대상일 YYYY-MM-DD")
    start: str | None = Field(None, description="기간 시작 YYYY-MM-DD")
    end: str | None = Field(None, description="기간 끝 YYYY-MM-DD")
    no_llm: bool = Field(False, description="LLM 설명 생략")


class BaselineState(BaseModel):
    sensorState: dict[str, Any] = Field(default_factory=dict)
    cropState: dict[str, Any] = Field(default_factory=dict)
    actuatorState: dict[str, Any] = Field(default_factory=dict)
    growthKpi: dict[str, Any] = Field(default_factory=dict)
    visionAssessment: dict[str, Any] = Field(default_factory=dict)


class BlueprintGenerateRequest(BaseModel):
    facilityId: str = Field("smartfarm-spark-a7ce", description="시설/트윈 식별자")
    objective: str = Field("earliest_viable_shipment", description="Blueprint 생성 목표")
    candidateCount: int = Field(3, ge=1, le=5, description="생성 후보 수")
    referenceDate: str | None = Field(None, description="현재 기준일 YYYY-MM-DD")
    plantingDate: str | None = Field(None, description="정식일 YYYY-MM-DD")
    currentDay: int | None = Field(None, description="현재 생육 일수")
    constraints: dict[str, Any] = Field(default_factory=dict)
    baseline: BaselineState = Field(default_factory=BaselineState)
    no_llm: bool = Field(False, description="LLM 후보 생성 생략")


class VisionAnalyzeRequest(BaseModel):
    facilityId: str = Field("smartfarm-spark-a7ce", description="시설/트윈 식별자")
    cameraPath: str = Field("", description="USD camera path")
    capturePath: str = Field("", description="Capture path on caller host")
    observedAt: str | None = Field(None, description="UTC observation timestamp")
    imageMimeType: str = Field("image/png", description="Image MIME type")
    imageBase64: str = Field(..., min_length=1, description="Base64-encoded crop camera image")
    objective: str = Field("Analyze strawberry growth progress", description="Analysis objective")
    sensorContext: dict[str, Any] = Field(default_factory=dict)
    cropContext: dict[str, Any] = Field(default_factory=dict)
    kpiContext: dict[str, Any] = Field(default_factory=dict)
    fallbackAssessment: dict[str, Any] = Field(default_factory=dict)


def _check_auth(authorization: str | None) -> None:
    if not API_TOKEN:
        if RAG_ALLOW_NO_AUTH:
            return
        raise HTTPException(status_code=503, detail="RAG_API_TOKEN is not configured")
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(
            status_code=401,
            detail="Authorization Bearer token이 필요합니다.",
            headers={"WWW-Authenticate": 'Bearer realm="rag-strawberry"'},
        )


def _parse_date(value: str) -> dt.date:
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"잘못된 날짜 형식: {value}") from e


def _daterange(start: dt.date, end: dt.date):
    cur = start
    while cur <= end:
        yield cur
        cur += dt.timedelta(days=1)


def _load_table() -> dict[str, Any]:
    with TABLE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _pick_stage(dap: int) -> dict[str, Any]:
    assert table is not None
    for stage in table["stages"]:
        if stage["dap_min"] <= dap <= stage["dap_max"]:
            return stage
    return table["stages"][-1]


def _apply_seasonal(base: dict[str, Any], month: int) -> tuple[dict[str, Any], list[str], str | None]:
    assert table is not None
    sp = copy.deepcopy(base["setpoints"])
    extra_sources: list[str] = []
    override_name = None
    for ov in table.get("seasonal_overrides", []):
        if month in ov["months"]:
            override_name = ov["name"]
            for key, val in ov["apply"].items():
                if key in sp and isinstance(sp[key], dict):
                    sp[key].update(val)
                else:
                    sp[key] = val
            extra_sources += ov.get("sources", [])
    return sp, extra_sources, override_name


def _chat(messages: list[dict[str, str]], *, temperature: float = 0.2, max_tokens: int | None = None) -> str:
    if llm is None:
        raise HTTPException(status_code=503, detail="LLM client is not ready")
    kwargs: dict[str, Any] = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    resp = llm.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def _retrieve(query: str, k: int = DEFAULT_TOP_K) -> list[dict[str, Any]]:
    if embedder is None or collection is None:
        raise HTTPException(status_code=503, detail="RAG collection is not ready")

    count = collection.count()
    if count <= 0:
        raise HTTPException(status_code=503, detail="RAG collection is empty")
    n_results = max(1, min(k, count))

    q_emb = embedder.encode([query], normalize_embeddings=True).tolist()
    results = collection.query(query_embeddings=q_emb, n_results=n_results)

    return [
        {
            "text": doc,
            "source": meta.get("source"),
            "page": meta.get("page"),
            "similarity": 1 - dist,
        }
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )
    ]


def _answer(question: str, contexts: list[dict[str, Any]]) -> str:
    context_str = "\n\n".join(
        f"[자료 {i + 1} | 출처: {c['source']} p.{c['page']}]\n{c['text']}"
        for i, c in enumerate(contexts)
    )
    user_prompt = f"""[참고 자료]
{context_str}

[질문]
{question}"""
    return _chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )


def _make_explanation(stage_name: str, season: str | None, sp: dict[str, Any]) -> str:
    seen: dict[str, dict[str, Any]] = {}
    for tmpl in SUBQUERY_TEMPLATES:
        for c in _retrieve(tmpl.format(stage=stage_name), k=3):
            seen.setdefault(c["text"][:120], c)
    contexts = list(seen.values())
    context_str = "\n\n".join(
        f"[자료 {i + 1} | {c['source']} p.{c['page']}]\n{c['text'][:400]}"
        for i, c in enumerate(contexts)
    )
    sp_str = json.dumps(sp, ensure_ascii=False, indent=2)
    season_line = f"- 계절 보정: {season}\n" if season else ""
    user = f"""[생육단계] {stage_name}
{season_line}
[확정 셋포인트]
{sp_str}

[참고 자료]
{context_str}

위 확정 셋포인트가 이 생육단계/계절에 왜 적절한지 2~4문장으로 설명하세요."""
    return _chat(
        [
            {"role": "system", "content": EXPLAIN_SYSTEM},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
    ).strip()


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    return int(round(_as_float(value, float(default))))


def _first(raw: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return default


def _range_target(raw: dict[str, Any], key: str, default: float) -> float:
    value = raw.get(key) or {}
    if isinstance(value, dict):
        return _as_float(value.get("target", value.get("min", default)), default)
    return _as_float(value, default)


def _baseline_summary(req: BlueprintGenerateRequest, stage_name: str) -> str:
    sensor = req.baseline.sensorState
    crop = req.baseline.cropState
    growth = req.baseline.growthKpi
    vision = req.baseline.visionAssessment
    constraints = req.constraints or {}
    return (
        f"{req.facilityId} baseline at {stage_name}: "
        f"DLI {_first(sensor, 'dli_mol_m2_day', 'dliMolM2Day', default='?')} mol/m²/day, "
        f"substrate moisture {_first(sensor, 'substrate_moisture_percent', 'soilMoisturePercent', default='?')}%, "
        f"RH {_first(sensor, 'humidity_percent', 'humidityPercent', default='?')}%, "
        f"temperature {_first(sensor, 'temperature_c', 'temperatureC', default='?')}°C, "
        f"CO₂ {_first(sensor, 'co2_ppm', 'co2Ppm', default='?')} ppm, "
        f"fruit maturity {_first(crop, 'fruitMaturity', 'fruit_maturity', default='?')}, "
        f"growth KPI health {_first(growth, 'healthScore', 'health_score', default='?')} "
        f"and readiness {_first(growth, 'harvestReadinessPercent', 'harvest_readiness_percent', default='?')}%, "
        f"vision risk {_first(vision, 'diseaseRisk', 'disease_risk', default='not-provided')}; "
        f"objective={req.objective}, constraints={json.dumps(constraints, ensure_ascii=False)}"
    )


def _blueprint_contexts(req: BlueprintGenerateRequest, stage_name: str) -> list[dict[str, Any]]:
    sensor = req.baseline.sensorState
    vision = req.baseline.visionAssessment
    queries = [
        f"{stage_name} 딸기 조기 출하 보광 CO2 관리",
        f"{stage_name} 딸기 온도 습도 환기 관리",
        "딸기 개화 착과 과실비대 양액 관수 EC pH 관리",
    ]
    if _as_float(_first(sensor, "humidity_percent", "humidityPercent", default=0), 0) >= 75:
        queries.append("딸기 고습 잿빛곰팡이 병해 환기 습도 관리")
    if _as_float(_first(sensor, "dli_mol_m2_day", "dliMolM2Day", default=99), 99) < 14:
        queries.append("딸기 저일조 보광 전조처리 광량 관리")
    if str(_first(vision, "diseaseRisk", "disease_risk", default="")).lower() in {"high", "높음"}:
        queries.append("딸기 병해 위험 생육 상태 조기 출하 환경 제어")

    seen: dict[str, dict[str, Any]] = {}
    for query in queries:
        for context in _retrieve(query, k=3):
            seen.setdefault(str(context["text"])[:160], context)
    return list(seen.values())[:8]


def _actuator_base(req: BlueprintGenerateRequest) -> dict[str, Any]:
    actuator = req.baseline.actuatorState
    return {
        "ledIntensityPercent": _as_int(_first(actuator, "ledIntensityPercent", "led_intensity_percent", default=40), 40),
        "photoperiodHours": _as_int(_first(actuator, "photoperiodHours", "photoperiod_hours", default=12), 12),
        "waterValveOpen": bool(_first(actuator, "waterValveOpen", "water_valve_open", default=False)),
        "irrigationPulsesPerDay": _as_int(
            _first(actuator, "irrigationPulsesPerDay", "irrigation_pulses_per_day", default=1), 1
        ),
        "fanDutyPercent": _as_int(_first(actuator, "fanDutyPercent", "fan_duty_percent", default=20), 20),
        "co2Ppm": _as_int(_first(actuator, "co2Ppm", "co2_ppm", default=420), 420),
    }


def _bounded_int(
    actuator: dict[str, Any],
    base: dict[str, Any],
    canonical_key: str,
    snake_key: str,
    minimum: float,
    maximum: float,
) -> int:
    default = base[canonical_key]
    value = _first(actuator, canonical_key, snake_key, default=default)
    return _as_int(_clamp(_as_float(value, default), minimum, maximum), default)


def _candidate_actuator(raw: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    actuator = raw.get("actuatorTargets") or raw.get("actuatorTarget") or raw.get("actuatorState") or raw
    if not isinstance(actuator, dict):
        actuator = {}
    return {
        "ledIntensityPercent": _bounded_int(actuator, base, "ledIntensityPercent", "led_intensity_percent", 0, 100),
        "photoperiodHours": _bounded_int(actuator, base, "photoperiodHours", "photoperiod_hours", 8, 18),
        "waterValveOpen": bool(_first(actuator, "waterValveOpen", "water_valve_open", default=base["waterValveOpen"])),
        "irrigationPulsesPerDay": _bounded_int(
            actuator, base, "irrigationPulsesPerDay", "irrigation_pulses_per_day", 0, 8
        ),
        "fanDutyPercent": _bounded_int(actuator, base, "fanDutyPercent", "fan_duty_percent", 0, 100),
        "co2Ppm": _bounded_int(actuator, base, "co2Ppm", "co2_ppm", 380, 900),
    }


def _fallback_blueprint_candidates(req: BlueprintGenerateRequest, sp: dict[str, Any], evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sensor = req.baseline.sensorState
    base = _actuator_base(req)
    humidity_target = _range_target(sp, "humidity_pct", 66.0)
    co2_target = min(_range_target(sp, "co2_ppm", 800.0), 900.0)
    light = sp.get("supplemental_light") or {}
    light_hours = _as_float(light.get("hours_per_day") if isinstance(light, dict) else 0.0, 0.0)
    dli_target = _clamp(14.0 + light_hours * 0.75, 14.0, 20.0)
    dli_gap = max(0.0, dli_target - _as_float(_first(sensor, "dli_mol_m2_day", "dliMolM2Day", default=11.0), 11.0))
    humidity_excess = max(0.0, _as_float(_first(sensor, "humidity_percent", "humidityPercent", default=72.0), 72.0) - humidity_target)
    moisture_gap = max(0.0, 46.0 - _as_float(_first(sensor, "substrate_moisture_percent", "soilMoisturePercent", default=42.0), 42.0))

    templates = [
        (
            "blueprint-a",
            "Blueprint A",
            "가장 빠른 조기 출하",
            {
                "ledIntensityPercent": max(72, base["ledIntensityPercent"] + dli_gap * 4.5),
                "photoperiodHours": max(15, base["photoperiodHours"] + dli_gap * 0.40),
                "irrigationPulsesPerDay": max(3, base["irrigationPulsesPerDay"] + moisture_gap / 12.0),
                "fanDutyPercent": max(48, base["fanDutyPercent"] + humidity_excess * 0.75),
                "co2Ppm": max(720, co2_target),
                "waterValveOpen": True,
            },
            "출하 단축을 위해 DLI와 CO₂ 결핍을 우선 보정합니다.",
            "가장 공격적이며 전력/CO₂ 사용량이 큽니다.",
        ),
        (
            "blueprint-b",
            "Blueprint B",
            "조기 출하와 비용 균형",
            {
                "ledIntensityPercent": max(58, base["ledIntensityPercent"] + dli_gap * 3.0),
                "photoperiodHours": max(13, base["photoperiodHours"] + dli_gap * 0.28),
                "irrigationPulsesPerDay": max(2, base["irrigationPulsesPerDay"] + moisture_gap / 10.0),
                "fanDutyPercent": max(36, base["fanDutyPercent"] + humidity_excess * 0.65),
                "co2Ppm": max(620, min(800, co2_target)),
                "waterValveOpen": True,
            },
            "문헌 setpoint와 현재 gap 사이를 비용 제약 내에서 보정합니다.",
            "출하 단축과 운영비 사이의 균형안입니다.",
        ),
        (
            "blueprint-c",
            "Blueprint C",
            "병해 리스크 안전",
            {
                "ledIntensityPercent": max(62, base["ledIntensityPercent"] + dli_gap * 2.5),
                "photoperiodHours": max(14, base["photoperiodHours"] + dli_gap * 0.25),
                "irrigationPulsesPerDay": max(2, min(4, base["irrigationPulsesPerDay"] + moisture_gap / 14.0)),
                "fanDutyPercent": max(66, base["fanDutyPercent"] + humidity_excess * 1.15),
                "co2Ppm": max(600, min(780, co2_target)),
                "waterValveOpen": True,
            },
            "고습/병해 위험을 먼저 낮추고 생육을 안정적으로 밀어줍니다.",
            "가장 안전하지만 출하 단축 폭은 제한적입니다.",
        ),
    ]
    candidates = []
    for cid, label, intent, actuator, rationale, tradeoff in templates[: req.candidateCount]:
        candidates.append({
            "id": cid,
            "label": label,
            "intent": intent,
            "actuatorTargets": _candidate_actuator(actuator, base),
            "rationale": rationale,
            "tradeoff": tradeoff,
            "riskNotes": tradeoff,
            "evidence": evidence[:3],
        })
    return candidates


def _json_object_from_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if "\n" in stripped:
            stripped = stripped.split("\n", 1)[1]
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LLM blueprint response is not a JSON object")
    return parsed


def _percent_from(*values: Any, default: float = 0.0) -> int:
    for value in values:
        if value is None:
            continue
        parsed = _as_float(value, -1.0)
        if parsed < 0:
            continue
        if 0.0 <= parsed <= 1.0:
            parsed *= 100.0
        return _as_int(_clamp(parsed, 0.0, 100.0), int(default))
    return _as_int(_clamp(default, 0.0, 100.0), int(default))


def _vision_fallback_assessment(req: VisionAnalyzeRequest, *, mode: str, warning: str | None = None) -> dict[str, Any]:
    fallback = req.fallbackAssessment or {}
    sensor = req.sensorContext or {}
    crop = req.cropContext or {}
    kpi = req.kpiContext or {}
    maturity = _percent_from(
        _first(fallback, "fruitMaturityPercent", "maturityPercent"),
        _as_float(_first(crop, "fruitMaturity", "fruit_maturity", default=-1), -1),
        _as_float(_first(sensor, "growth_index", "growthIndex", default=-1), -1),
        default=42,
    )
    readiness = _percent_from(
        _first(fallback, "harvestReadinessPercent", "readinessPercent"),
        _first(kpi, "harvestReadinessPercent", "harvest_readiness_percent"),
        maturity + 3,
        default=maturity,
    )
    progress = _percent_from(
        _first(fallback, "growthProgressPercent", "growthPercent", "percentOfFullCycle"),
        readiness,
        maturity,
        default=readiness,
    )
    fruit_set = _percent_from(
        _first(fallback, "fruitSetPercent", "fruitSet"),
        _as_float(_first(crop, "fruitSet", "fruit_set", default=-1), -1),
        default=max(0, maturity + 6),
    )
    canopy = _percent_from(
        _first(fallback, "canopyVigorPercent", "canopyPercent"),
        _as_float(_first(crop, "vegetativeGrowth", "vegetative_growth", default=-1), -1),
        default=max(45, progress),
    )
    disease_pressure = _as_float(_first(crop, "diseasePressure", "disease_pressure", default=0), 0)
    humidity = _as_float(_first(sensor, "humidity_percent", "humidityPercent", default=0), 0)
    disease = str(_first(fallback, "diseaseRisk", "disease_risk", default="") or "").lower()
    if disease not in {"low", "controlled", "high"}:
        disease = "high" if disease_pressure >= 0.62 or humidity >= 78 else ("controlled" if humidity >= 70 else "low")
    health_default = 100 - disease_pressure * 42 - max(0, humidity - 72) * 1.2
    health = _percent_from(_first(fallback, "healthScore", "healthPercent"), _first(kpi, "healthScore", "health_score"), default=health_default)
    stage = str(
        _first(fallback, "phenotypeStage", "growthStage", default="")
        or _first(kpi, "stage", default="")
        or _first(sensor, "crop_stage", "cropStage", default="strawberry growth stage")
    )
    traits = [
        f"Image received from {req.cameraPath or 'growth camera'} ({req.imageMimeType}).",
        f"Estimated {progress}% full-cycle progress from crop context and visual-analysis fallback.",
        f"Disease risk {disease}; humidity {humidity:g}% and maturity {maturity}%.",
    ]
    if warning:
        traits.append(f"Gemma vision fallback reason: {warning}")
    return {
        "provider": "twinx-gemma-vision",
        "model": LLM_MODEL,
        "analysisMode": mode,
        "growthProgressPercent": progress,
        "fruitMaturityPercent": maturity,
        "fruitSetPercent": fruit_set,
        "canopyVigorPercent": canopy,
        "harvestReadinessPercent": readiness,
        "healthScore": health,
        "diseaseRisk": disease,
        "phenotypeStage": stage,
        "confidence": "gemma-text-fallback" if warning else "context-derived",
        "traits": traits[:6],
        "recommendation": "Use the generated vision assessment as context for the next Blueprint generation run.",
        "summary": f"{progress}% growth progress, health {health}/100, disease risk {disease}.",
        "basis": "Gemma vision endpoint accepted the capture request; deterministic guardrail filled missing fields.",
    }


def _normalize_vision_assessment(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    base = dict(fallback)
    out = {**base, **raw}
    out["provider"] = str(out.get("provider") or "twinx-gemma-vision")
    out["model"] = str(out.get("model") or LLM_MODEL)
    out["analysisMode"] = str(out.get("analysisMode") or "gemma_vision_json")
    out["growthProgressPercent"] = _percent_from(out.get("growthProgressPercent"), out.get("growthPercent"), out.get("percentOfFullCycle"), default=50)
    out["fruitMaturityPercent"] = _percent_from(out.get("fruitMaturityPercent"), out.get("maturityPercent"), default=out["growthProgressPercent"])
    out["fruitSetPercent"] = _percent_from(out.get("fruitSetPercent"), out.get("fruitSet"), default=max(0, out["fruitMaturityPercent"] + 5))
    out["canopyVigorPercent"] = _percent_from(out.get("canopyVigorPercent"), out.get("canopyPercent"), default=max(45, out["growthProgressPercent"]))
    out["harvestReadinessPercent"] = _percent_from(out.get("harvestReadinessPercent"), out.get("readinessPercent"), default=out["growthProgressPercent"])
    out["healthScore"] = _percent_from(out.get("healthScore"), out.get("healthPercent"), default=75)
    disease = str(out.get("diseaseRisk") or "controlled").lower()
    out["diseaseRisk"] = disease if disease in {"low", "controlled", "high"} else "controlled"
    out["phenotypeStage"] = str(out.get("phenotypeStage") or out.get("growthStage") or "strawberry growth stage")
    out["confidence"] = str(out.get("confidence") or "gemma-vision")
    traits = out.get("traits") or out.get("visualEvidence") or out.get("evidence") or out.get("observations")
    if isinstance(traits, list):
        out["traits"] = [str(item) for item in traits[:6]]
    elif traits:
        out["traits"] = [str(traits)]
    else:
        out["traits"] = [str(out.get("summary") or "Gemma returned a growth assessment from the capture.")]
    out["recommendation"] = str(out.get("recommendation") or "Use this vision assessment in the next Blueprint generation run.")
    out["summary"] = str(out.get("summary") or f"{out['growthProgressPercent']}% growth progress, health {out['healthScore']}/100.")
    out["basis"] = str(out.get("basis") or "captured PNG sent to Gemma vision endpoint")
    return out


def _llm_vision_assessment(req: VisionAnalyzeRequest) -> dict[str, Any]:
    try:
        image_bytes = base64.b64decode(req.imageBase64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"imageBase64 is not valid base64: {e}") from e
    if not image_bytes:
        raise HTTPException(status_code=400, detail="imageBase64 decoded to empty image")
    if len(image_bytes) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="imageBase64 image is larger than 8 MiB")

    context = {
        "facilityId": req.facilityId,
        "cameraPath": req.cameraPath,
        "capturePath": req.capturePath,
        "observedAt": req.observedAt,
        "objective": req.objective,
        "sensorContext": req.sensorContext,
        "cropContext": req.cropContext,
        "kpiContext": req.kpiContext,
        "fallbackAssessment": req.fallbackAssessment,
    }
    user_text = (
        "Analyze this strawberry greenhouse crop capture for the SmartFarm twin. "
        "Return only JSON matching the schema. Context:\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )
    data_url = f"{req.imageMimeType};base64,{req.imageBase64}"
    if not data_url.startswith("data:"):
        data_url = "data:" + data_url
    try:
        raw_text = _chat(
            [
                {"role": "system", "content": VISION_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            temperature=0.1,
            max_tokens=900,
        )
        parsed = _json_object_from_text(raw_text)
        parsed["analysisMode"] = parsed.get("analysisMode") or "gemma_vision_json"
        parsed["imageBytes"] = len(image_bytes)
        return _normalize_vision_assessment(parsed, req.fallbackAssessment)
    except HTTPException:
        raise
    except Exception as e:
        # Some Gemma/vLLM deployments are text-only. Keep the endpoint useful and
        # explicit rather than forcing the OmniOps UI back to a silent local mock.
        fallback = _vision_fallback_assessment(req, mode="gemma_vision_fallback", warning=f"{type(e).__name__}: {e}")
        fallback["imageBytes"] = len(image_bytes)
        return fallback


def _llm_blueprint_candidates(
    req: BlueprintGenerateRequest,
    stage_name: str,
    sp: dict[str, Any],
    contexts: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    base = _actuator_base(req)
    context_str = "\n\n".join(
        f"[자료 {i + 1} | {c['source']} p.{c['page']}]\n{str(c['text'])[:700]}"
        for i, c in enumerate(contexts)
    )
    user = f"""[목표]
{req.objective}

[생육단계]
{stage_name}

[현재 Baseline Twin 상태]
{_baseline_summary(req, stage_name)}

[문헌 기반 setpoint guardrail]
{json.dumps(sp, ensure_ascii=False, indent=2)}

[actuator 현재값]
{json.dumps(base, ensure_ascii=False, indent=2)}

[actuator bounds]
LED 0~100%, photoperiod 8~18h, irrigation 0~8회/day, fan 0~100%, CO₂ 380~900ppm

[참고 자료]
{context_str}

현재 Baseline을 변경하지 말고, Twin 시뮬레이션에 넣을 Blueprint A/B/C 후보만 JSON으로 생성하세요."""
    parsed = _json_object_from_text(_chat(
        [
            {"role": "system", "content": BLUEPRINT_SYSTEM},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=1400,
    ))
    raw_candidates = parsed.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("LLM blueprint response missing candidates")
    normalized = []
    for idx, raw in enumerate(raw_candidates[: req.candidateCount]):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or f"Blueprint {chr(ord('A') + idx)}")
        normalized.append({
            "id": str(raw.get("id") or f"blueprint-{chr(ord('a') + idx)}"),
            "label": label,
            "intent": str(raw.get("intent") or raw.get("operatorIntent") or label),
            "actuatorTargets": _candidate_actuator(raw, base),
            "rationale": str(raw.get("rationale") or ""),
            "tradeoff": str(raw.get("tradeoff") or raw.get("riskNotes") or ""),
            "riskNotes": str(raw.get("riskNotes") or raw.get("tradeoff") or ""),
            "evidence": evidence[:3],
        })
    if not normalized:
        raise ValueError("LLM blueprint candidates were not usable")
    return normalized


def _recommend_one(target: dt.date, planting: dt.date, *, with_llm: bool) -> dict[str, Any]:
    dap = (target - planting).days
    stage = _pick_stage(dap)
    sp, extra_sources, season = _apply_seasonal(stage, target.month)
    result: dict[str, Any] = {
        "date": target.isoformat(),
        "planting_date": planting.isoformat(),
        "days_after_planting": dap,
        "growth_stage": stage["name"],
        "seasonal_adjustment": season,
        "setpoints": sp,
        "sources": list(stage["sources"]) + extra_sources,
    }
    if with_llm:
        try:
            result["explanation"] = _make_explanation(stage["name"], season, sp)
        except Exception as e:  # explanation should not break deterministic setpoints
            result["explanation"] = f"(설명 생성 실패: {e})"
    return result


@app.on_event("startup")
def startup() -> None:
    global embedder, collection, table, llm, startup_error
    try:
        llm = OpenAI(base_url=OPENAI_BASE_URL, api_key=OPENAI_API_KEY)
        if VERIFY_LLM_ON_STARTUP:
            models = [m.id for m in llm.models.list().data]
            if LLM_MODEL not in models:
                raise RuntimeError(f"model {LLM_MODEL!r} not found. available={models}")

        if not DB_DIR.exists():
            raise RuntimeError(f"DB_DIR not found: {DB_DIR}")
        if not TABLE_PATH.exists():
            raise RuntimeError(f"TABLE_PATH not found: {TABLE_PATH}")

        table = _load_table()
        embedder = SentenceTransformer(EMBEDDING_MODEL)
        chroma_client = chromadb.PersistentClient(path=str(DB_DIR))
        collection = chroma_client.get_collection(COLLECTION_NAME)
        startup_error = None
    except Exception as e:
        startup_error = f"{type(e).__name__}: {e}"
        raise


@app.get("/livez")
def livez() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    if startup_error:
        raise HTTPException(status_code=503, detail=startup_error)
    if collection is None or table is None or llm is None:
        raise HTTPException(status_code=503, detail="not ready")
    return {
        "status": "ok",
        "model": LLM_MODEL,
        "collection": COLLECTION_NAME,
        "collection_count": collection.count(),
    }


@app.post("/ask")
def ask(req: AskRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _check_auth(authorization)
    contexts = _retrieve(req.question, k=req.top_k)
    answer = _answer(req.question, contexts)
    res: dict[str, Any] = {"question": req.question, "answer": answer}
    if req.include_contexts:
        res["contexts"] = contexts
    return res


@app.post("/recommend")
def recommend(req: RecommendRequest, authorization: str | None = Header(default=None)) -> dict[str, Any] | list[dict[str, Any]]:
    _check_auth(authorization)
    if table is None:
        raise HTTPException(status_code=503, detail="setpoint table is not ready")

    planting = _parse_date(req.planting_date)
    if req.date:
        targets = [_parse_date(req.date)]
    elif req.start and req.end:
        start, end = _parse_date(req.start), _parse_date(req.end)
        if end < start:
            raise HTTPException(status_code=400, detail="end는 start보다 빠를 수 없습니다.")
        targets = list(_daterange(start, end))
    else:
        raise HTTPException(status_code=400, detail="date 또는 start/end를 지정하세요.")

    results = [_recommend_one(target, planting, with_llm=not req.no_llm) for target in targets]
    return results[0] if len(results) == 1 else results


@app.post("/blueprints/generate")
def generate_blueprints(req: BlueprintGenerateRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Generate state-aware Blueprint candidates from the current Baseline Twin."""
    _check_auth(authorization)
    if table is None:
        raise HTTPException(status_code=503, detail="setpoint table is not ready")

    if req.referenceDate:
        target = _parse_date(req.referenceDate)
    else:
        target = dt.date.today()

    if req.plantingDate:
        planting = _parse_date(req.plantingDate)
        dap = (target - planting).days
    elif req.currentDay is not None:
        dap = int(req.currentDay)
        planting = target - dt.timedelta(days=max(0, dap))
    else:
        sensor_day = _first(req.baseline.sensorState, "twin_day", "twinDay", default=34)
        dap = _as_int(sensor_day, 34)
        planting = target - dt.timedelta(days=max(0, dap))

    stage = _pick_stage(dap)
    sp, extra_sources, season = _apply_seasonal(stage, target.month)
    contexts = _blueprint_contexts(req, stage["name"])
    evidence = [
        {
            "source": c.get("source"),
            "page": c.get("page"),
            "summary": str(c.get("text", ""))[:220],
            "similarity": c.get("similarity"),
        }
        for c in contexts[:5]
    ]
    for source in list(stage.get("sources", [])) + extra_sources:
        evidence.append({"source": source, "summary": source})

    generation_mode = "deterministic_no_llm" if req.no_llm else "gemma_json"
    warnings: list[str] = []
    try:
        candidates = _fallback_blueprint_candidates(req, sp, evidence) if req.no_llm else _llm_blueprint_candidates(
            req, stage["name"], sp, contexts, evidence
        )
    except Exception as e:
        generation_mode = "deterministic_fallback"
        warning = f"Gemma JSON generation fallback: {type(e).__name__}: {e}"
        warnings.append(warning)
        candidates = _fallback_blueprint_candidates(req, sp, evidence)
        for candidate in candidates:
            candidate["generationWarning"] = warning

    logger.info(
        "blueprints.generate facility=%s objective=%s mode=%s candidates=%s warnings=%s evidence=%s",
        req.facilityId,
        req.objective,
        generation_mode,
        len(candidates),
        len(warnings),
        len(evidence[:8]),
    )
    return {
        "provider": "twinx-gemma-rag",
        "model": LLM_MODEL,
        "facilityId": req.facilityId,
        "objective": req.objective,
        "referenceDate": target.isoformat(),
        "plantingDate": planting.isoformat(),
        "currentDay": dap,
        "growthStage": stage["name"],
        "seasonalAdjustment": season,
        "generationMode": generation_mode,
        "warnings": warnings,
        "baselineSummary": _baseline_summary(req, stage["name"]),
        "setpoints": sp,
        "constraints": req.constraints,
        "evidence": evidence[:8],
        "candidates": candidates,
    }


def _vision_response(req: VisionAnalyzeRequest, authorization: str | None) -> dict[str, Any]:
    _check_auth(authorization)
    assessment = _llm_vision_assessment(req)
    mode = str(assessment.get("analysisMode") or "")
    confidence = str(assessment.get("confidence") or "")
    image_bytes = assessment.get("imageBytes")
    logger.info(
        "vision.analyze facility=%s camera=%s mode=%s confidence=%s imageBytes=%s fallback=%s",
        req.facilityId,
        req.cameraPath,
        mode or "-",
        confidence or "-",
        image_bytes if image_bytes is not None else "-",
        "yes" if "fallback" in f"{mode} {confidence}".lower() else "no",
    )
    return {
        "provider": "twinx-gemma-vision",
        "model": LLM_MODEL,
        "analysisMode": mode,
        "confidence": confidence,
        "cameraPath": req.cameraPath,
        "capturePath": req.capturePath,
        "observedAt": req.observedAt,
        "imageBytes": image_bytes,
        "assessment": assessment,
    }


@app.post("/vision/analyze")
def vision_analyze(req: VisionAnalyzeRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    return _vision_response(req, authorization)


@app.post("/analyze/growth")
def analyze_growth(req: VisionAnalyzeRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    return _vision_response(req, authorization)


@app.post("/phenotype/analyze")
def phenotype_analyze(req: VisionAnalyzeRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    return _vision_response(req, authorization)


@app.post("/analyze")
def analyze(req: VisionAnalyzeRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    return _vision_response(req, authorization)


@app.get("/")
def root(request: Request) -> dict[str, Any]:
    return {
        "name": "rag-strawberry",
        "model": LLM_MODEL,
        "openapi": str(request.url_for("openapi")),
        "docs": "/docs",
        "endpoints": {
            "health": "/healthz",
            "ask": "/ask",
            "recommend": "/recommend",
            "generate_blueprints": "/blueprints/generate",
            "vision_analyze": "/vision/analyze",
        },
        "examples": {
            "ask": {"question": "봄철 딸기 온실의 적정 낮 온도와 밤 온도는?", "top_k": 5},
            "recommend": {"planting_date": "2025-09-15", "date": "2025-11-15"},
            "generate_blueprints": {
                "objective": "earliest_viable_shipment",
                "candidateCount": 3,
                "referenceDate": "2026-06-15",
                "currentDay": 34,
                "baseline": {
                    "sensorState": {
                        "dli_mol_m2_day": 11.2,
                        "substrate_moisture_percent": 31,
                        "humidity_percent": 82,
                        "temperature_c": 24.8,
                        "co2_ppm": 420,
                    }
                },
            },
            "vision_analyze": {
                "cameraPath": "/World/SmartFarm/Cameras/GrowthPhenotypeCamera",
                "imageMimeType": "image/png",
                "imageBase64": "...",
                "sensorContext": {"humidity_percent": 82, "dli_mol_m2_day": 11.2},
            },
        },
    }
