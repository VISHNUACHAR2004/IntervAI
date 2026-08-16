import { useState, useRef } from "react";
import html2canvas from "html2canvas-pro";
import jsPDF from "jspdf";

/**
 * INTERVAI frontend — v1 (styled)
 *
 * Design: formal interview room, not a SaaS dashboard. Warm near-black,
 * brass accent, serif display type, monospace for anything numeric
 * (scores, question count) — styled like a case file, not a dashboard
 * widget. See tailwind.config.js for the token system.
 *
 * Functional design decisions unchanged from before:
 * - STATELESS. Frontend owns history, backend takes it fresh each call.
 * - No routing library, no auth, no DB. Still v1 scope.
 */

const API_BASE = "http://localhost:8000";
const ROLES = ["Software Engineer", "ML Engineer", "Data Analyst", "Data Scientist",
    "Java Developer", "Frontend Engineer", "Backend Engineer", "Fullstack Engineer",
    "DevOps Engineer", "QA Engineer", "Product Manager", "Business Analyst",
    "Project Manager", "System Administrator", "Network Engineer",
    "Database Administrator", "Mobile App Developer", "Cloud Solutions Architect",
    "Data Engineer", "Embedded Systems Engineer", "Solutions Architect",
    "Business Development Executive"];
const DIFFICULTIES = ["Easy", "Medium", "Hard"];
const QUESTION_COUNTS = [5, 10, 15];

export default function App() {
  const [screen, setScreen] = useState("setup");
  const [role, setRole] = useState(ROLES[0]);
  const [difficulty, setDifficulty] = useState("Medium");
  const [numQuestions, setNumQuestions] = useState(5);

  const [history, setHistory] = useState([]);
  const [perQuestionScores, setPerQuestionScores] = useState([]);
  const [currentQuestion, setCurrentQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [isCodeAnswer, setIsCodeAnswer] = useState(false);
  const [lastFeedback, setLastFeedback] = useState(null);

  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const questionNumber = history.length + 1;

  async function startInterview() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/start-interview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role, difficulty, num_questions: numQuestions }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Failed to start interview (${res.status})`);
      }
      const data = await res.json();
      setCurrentQuestion(data.question);
      setHistory([]);
      setPerQuestionScores([]);
      setLastFeedback(null);
      setScreen("interview");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function submitAnswer() {
    if (!answer.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          role,
          difficulty,
          num_questions: numQuestions,
          history,
          current_question: currentQuestion,
          current_answer: answer,
          is_code_answer: isCodeAnswer,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Failed to evaluate answer (${res.status})`);
      }
      const data = await res.json();

      const newHistory = [...history, { question: currentQuestion, answer }];
      const newScores = [...perQuestionScores, data.score];
      setHistory(newHistory);
      setPerQuestionScores(newScores);
      setLastFeedback(data);
      setAnswer("");
      setIsCodeAnswer(false);

      if (data.is_final || !data.next_question) {
        await fetchFinalReport(newHistory, newScores);
      } else {
        setCurrentQuestion(data.next_question);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function fetchFinalReport(finalHistory, finalScores) {
    try {
      const res = await fetch(`${API_BASE}/final-report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          role,
          difficulty,
          history: finalHistory,
          per_question_scores: finalScores,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Failed to generate report (${res.status})`);
      }
      const data = await res.json();
      setReport(data);
      setScreen("report");
    } catch (e) {
      setError(e.message);
    }
  }

  function resetToSetup() {
    setScreen("setup");
    setReport(null);
    setHistory([]);
    setPerQuestionScores([]);
    setLastFeedback(null);
    setAnswer("");
    setError(null);
  }

  return (
    <div className="min-h-screen bg-ink text-parchment font-body flex items-start justify-center p-6">
      <div className="w-full max-w-2xl">
        <Letterhead />

        {error && (
          <div className="mb-6 px-4 py-3 border border-rust/40 bg-rust/10 text-rust text-sm font-mono">
            {error}
          </div>
        )}

        {screen === "setup" && (
          <SetupScreen
            role={role} setRole={setRole}
            difficulty={difficulty} setDifficulty={setDifficulty}
            numQuestions={numQuestions} setNumQuestions={setNumQuestions}
            loading={loading}
            onStart={startInterview}
          />
        )}

        {screen === "interview" && (
          <InterviewScreen
            role={role}
            questionNumber={Math.min(questionNumber, numQuestions)}
            numQuestions={numQuestions}
            question={currentQuestion}
            answer={answer}
            setAnswer={setAnswer}
            isCodeAnswer={isCodeAnswer}
            setIsCodeAnswer={setIsCodeAnswer}
            loading={loading}
            lastFeedback={lastFeedback}
            onSubmit={submitAnswer}
          />
        )}

        {screen === "report" && report && (
          <ReportScreen report={report} onRestart={resetToSetup} />
        )}
      </div>
    </div>
  );
}

function Letterhead() {
  return (
    <div className="mb-10">
      <div className="flex items-baseline justify-between">
        <h1 className="font-display text-6xl tracking-tight text-parchment">
          INTERV<span className="text-brass">AI</span>
        </h1>
        <span className="font-mono text-[28px] tracking-[0.2em] text-muted uppercase">
          Candidate Assessment
        </span>
      </div>
      <div className="mt-3 h-px bg-brass/50" />
      <div className="mt-1 h-px bg-brass/50" />
    </div>
  );
}

function SetupScreen({ role, setRole, difficulty, setDifficulty, numQuestions, setNumQuestions, loading, onStart }) {
  return (
    <div className="space-y-8">
      <div>
        <p className="font-mono text-xl tracking-widest text-muted uppercase mb-3">Position applied for</p>
        <div className="grid grid-cols-4 gap-5">
          {ROLES.map((r) => (
            <button
              key={r}
              onClick={() => setRole(r)}
              className={`px-4 py-3 border text-left text-sm transition-colors ${
                role === r
                  ? "border-brass bg-brass/10 text-parchment"
                  : "border-border bg-surface text-muted hover:border-brass/40 hover:text-parchment"
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="font-mono text-xl tracking-widest text-muted uppercase mb-3">Difficulty</p>
        <div className="flex gap-2">
          {DIFFICULTIES.map((d) => (
            <button
              key={d}
              onClick={() => setDifficulty(d)}
              className={`px-4 py-2 border text-xl transition-colors ${
                difficulty === d
                  ? "border-brass bg-brass/10 text-parchment"
                  : "border-border bg-surface text-muted hover:border-brass/40 hover:text-parchment"
              }`}
            >
              {d}
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="font-mono text-xl tracking-widest text-muted uppercase mb-3">Number of questions</p>
        <div className="flex gap-2">
          {QUESTION_COUNTS.map((n) => (
            <button
              key={n}
              onClick={() => setNumQuestions(n)}
              className={`w-12 h-10 border text-sm font-mono transition-colors ${
                numQuestions === n
                  ? "border-brass bg-brass/10 text-parchment"
                  : "border-border bg-surface text-muted hover:border-brass/40 hover:text-parchment"
              }`}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      <button
        onClick={onStart}
        disabled={loading}
        className="w-full py-3 border border-brass bg-brass/10 hover:bg-brass/20 disabled:opacity-40 text-parchment font-display text-lg tracking-wide transition-colors"
      >
        {loading ? "Preparing interview…" : "Begin Interview"}
      </button>
    </div>
  );
}

function InterviewScreen({ role, questionNumber, numQuestions, question, answer, setAnswer, isCodeAnswer, setIsCodeAnswer, loading, lastFeedback, onSubmit }) {
  const padded = String(questionNumber).padStart(2, "0");
  const total = String(numQuestions).padStart(2, "0");

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <span className="font-mono text-xs tracking-widest text-muted uppercase">{role}</span>
        <span className="font-mono text-xs border border-brass/50 text-brass px-2 py-1 tracking-widest">
          FILE {padded}/{total}
        </span>
      </div>

      <div className="border border-border bg-surface p-5">
        <p className="font-mono text-[31px] tracking-widest text-brass uppercase mb-3">Interviewer asks</p>
        <p className="font-display text-xl leading-snug text-parchment">{question}</p>
      </div>

      {lastFeedback && (
        <div className="border-l-2 border-brass/40 pl-4 py-1 text-sm text-muted">
          <span className="font-mono text-parchment">{lastFeedback.score}/10</span> — {lastFeedback.feedback}
        </div>
      )}

      <label className="flex items-center gap-2 cursor-pointer w-fit">
        <input
          type="checkbox"
          checked={isCodeAnswer}
          onChange={(e) => setIsCodeAnswer(e.target.checked)}
          className="accent-brass w-4 h-4"
        />
        <span className="font-mono text-xs tracking-widest text-muted uppercase">
          This is a code answer
        </span>
      </label>

      <textarea
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        rows={8}
        placeholder={isCodeAnswer ? "// Paste or write your code here…" : "Compose your response…"}
        spellCheck={!isCodeAnswer}
        className={`w-full p-4 bg-surface border border-border text-parchment placeholder-muted/60 focus:outline-none focus:border-brass resize-none ${
          isCodeAnswer ? "font-mono text-sm" : "font-body"
        }`}
      />

      <button
        onClick={onSubmit}
        disabled={loading || !answer.trim()}
        className="w-full py-3 border border-brass bg-brass/10 hover:bg-brass/20 disabled:opacity-40 text-parchment font-display text-lg tracking-wide transition-colors"
      >
        {loading ? "Evaluating…" : "Submit Answer"}
      </button>
    </div>
  );
}

function ReportScreen({ report, onRestart }) {
  const reportRef = useRef(null);
  const [exporting, setExporting] = useState(false);

  async function captureCanvas() {
    return html2canvas(reportRef.current, {
      scale: 2,
      backgroundColor: "#15130F",
    });
  }

  async function downloadJPG() {
    setExporting(true);
    try {
      const canvas = await captureCanvas();
      const link = document.createElement("a");
      link.download = "intervai-report.jpg";
      link.href = canvas.toDataURL("image/jpeg", 0.95);
      link.click();
    } catch (e) {
      console.error("JPG export failed:", e);
    } finally {
      setExporting(false);
    }
  }

  async function downloadPDF() {
    setExporting(true);
    try {
      const canvas = await captureCanvas();
      const imgData = canvas.toDataURL("image/jpeg", 0.95);
      const pdf = new jsPDF({
        orientation: canvas.width > canvas.height ? "landscape" : "portrait",
        unit: "px",
        format: [canvas.width, canvas.height],
      });
      pdf.addImage(imgData, "JPEG", 0, 0, canvas.width, canvas.height);
      pdf.save("intervai-report.pdf");
    } catch (e) {
      console.error("PDF export failed:", e);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="space-y-8">
      <div ref={reportRef} className="bg-ink space-y-8 p-2">
        <div className="text-center border-b border-brass/30 pb-6">
          <p className="font-mono text-xs tracking-widest text-muted uppercase mb-2">Assessment Complete</p>
          <p className="font-display text-6xl text-parchment">
            {report.overall_score}<span className="text-2xl text-muted">/100</span>
          </p>
        </div>

        <div className="grid grid-cols-2 grid-rows-2 gap-px text-xl bg-border border border-border text-parchment">
          <Metric label="Technical Knowledge" value={report.technical_knowledge_pct} />
          <Metric label="Communication" value={report.communication_pct} />
          <Metric label="Completeness" value={report.completeness_pct} />
          <Metric label="Problem Solving" value={report.problem_solving_pct} />
        </div>

        <div className="grid grid-cols-1 gap-6">
          <div>
            <p className="font-mono text-xl tracking-widest text-olive uppercase mb-2">Strengths</p>
            <ul className="space-y-1.5 text-xl text-parchment/90">
              {report.strengths.map((s, i) => (
                <li key={i} className="flex gap-2"><span className="text-olive">+</span>{s}</li>
              ))}
            </ul>
          </div>

          <div>
            <p className="font-mono text-xl tracking-widest text-rust uppercase mb-2">Weaknesses</p>
            <ul className="space-y-1.5 text-xl text-parchment/90">
              {report.weaknesses.map((w, i) => (
                <li key={i} className="flex gap-2"><span className="text-rust">−</span>{w}</li>
              ))}
            </ul>
          </div>

          <div>
            <p className="font-mono text-xl tracking-widest text-brass uppercase mb-2">Recommended Study Topics</p>
            <ol className="space-y-1.5 text-xl text-parchment/90">
              {report.recommended_topics.map((t, i) => (
                <li key={i} className="flex gap-3">
                  <span className="font-mono text-brass">{String(i + 1).padStart(2, "0")}</span>{t}
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <button
          onClick={downloadPDF}
          disabled={exporting}
          className="py-3 border border-brass/60 hover:bg-brass/10 disabled:opacity-40 text-parchment font-mono text-sm tracking-widest uppercase transition-colors"
        >
          {exporting ? "Working…" : "Download PDF"}
        </button>
        <button
          onClick={downloadJPG}
          disabled={exporting}
          className="py-3 border border-brass/60 hover:bg-brass/10 disabled:opacity-40 text-parchment font-mono text-sm tracking-widest uppercase transition-colors"
        >
          {exporting ? "Working…" : "Download JPG"}
        </button>
      </div>

      <button
        onClick={onRestart}
        className="w-full py-3 border border-brass bg-brass/10 hover:bg-brass/20 text-parchment font-display text-lg tracking-wide transition-colors"
      >
        Take Another Interview
      </button>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="bg-surface p-4">
      <p className="font-mono text-[30px] tracking-widest text-muted uppercase mb-1">{label}</p>
      <p className="font-display text-5xl text-parchment">{value}<span className="text-sm text-muted">%</span></p>
    </div>
  );
}