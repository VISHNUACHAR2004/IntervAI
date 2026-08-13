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
from dotenv import load_dotenv;
import os
import json
import logging
from typing import List, Optional, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
from google import genai

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("intervai")

app = FastAPI(title="INTERVAI API")

# In dev, allow the Vite/CRA dev server. Lock this down before deploying.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Free tier: get a key at https://aistudio.google.com/apikey (no credit card)
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

ROLES = Literal["Software Engineer", "ML Engineer", "Data Scientist", "Java Developer"]
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


class EvaluateRequest(BaseModel):
    role: ROLES
    difficulty: DIFFICULTY
    num_questions: int
    history: List[QAPair]          # all Q&A pairs BEFORE this one
    current_question: str
    current_answer: str


class EvaluateResponse(BaseModel):
    score: int
    technical_accuracy: int
    clarity: int
    completeness: int
    feedback: str
    missing_points: List[str]
    next_question: Optional[str] = None   # None if interview is over
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

def call_llm_json(system: str, user: str, retries: int = 1) -> dict:
    """Call the LLM and force a JSON object back. Retries once on parse failure."""
    last_err = None
    for attempt in range(retries + 1):
        resp = client.models.generate_content(
            model=MODEL,
            contents=user,
            config={
                "system_instruction": system,
                "response_mime_type": "application/json",  # forces valid JSON, unlike Claude's prompt-only approach
            },
        )
        raw = resp.text.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            last_err = e
            logger.warning(f"LLM returned invalid JSON (attempt {attempt+1}): {raw[:300]}")
    raise HTTPException(status_code=502, detail=f"LLM did not return valid JSON: {last_err}")


# ---------- Endpoints ----------

@app.post("/start-interview", response_model=StartInterviewResponse)
def start_interview(req: StartInterviewRequest):
    system = (
        "You are a senior technical interviewer conducting a real interview. "
        "Respond with ONLY a JSON object, no markdown, no preamble. "
        'Schema: {"question": string}'
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
    return StartInterviewResponse(question=data["question"], question_number=1)


@app.post("/evaluate", response_model=EvaluateResponse)
def evaluate(req: EvaluateRequest):
    q_number = len(req.history) + 1
    is_last = q_number >= req.num_questions

    history_text = "\n\n".join(
        f"Q{i+1}: {qa.question}\nA{i+1}: {qa.answer}" for i, qa in enumerate(req.history)
    ) or "(none yet)"

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
        '  "next_question": string or null\n'
        "}\n\n"
        "Rules for next_question:\n"
        "- If the answer was strong, ask a harder or deeper follow-up that "
        "builds on something specific the candidate said.\n"
        "- If the answer was weak or vague, ask a probing question that "
        "pushes for the missing piece rather than moving to an unrelated topic.\n"
        "- If the answer was incomplete, ask a clarification question.\n"
        "- If this was the LAST question of the interview, set next_question "
        "to null."
    )
    user = (
        f"Role: {req.role}\n"
        f"Difficulty: {req.difficulty}\n"
        f"Question {q_number} of {req.num_questions} (this is "
        f"{'the FINAL question' if is_last else 'not the final question'}).\n\n"
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
            is_final=is_last,
        )
    except (KeyError, ValidationError) as e:
        raise HTTPException(status_code=502, detail=f"Malformed LLM evaluation: {e}")
    return result


@app.post("/final-report", response_model=FinalReport)
def final_report(req: FinalReportRequest):
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
