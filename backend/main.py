"""
INTERVAI backend — v1

Design decisions (read this before you change anything):
- STATELESS. No DB, no session store. The frontend owns the conversation
  history and sends it back on every request. This is correct for v1.
  Don't add Redis/Postgres until this loop actually works end to end.
- ONE LLM call per turn does both evaluation of the previous answer AND
  generation of the next question. Do not split this into two calls —
  that doubles cost and latency for no benefit.
- The LLM is forced to return JSON. We validate it with pydantic. If it
  fails to parse, we retry once, then fail loudly (500) instead of
  silently returning garbage to the user.
"""

import os
import json
import time
import logging
from typing import List, Optional, Literal
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
from google import genai
from google.genai.errors import ServerError, ClientError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

load_dotenv()
print("DEBUG — GEMINI_MODEL from env:", os.environ.get("GEMINI_MODEL"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("intervai")

app = FastAPI(title="INTERVAI API")

# Rate limiting: protects your Gemini quota from accidental hammering
# (double-clicks, buggy retries, someone leaving a tab open with a script).
# This is NOT abuse protection against a determined attacker — it's a
# sanity limit for a single-user dev app. Tune the numbers if they're too
# tight/loose for how you actually use it.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# In dev, allow the Vite/CRA dev server. Lock this down before deploying.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000","https://intervai-kk85.onrender.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Free tier: get a key at https://aistudio.google.com/apikey (no credit card)
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

ROLES = Literal[
    "Software Engineer", "ML Engineer", "Data Analyst", "Data Scientist",
    "Java Developer", "Frontend Engineer", "Backend Engineer", "Fullstack Engineer",
    "DevOps Engineer", "QA Engineer", "Product Manager", "Business Analyst",
    "Project Manager", "System Administrator", "Network Engineer",
    "Database Administrator", "Mobile App Developer", "Cloud Solutions Architect",
    "Data Engineer", "Embedded Systems Engineer", "Solutions Architect",
    "Business Development Executive",
]
DIFFICULTY = Literal["Easy", "Medium", "Hard"]


# ---------- Schemas ----------

class QAPair(BaseModel):
    question: str
    answer: str


class StartInterviewRequest(BaseModel):
    role: ROLES
    difficulty: DIFFICULTY
    num_questions: int = Field(default=5, ge=1, le=15)


class StartInterviewResponse(BaseModel):
    question: str
    question_number: int = 1
    requires_code: bool = False   # true if a real answer needs actual code, not prose


class EvaluateRequest(BaseModel):
    role: ROLES
    difficulty: DIFFICULTY
    num_questions: int
    history: List[QAPair]          # all Q&A pairs BEFORE this one
    current_question: str
    current_answer: str
    is_code_answer: bool = False   # true if the CURRENT question required code (server-determined, not self-reported)
    timed_out: bool = False        # true if the answer was auto-submitted when the timer hit zero


class EvaluateResponse(BaseModel):
    score: int
    technical_accuracy: int
    clarity: int
    completeness: int
    feedback: str
    missing_points: List[str]
    next_question: Optional[str] = None   # None if interview is over
    next_question_requires_code: bool = False
    is_final: bool


class FinalReportRequest(BaseModel):
    role: ROLES
    difficulty: DIFFICULTY
    history: List[QAPair]
    per_question_scores: List[int]


class FinalReport(BaseModel):
    overall_score: int
    technical_knowledge_pct: int
    communication_pct: int
    completeness_pct: int
    problem_solving_pct: int
    strengths: List[str]
    weaknesses: List[str]
    recommended_topics: List[str]


# ---------- Helpers ----------

def call_llm_json(system: str, user: str, retries: int = 2) -> dict:
    """Call the LLM and force a JSON object back.
    Retries on: (a) transient 503/server-overload errors, with backoff,
    and (b) malformed JSON. A 429 quota/rate-limit error is NOT retried —
    if it's a daily quota cap, retrying in a few seconds is pointless and
    just wastes time before failing anyway. Instead it fails fast with a
    clear message the frontend can show directly to the user.
    """
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=user,
                config={
                    "system_instruction": system,
                    "response_mime_type": "application/json",
                },
            )
        except ClientError as e:
            if getattr(e, "status_code", None) == 429 or "RESOURCE_EXHAUSTED" in str(e):
                logger.error(f"Gemini quota/rate limit hit: {e}")
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "The interview AI has hit its usage limit for now "
                        "(free tier quota). Please try again later, or switch "
                        "to a different model/API key."
                    ),
                )
            raise HTTPException(status_code=502, detail=f"LLM request failed: {e}")
        except ServerError as e:
            last_err = e
            wait = 1.5 * (attempt + 1)
            logger.warning(f"Gemini server error (attempt {attempt+1}): {e}. Retrying in {wait}s.")
            time.sleep(wait)
            continue

        raw = resp.text.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            last_err = e
            logger.warning(f"LLM returned invalid JSON (attempt {attempt+1}): {raw[:300]}")

    raise HTTPException(
        status_code=503,
        detail="The interview AI is temporarily unavailable. Please try again in a moment.",
    )


# ---------- Endpoints ----------

@app.post("/start-interview", response_model=StartInterviewResponse)
@limiter.limit("10/minute")
def start_interview(request: Request, req: StartInterviewRequest):
    system = (
        "You are a senior technical interviewer conducting a real interview. "
        "Respond with ONLY a JSON object, no markdown, no preamble. "
        "Schema:\n"
        "{\n"
        '  "question": string,\n'
        '  "requires_code": bool\n'
        "}\n\n"
        "requires_code is true ONLY if genuinely answering this question well "
        "requires writing actual code (e.g. implementing a function or "
        "algorithm), not just describing an approach verbally. For "
        "non-engineering roles (Product Manager, Business Analyst, Project "
        "Manager, System Administrator, Network Engineer, Business "
        "Development Executive, etc.) this should almost always be false — "
        "do not ask coding questions for roles that don't call for them."
    )
    user = (
        f"Role: {req.role}\n"
        f"Difficulty: {req.difficulty}\n"
        f"This is question 1 of {req.num_questions}.\n"
        "Ask a single, specific, well-scoped interview question appropriate "
        "for this role and difficulty. Do not ask something generic like "
        "'tell me about yourself'."
    )
    data = call_llm_json(system, user)
    if "question" not in data:
        raise HTTPException(status_code=502, detail="LLM response missing 'question'")
    return StartInterviewResponse(
        question=data["question"],
        question_number=1,
        requires_code=bool(data.get("requires_code", False)),
    )


@app.post("/evaluate", response_model=EvaluateResponse)
@limiter.limit("15/minute")
def evaluate(request: Request, req: EvaluateRequest):
    q_number = len(req.history) + 1
    is_last = q_number >= req.num_questions

    history_text = "\n\n".join(
        f"Q{i+1}: {qa.question}\nA{i+1}: {qa.answer}" for i, qa in enumerate(req.history)
    ) or "(none yet)"

    if req.is_code_answer:
        eval_criteria = (
            "The candidate submitted CODE, not prose. Evaluate it like a senior "
            "engineer doing code review:\n"
            "- technical_accuracy: does the code actually work / solve the problem correctly?\n"
            "- clarity: is the code readable (naming, structure), not the prose fluency?\n"
            "- completeness: are edge cases, error handling, and complexity considered?\n"
            "missing_points should list specific missing edge cases, bugs, or "
            "inefficiencies (e.g. 'doesn't handle empty input', 'O(n^2) when O(n) is possible')."
        )
    else:
        eval_criteria = (
            "The candidate submitted a spoken/written explanation. Evaluate technical "
            "accuracy, clarity of communication, and completeness of the explanation."
        )

    system = (
        "You are a senior technical interviewer conducting a live, adaptive "
        "interview. You evaluate the candidate's last answer AND decide the "
        "next question in the SAME response. Respond with ONLY a JSON object, "
        "no markdown, no preamble. Schema:\n"
        "{\n"
        '  "score": int (0-10),\n'
        '  "technical_accuracy": int (0-10),\n'
        '  "clarity": int (0-10),\n'
        '  "completeness": int (0-10),\n'
        '  "feedback": string (2-3 sentences, specific, direct),\n'
        '  "missing_points": [string],\n'
        '  "next_question": string or null,\n'
        '  "next_question_requires_code": bool\n'
        "}\n\n"
        f"{eval_criteria}\n\n"
        "Rules for next_question:\n"
        "- If the answer was strong, ask a harder or deeper follow-up that "
        "builds on something specific the candidate said.\n"
        "- If the answer was weak or vague, ask a probing question that "
        "pushes for the missing piece rather than moving to an unrelated topic.\n"
        "- If the answer was incomplete, ask a clarification question.\n"
        "- If this was the LAST question of the interview, set next_question "
        "to null and next_question_requires_code to false.\n\n"
        "next_question_requires_code is true ONLY if genuinely answering the "
        "next question well requires writing actual code, not just describing "
        "an approach verbally. Be honest about this — it directly affects how "
        "much time the candidate is given, so don't mark it true unless code "
        "is genuinely the right way to answer."
    )
    timeout_note = (
        "\nNOTE: The candidate ran out of time on this question — this answer "
        "was auto-submitted when the clock hit zero, not submitted voluntarily. "
        "Evaluate whatever content is present fairly on its own merits, but do "
        "not treat an incomplete/short answer here the same as a candidate who "
        "had unlimited time and still gave a weak answer. Mention the time "
        "pressure in feedback if relevant, and keep missing_points focused on "
        "what was actually said rather than assuming the worst about what "
        "wasn't reached.\n"
        if req.timed_out else ""
    )
    user = (
        f"Role: {req.role}\n"
        f"Difficulty: {req.difficulty}\n"
        f"Question {q_number} of {req.num_questions} (this is "
        f"{'the FINAL question' if is_last else 'not the final question'}).\n"
        f"{timeout_note}\n"
        f"Previous Q&A history:\n{history_text}\n\n"
        f"Current question: {req.current_question}\n"
        f"Candidate's answer: {req.current_answer}\n\n"
        "Evaluate the current answer and produce the next_question per the rules above."
    )

    data = call_llm_json(system, user)
    try:
        result = EvaluateResponse(
            score=data["score"],
            technical_accuracy=data["technical_accuracy"],
            clarity=data["clarity"],
            completeness=data["completeness"],
            feedback=data["feedback"],
            missing_points=data.get("missing_points", []),
            next_question=None if is_last else data.get("next_question"),
            next_question_requires_code=False if is_last else bool(data.get("next_question_requires_code", False)),
            is_final=is_last,
        )
    except (KeyError, ValidationError) as e:
        raise HTTPException(status_code=502, detail=f"Malformed LLM evaluation: {e}")
    return result


@app.post("/final-report", response_model=FinalReport)
@limiter.limit("5/minute")
def final_report(request: Request, req: FinalReportRequest):
    history_text = "\n\n".join(
        f"Q{i+1}: {qa.question}\nA{i+1}: {qa.answer}" for i, qa in enumerate(req.history)
    )
    system = (
        "You are a senior technical interviewer writing a final performance "
        "report for a candidate. Respond with ONLY a JSON object, no markdown. "
        "Schema:\n"
        "{\n"
        '  "overall_score": int (0-100),\n'
        '  "technical_knowledge_pct": int (0-100),\n'
        '  "communication_pct": int (0-100),\n'
        '  "completeness_pct": int (0-100),\n'
        '  "problem_solving_pct": int (0-100),\n'
        '  "strengths": [string] (2-4 items),\n'
        '  "weaknesses": [string] (2-4 items),\n'
        '  "recommended_topics": [string] (3-5 items)\n'
        "}"
    )
    user = (
        f"Role: {req.role}\nDifficulty: {req.difficulty}\n\n"
        f"Full interview transcript:\n{history_text}\n\n"
        f"Per-question scores (0-10 each): {req.per_question_scores}\n\n"
        "Write the final report."
    )
    data = call_llm_json(system, user)
    try:
        return FinalReport(**data)
    except ValidationError as e:
        raise HTTPException(status_code=502, detail=f"Malformed LLM report: {e}")


@app.get("/health")
def health():
    return {"status": "ok"}