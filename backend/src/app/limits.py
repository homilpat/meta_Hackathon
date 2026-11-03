"""Every operating limit in one place, with where its value comes from (spec v5.8 §23.5: configurable and stated).

Who may change a value: the AI operations department (role AGENT_ADMIN) at POST /limits/{name}, with a reason,
recorded append-only in limit_settings; the deployment may also set QO_<NAME>. A recorded setting wins over the
environment, which wins over the default. Everyone can read the effective table at GET /limits. Values bound into
request schemas when the server starts take effect after a restart (marked restart_required).
basis:
  STANDARD  an outside rule or a documented external limit (source given)
  MEASURED  measured on this system (docs/evaluations/limits_measure.json)
  DERIVED   computed from other values or from the format itself (formula given)
  DECISION  decided by a person (who and when given)
  DEFAULT   an arbitrary starting value: the owner sets it (e.g. from the company budget)
"""

import os
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.fields import FreeText

ADMIN_ROLE = "AGENT_ADMIN"
OVERRIDES: dict[str, object] = {}  # recorded settings of this process (loaded at start, updated on change)
RESTART = {"MAX_FILES_PER_UPLOAD", "MAX_REQUEST_ITEMS"}  # fixed in request schemas at start
CHOICES = {"MODEL_RESPONSE_REUSE": {"ON", "OFF"}, "INVESTIGATION_REASONING_EFFORT": {"minimal", "default"}, "EXTRACT_MODE": {"WHOLE_FIRST", "HYBRID", "WHOLE", "AUTO", "AI_CHOICE"}}
OFF_ALLOWED = {"MAX_COST_PER_MODEL_CALL_USD", "MODEL_TEMPERATURE", "MODEL_SEED", "INVESTIGATION_MAX_COST_USD",
               "INVESTIGATION_MAX_REPAIRS"}  # 0 is a valid setting


@dataclass(frozen=True)
class Limit:
    default: object
    unit: str
    basis: str
    source: str


LIMITS: dict[str, Limit] = {
    "MAX_UPLOAD_BYTES": Limit(10 * 1024 * 1024, "bytes per file", "DECISION",
                              "user, 2026-11-01 (IN0 decision 1)"),
    "MAX_FILES_PER_UPLOAD": Limit(5, "files per request", "DEFAULT", "starting value; set by the owner"),
    "MAX_COMPRESSION_RATIO": Limit(100, "uncompressed / compressed, per entry and in total", "STANDARD",
                                   "zip-bomb guidance: ratio < 100:1 (knowledgelib.io file-upload-security; "
                                   "privacy-tools-guide secure file upload). Sonar RSPEC-5042 uses 10 in its "
                                   "example, but ordinary DOCX measured here reach 24x in total and 32x per entry"),
    "MAX_ZIP_ENTRIES": Limit(10000, "entries per Office file", "STANDARD", "Sonar RSPEC-5042 THRESHOLD_ENTRIES"),
    "MAX_UNZIPPED_BYTES": Limit(10 * 1024 * 1024 * 100, "bytes unpacked", "DERIVED",
                                "MAX_UPLOAD_BYTES x MAX_COMPRESSION_RATIO (= Sonar RSPEC-5042 THRESHOLD_SIZE 1 GB)"),
    "PARSE_TIME_BUDGET_S": Limit(50.0, "seconds of server parsing per analysis", "DERIVED",
                                 "provider timeout 60 s - LIVE extraction p95 about 10 s (META_LIVE_LOG); "
                                 "parsing stops there and the rest is marked unprocessed"),
    "MAX_IMAGES_PER_CALL": Limit(9, "images in one model call", "STANDARD",
                                 "Llama API: at most 9 images per request, 25 MB each (llama.developer.meta.com; "
                                 "promptfoo llamaApi provider docs). muse-spark-1.3 accepted and read 10 in the "
                                 "2026-11-01 probe (META_LIVE_LOG), so 9 is the documented, not a measured, ceiling"),
    "MODEL_CONTEXT_TOKENS": Limit(1048576, "tokens the model accepts in one call", "STANDARD",
                                  "Meta Model API docs: muse-spark family context window 1,048,576 tokens "
                                  "(ai.developer.meta.com/docs/models)"),
    "MODEL_PRICE_INPUT_PER_M_USD": Limit(1.25, "USD per million input tokens", "STANDARD",
                                         "api.meta.ai published price for muse-spark-1.1 (1.3 not separately "
                                         "confirmed)"),
    "MODEL_PRICE_OUTPUT_PER_M_USD": Limit(4.25, "USD per million output tokens", "STANDARD",
                                          "api.meta.ai published price for muse-spark-1.1 (1.3 not separately "
                                          "confirmed)"),
    "MAX_COST_PER_MODEL_CALL_USD": Limit(0.0, "USD of input per document-model call; 0 = off", "DECISION",
                                         "user, 2026-11-01: the context window is the cap; a cost cap is optional "
                                         "and set from the company's model budget when wanted"),
    "EXTRACT_MODE": Limit("WHOLE_FIRST", "how documents reach the model: WHOLE_FIRST, WHOLE, HYBRID, AUTO or AI_CHOICE "
                          "(the server narrows by size and budget, Meta picks between feasible methods; v5.14 AI-CFG-03)",
                          "DECISION", "user, 2026-11-02, after the CUAD LIVE runs: WHOLE_FIRST reads every element "
                          "when it fits one call (context and cost cap) and uses HYBRID (contents + server selection "
                          "+ the model asks for parts) only beyond that. WHOLE always reads all (in pieces); AUTO picks "
                          "the cheaper by estimate"),
    "EXTRACT_COMPLETION_TOKENS_PER_CALL": Limit(1274, "output tokens of one extraction call, for AUTO's estimate",
                                                "MEASURED", "CUAD held-out LIVE 2026-11-02: 62,409 completion tokens "
                                                "over 49 calls (conditions A, B, C; muse-spark-1.3, minimal effort)"),
    "TOKENS_PER_ESTIMATE_TEXT": Limit(1.34, "actual prompt tokens per estimated token, document elements",
                                      "MEASURED", "CUAD held-out LIVE 2026-11-02, WHOLE: 526,682 actual / 393,138 "
                                      "estimated (muse-spark-1.3)"),
    "TOKENS_PER_ESTIMATE_MAP": Limit(2.3, "actual prompt tokens per estimated token, document maps (word lists)",
                                     "MEASURED", "CUAD held-out LIVE 2026-11-02, HYBRID: 473,099 actual / 234,885 "
                                     "estimated, maps 70% of the estimate; (2.014 - 0.3 x 1.34) / 0.7"),
    "HYBRID_MAX_PARTS_PER_ROUND": Limit(5, "pages or sections the model may ask for per round", "DEFAULT",
                                        "arbitrary starting value: bounds a round's size; set by the owner"),
    "EXTRACT_MAX_ROUNDS": Limit(2, "model calls per document analysis (round 2 asks only for missing fields)",
                                "DEFAULT", "arbitrary starting value: each round is a paid call; set by the owner"),
    "BYTES_PER_TOKEN": Limit(4.0, "UTF-8 bytes per token, for estimating before a call", "STANDARD",
                             "rule of thumb ~4 characters per token for English text (OpenAI tokenizer guidance); "
                             "Korean is ~3 bytes per character, so the estimate is conservative. Calibrate with "
                             "the usage recorded on every call"),
    "IMAGE_TOKENS": Limit(390, "input tokens one image costs, for estimating", "MEASURED",
                          "LIVE 2026-11-01: 2,414 prompt tokens = 790 text + 362 prompt + 481 schema (estimated) + 2 "
                          "images -> about 390 each (one run; recalibrate from recorded usage)"),
    "EXTRACT_REASONING_EFFORT": Limit("minimal", "reasoning effort of the document extraction call", "MEASURED",
                                      "LIVE 2026-11-01 on the LIVE fixture: minimal 8/8 in 8.4 s and 7/8 in 7.4 s, "
                                      "default 8/8 in 19.5 s (META_LIVE_LOG); speed vs completeness is the owner's "
                                      "choice ('minimal' or 'default')"),
    "MODEL_TEMPERATURE": Limit(0.0, "sampling temperature sent with every model call", "DECISION",
                               "user, 2026-11-02: answers as repeatable as the model allows. Muse accepts 0-2, API "
                               "default 1.0 (LiteLLM / promptfoo provider docs; not yet confirmed on api.meta.ai). "
                               "0 = always the most likely token; it narrows, but does not remove, run-to-run change"),
    "MODEL_SEED": Limit(1, "sampling seed sent with every model call (0 = not sent)", "DEFAULT",
                        "any fixed integer: the value does not matter, only that it stays the same; reproducibility "
                        "is best effort on the provider's side"),
    "MODEL_RESPONSE_REUSE": Limit("ON", "ON: an identical request (same model, messages, tools, schema and settings) "
                                        "gets the stored answer instead of a new call", "DECISION",
                                  "user, 2026-11-02: the same document and question must not get a different "
                                  "answer on a second look; OFF for a fresh answer. Evaluations call the model "
                                  "directly (scripts/evalkit.py) so run-to-run change stays measurable"),
    "MODEL_MAX_OUTPUT_TOKENS": Limit(131072, "output tokens one model call may write (its reasoning included)",
                                     "STANDARD", "Muse Spark documented maximum output (Vercel AI Gateway, LiteLLM "
                                     "provider docs); replaces a fixed 8,192 that cut 2 of 8 LIVE investigation "
                                     "reports. Reasoning tokens count toward it and bill at the output price"),
    "MODEL_OUTPUT_TOKENS_PER_S": Limit(116, "slowest measured output speed, tokens per second", "MEASURED",
                                       "LIVE investigation calls 2026-11-02: 38 calls over 1,000 output tokens, "
                                       "min 116, p10 125, median 167 tokens/s (muse-spark-1.3)"),
    "INVESTIGATION_REASONING_EFFORT": Limit("minimal", "reasoning effort of investigation calls ('minimal' or "
                                            "'default')", "DECISION",
                                            "user, 2026-11-02: 71% of the investigation's output tokens were "
                                            "reasoning at the default; extraction measured the same answers ~3x "
                                            "faster at minimal. Measured again on the LIVE loop run"),
    "INVESTIGATION_MAX_COST_USD": Limit(0.0, "USD per investigation run (0 = off: each call is bounded by the "
                                        "model's input, MODEL_CONTEXT_TOKENS)", "DECISION",
                                        "user, 2026-11-02: the same rule as document extraction; the owner sets an "
                                        "amount from the budget. Replaces a fixed 30,000-token run cap that stopped "
                                        "4 of 13 LIVE runs (a complete run measured 40-50k prompt tokens, $0.06-0.08)"),
    "INVESTIGATION_MAX_REPAIRS": Limit(2, "times one investigation may fix a report the server refused", "DEFAULT",
                                       "starting value, set by the owner: each repair is a paid call and counts "
                                       "toward INVESTIGATION_MAX_ROUNDS; a repeated identical error stops at once"),
    "INVESTIGATION_MAX_ROUNDS": Limit(5, "model calls per investigation run", "DEFAULT",
                                      "starting value, set by the owner; LIVE runs on 2026-11-02 used 3-5"),
    "INVESTIGATION_MAX_TOOL_CALLS": Limit(8, "tool calls per investigation run", "DEFAULT",
                                          "starting value, set by the owner; LIVE runs on 2026-11-02 used 4-6"),
    "INVESTIGATION_DEADLINE_S": Limit(300, "seconds per investigation run", "DEFAULT",
                                      "starting value: wall time of one run (LIVE runs took 50-70 s); each call is "
                                      "bounded by the provider timeout (limits.model_timeout_s)"),
    "INVESTIGATION_RUNS_PER_USER_HOUR": Limit(10, "investigation runs per user per hour", "DEFAULT",
                                              "starting value, set from the company's model budget"),
    "MODEL_RUNS_PER_USER_HOUR": Limit(30, "agent model runs per user per hour", "DEFAULT",
                                      "arbitrary starting value; set from the company's model budget"),
    "MAX_RECOMMENDATIONS": Limit(3, "agent recommendations shown per run", "DEFAULT",
                                 "screen default; set by the owner"),
    "MAX_INTAKE_QUESTIONS": Limit(8, "AI questions shown per intake draft", "DEFAULT",
                                  "screen default; set by the owner"),
    "MIN_RECOMMENDATION_GRADE": Limit("B", "lowest evidence grade shown as a recommendation (A best)", "DECISION",
                                      "proposed default, set by the owner: A = matches a past case whose effect was "
                                      "verified, B = controlled document or unverified case, C = this case's data "
                                      "only (shown folded as 참고). Grades come from the sources, never from a "
                                      "model's confidence (spec §23.3)"),
    "MAX_REQUEST_ITEMS": Limit(20, "items per request card", "DEFAULT", "screen default; set by the owner"),
    "XLSX_HEADER_TERMS_EN": Limit("lot,lots,batch,part,no,number,item,code,id,qty,quantity,inspected,inspection,insp,checked,check,sample,size,total,accepted,accept,rejected,reject,pass,passed,fail,failed,ng,ok,good,defect,defects,defective,date,unit,uom,value,measured,result,remarks,rate,count,pcs,ea",
                                     "readable header terms, comma separated (EN)", "DECISION", "user, 2026-11-03: a protected file's header words go masked except the inspection terms of its language, read on the server (a header is a form label, not a value); terms a run may be built from"),
    "XLSX_HEADER_TERMS_KO": Limit("로트,번호,품번,부품,검사,검사일,일자,수량,개수,합격,불합격,불량,양품,부적합,적합,단위,비고,측정,측정값,항목,값,총,합계,수입,출하,샘플,시료,판정,결과,날짜",
                                     "readable header terms, comma separated (KO)", "DECISION", "user, 2026-11-03: a protected file's header words go masked except the inspection terms of its language, read on the server (a header is a form label, not a value); terms a run may be built from"),
    "XLSX_HEADER_TERMS_JA": Limit("ロット,番号,品番,部品,検査,検査日,日付,数,数量,合格,不合格,不良,良品,単位,備考,測定,測定値,項目,値,合計,判定,結果",
                                     "readable header terms, comma separated (JA)", "DECISION", "user, 2026-11-03: a protected file's header words go masked except the inspection terms of its language, read on the server (a header is a form label, not a value); terms a run may be built from"),
    "XLSX_HEADER_TERMS_ZH": Limit("批次,批号,编号,品号,零件,检验,檢驗,检查,日期,数量,數量,合格,不合格,不良,良品,单位,單位,备注,測量,测量,项目,值,合计,判定,结果",
                                     "readable header terms, comma separated (ZH)", "DECISION", "user, 2026-11-03: a protected file's header words go masked except the inspection terms of its language, read on the server (a header is a form label, not a value); terms a run may be built from"),
    "ALLOWED_TIMEZONES": Limit("Asia/Seoul,America/New_York,America/Chicago,America/Denver,America/Los_Angeles",
                               "IANA zones for due dates (KST = Asia/Seoul)", "DECISION",
                               "user, 2026-11-01: Korea and the US; the US has several zones, so each by its IANA "
                               "name and no ambiguous abbreviations (CST, EST)"),
}


def cast(name: str, raw: str):
    kind = type(LIMITS[name].default)
    try:
        value = kind(raw.strip())
    except ValueError:
        raise HTTPException(422, f"{name} needs a {kind.__name__}") from None
    if name in CHOICES and value not in CHOICES[name]:
        raise HTTPException(422, f"{name} must be one of {', '.join(sorted(CHOICES[name]))}")
    if isinstance(value, int | float) and (value < 0 or (value == 0 and name not in OFF_ALLOWED)):
        raise HTTPException(422, f"{name} must be positive")
    return value


def get(name: str):
    """The effective value: a recorded setting, else QO_<NAME> from the environment, else the default."""
    if name in OVERRIDES:
        return OVERRIDES[name]
    raw = os.environ.get(f"QO_{name}")
    return LIMITS[name].default if raw is None or raw.strip() == "" else cast(name, raw)


def max_input_tokens() -> int:
    """DERIVED: the smaller of what fits (context minus the output reserve) and what the cost cap pays for."""
    fits = get("MODEL_CONTEXT_TOKENS") - get("MODEL_MAX_OUTPUT_TOKENS")  # the context holds the answer too
    cost = get("MAX_COST_PER_MODEL_CALL_USD")
    pays = int(cost / get("MODEL_PRICE_INPUT_PER_M_USD") * 1_000_000) if cost > 0 else fits
    return max(1, min(fits, pays))


def model_timeout_s() -> int:
    """DERIVED: a call that writes the most it may (MODEL_MAX_OUTPUT_TOKENS) at the slowest measured speed ends."""
    return -(-get("MODEL_MAX_OUTPUT_TOKENS") // get("MODEL_OUTPUT_TOKENS_PER_S"))


def estimate_tokens(text: str) -> int:
    return int(len(text.encode("utf-8")) / get("BYTES_PER_TOKEN")) + 1


def where(name: str) -> str:
    return "SETTING" if name in OVERRIDES else "ENV" if os.environ.get(f"QO_{name}") not in (None, "") \
        else "DEFAULT"


def table() -> list[dict]:
    return [{"name": k, "value": get(k), "default": v.default, "unit": v.unit, "basis": v.basis,
             "source": v.source, "set_by": where(k), "restart_required": k in RESTART} for k, v in LIMITS.items()]


def load(sessions: sessionmaker) -> None:
    """Replay the recorded settings into this process (latest per name wins)."""
    from app.db import LimitSetting

    OVERRIDES.clear()
    with sessions() as session:
        for row in session.scalars(select(LimitSetting).order_by(LimitSetting.id)):
            if row.name in LIMITS:
                OVERRIDES[row.name] = cast(row.name, row.value)


class SettingIn(BaseModel):
    value: str
    reason: FreeText  # why the AI operations department changed it


def make_limits_router(sessions: sessionmaker, current_user) -> APIRouter:
    from app.db import LimitSetting
    from app.workflow import Actor, now

    router = APIRouter()
    Who = Annotated[Actor, Depends(current_user)]

    @router.get("/limits")
    def read(actor: Who) -> dict:
        with sessions() as session:
            history = [{"name": r.name, "value": r.value, "reason": r.reason, "actor_id": r.actor_id,
                        "at": r.created_at} for r in session.scalars(select(LimitSetting).order_by(LimitSetting.id))]
        return {"limits": table(), "history": history, "admin_role": ADMIN_ROLE}

    @router.post("/limits/{name}", status_code=201)
    def change(name: str, body: SettingIn, actor: Who) -> dict:
        if actor.role != ADMIN_ROLE:
            raise HTTPException(403, f"only {ADMIN_ROLE} (AI 운영 담당) changes operating limits")
        if name not in LIMITS:
            raise HTTPException(404, "Unknown limit")
        value = cast(name, body.value)
        if name == "ALLOWED_TIMEZONES":
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            try:
                [ZoneInfo(z) for z in str(value).split(",")]
            except (ZoneInfoNotFoundError, ValueError):
                raise HTTPException(422, "every zone must be an IANA name") from None
        with sessions.begin() as session:
            session.add(LimitSetting(name=name, value=str(value), reason=body.reason, actor_id=actor.id,
                                     created_at=now()))
        OVERRIDES[name] = value
        return {"limit": next(x for x in table() if x["name"] == name)}

    return router
