# INTERVAI — AI Mock Interview Platform

INTERVAI is a web app that runs a live, adaptive mock interview. It asks a question, listens to your answer, scores it, and then decides the next question based on how well you did — just like a real interviewer would. At the end, it gives you a full performance report you can download or look back at later.

---

## Why this project exists

Most "practice interview" tools just show you a fixed list of questions and a text box. That's not how a real interview works. A real interviewer listens to your answer and adjusts — harder questions if you're doing well, clarifying questions if you're vague, follow-ups that build on what you actually said.

INTERVAI tries to recreate that. The interviewer is an AI model that evaluates each answer and picks the next question live, during the interview — not from a pre-written list.

---

## Technologies used, and why

### Backend — FastAPI (Python)
FastAPI was chosen because it's fast to build with, has built-in request validation (so bad data gets rejected automatically before it causes problems), and works well with Python's AI/ML libraries. The core interview flow is intentionally simple and stateless — it has no database of its own for that part. It receives the interview history from the frontend on every request and forwards it to the AI model — nothing about an in-progress interview is stored on the server. Optional user accounts (see below) are the one part of the backend that does use a database.

### Frontend — React + Vite
React handles the interactive parts (the interview flow, timer, forms). Vite is the build tool — it's fast during development and produces an optimized build for deployment.

### Styling — Tailwind CSS v4
Used for all the visual design. The whole app follows one visual theme: a "formal interview room" look — dark background, brass/gold accents, serif headings — instead of a generic dashboard look.

### AI Model — Google Gemini 3.1 Flash Lite
See the dedicated section below — this needed its own explanation.

### Accounts & database — Neon (Postgres) + JWT
User accounts are optional — the app works fully without ever creating one. When someone does register, their password is hashed (never stored as plain text) and a signed login token (JWT) is issued so the frontend can prove who's asking on future requests. The database itself is hosted on **Neon**, a free managed Postgres provider chosen specifically because its free tier doesn't expire or get deleted after a fixed number of days, unlike some competing free database offers.

### Other libraries
| Library | What it's used for |
|---|---|
| `slowapi` | Rate limiting on the backend, so one bug or accidental double-click can't burn through the AI usage quota |
| `python-dotenv` | Loads secret keys (like the API key) from a `.env` file instead of hardcoding them in code |
| `recharts` | Draws the score-over-time chart on the History screen |
| `jsPDF` | Builds the downloadable PDF report by drawing text and shapes directly — not a screenshot, which makes it reliable across different browsers and devices |
| `html2canvas-pro` | Used for the JPG image export, by taking a screenshot of the report on screen |
| `sqlmodel` | Defines the database tables (users, saved interviews) and talks to Postgres |
| `psycopg2-binary` | The actual driver that lets Python connect to a Postgres database |
| `bcrypt` | Hashes passwords before they're stored, so even a database leak wouldn't expose anyone's actual password |
| `PyJWT` | Creates and checks the login tokens used to recognize a signed-in user on each request |

---

## Why Gemini 3.1 Flash Lite, and not another AI model

A few reasons this model was chosen over the alternatives:

1. **Free to use for development.** Gemini has a genuinely free tier (no credit card required to start), which matters a lot for a project like this that's still being built and tested. Other well-known models are also excellent, but mostly require payment from the first request.
2. **Reliable structured output.** The app needs the AI to always reply in a specific JSON format (a score, feedback, the next question, and so on) so the code can read it automatically. Gemini has a built-in setting that forces the response to be valid JSON, which made this much more dependable than trying to just ask nicely in the prompt.
3. **Good enough quality for this task.** Evaluating an interview answer and picking a sensible follow-up question doesn't need the absolute smartest model available — a lighter, faster model does the job well and keeps response times quick.

**Trade-off to be honest about:** the free tier has a daily request limit. This is a real constraint of building on a free plan, not a flaw in the app itself — see the Limitations section below.

---

## How to run this locally

You'll need Python 3.11+, Node.js, and a free Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).

### 1. Backend setup

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

pip install -r requirements.txt
```

Create a file named `.env` inside the `backend` folder with this content:

```
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-3.1-flash-lite
DATABASE_URL=your_neon_connection_string
JWT_SECRET=any_long_random_string
```

`DATABASE_URL` and `JWT_SECRET` are optional. If you leave them out, the app runs exactly as before — the interview flow works fully, only the sign-in/account features are disabled (guest mode with local history keeps working either way).

Then start the backend:

```bash
uvicorn main:app --reload --port 8000
```

The backend is now running at `http://localhost:8000`.

### 2. Frontend setup

```bash
cd frontend
npm install
npm run dev
```

The app will open at `http://localhost:5173`. It automatically talks to the backend at `localhost:8000` when running locally — no manual configuration needed.

---

## How it works, step by step

This section explains what actually happens when someone uses the app, in order.

### 1. Setting up the interview
The user picks a **role** (e.g. Software Engineer), a **difficulty** (Easy/Medium/Hard), and a **number of questions**. Nothing is sent to the server yet — this is just choosing settings on screen.

### 2. Starting the interview — `/start-interview`
When the user clicks "Begin Interview," the frontend sends the role and difficulty to the backend. The backend asks the AI model to write one interview question appropriate for that role and difficulty, and to say whether answering it properly would require writing actual code. The backend sends this question back to the frontend, and a countdown timer starts — longer for harder difficulties, with extra time added automatically if the question needs code.

### 3. Answering a question
The user types their answer. If the timer runs out before they submit, the app automatically submits whatever they've typed (or a placeholder if the box is empty) and tells the backend the answer was cut short by time, so the AI doesn't unfairly grade it as if the person had unlimited time.

### 4. Evaluating the answer and picking the next question — `/evaluate`
This is the core of the app. In **one single request**, the backend asks the AI to:
- Score the answer (technical accuracy, clarity, completeness)
- Write short feedback
- List anything important that was missing from the answer
- Decide the next question — harder if the answer was strong, a clarifying question if it was weak or incomplete
- Say whether that next question needs code

Doing evaluation and next-question generation in one request (instead of two separate ones) keeps the app fast and uses half as many AI requests.

This repeats until the set number of questions is reached.

### 5. Generating the final report — `/final-report`
Once all questions are answered, the backend sends the full transcript to the AI and asks for an overall score, a breakdown by category (technical knowledge, communication, completeness, problem solving), a list of strengths and weaknesses, and recommended topics to study.

### 6. Saving to history
The finished report is automatically saved in the browser's local storage (not on any server) so the user can look back at past interviews later, without needing to log in. This happens every time, whether or not the user has an account.

### 7. Optional accounts and cross-device sync
Signing in is entirely optional. If a user chooses to register or log in:
- Their password is hashed before being stored — the actual password is never saved anywhere.
- Every interview they complete is *also* saved to the account's database record (in addition to the local browser save above), so it's visible from any device they log into.
- Guest history taken before creating an account stays in that browser's local storage only — it isn't automatically pulled into the new account.

### 8. Downloading the report
The user can download the report as a PDF (built directly from the data, so it always looks correct) or as a JPG image (a screenshot of the report as shown on screen).

---

## Deployment

The app is deployed as two separate pieces:

- **Backend** is deployed on **Render** as a Python web service.
  - Build command: `pip install -r requirements.txt`
  - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
  - The `GEMINI_API_KEY`, `GEMINI_MODEL`, `DATABASE_URL`, and `JWT_SECRET` values are all set directly in Render's Environment settings — they are never committed to the code.

- **Database** is hosted on **Neon** (managed Postgres, free tier). Render was deliberately *not* used for the database — its free Postgres tier auto-deletes after 30 days, which makes it unsuitable for anything meant to hold real user data long-term.

- **Frontend** is deployed on **Netlify**.
  - Base directory: `frontend`
  - Build command: `npm run build`
  - Publish directory: `frontend/dist`

- **CORS**: the backend keeps an explicit list of which frontend URLs are allowed to call it (`localhost` for development, the live Netlify URL for production). This list has to include the *exact* frontend URL — a small difference like a trailing slash will cause requests to be blocked.

- **Environment-aware backend URL**: the frontend automatically uses `localhost:8000` when running locally and the live Render URL when built for production, using Vite's built-in `import.meta.env.DEV` flag. No manual switching needed when moving between local development and the live site.

---

## Known limitations

Being upfront about what this app does *not* do yet:

- **Guest and account history don't merge.** If someone uses the app as a guest and later creates an account, their earlier guest-mode interviews stay in that browser's local storage only — they don't automatically appear in the new account.
- **No password reset flow yet.** If someone forgets their password, there's currently no "forgot password" email/reset process — they'd need a new account.
- **No database migrations tooling.** The database tables are created automatically on first startup, but if the table structure needs to change later, there's no proper migration system (like Alembic) in place yet — just a fresh-create approach that works for now but isn't how a long-lived production app should evolve its schema.
- **Free-tier AI usage limits.** The free Gemini plan allows a limited number of requests per day. Heavy use in a single day can hit that limit, and the app will show a clear message when this happens rather than failing silently.
- **Rate limiting is basic.** It stops accidental overuse (like double-clicking a button) but wouldn't stop someone deliberately trying to abuse the app.
- **Mobile layout is responsive.** All sizing scales down for small screens (phones/tablets) using breakpoint-based CSS, and the past-interviews chart, role grid, and header layout have been specifically adjusted to fit narrow screens rather than just shrinking desktop styling.
- **The interviewer isn't perfect.** Like any AI, it can occasionally misjudge an answer or ask a slightly off-target follow-up question. It's a practice tool, not a certified assessment.

---

## Future scope

Ideas for what could reasonably be added next:

- **Merge guest history into an account** automatically when someone registers, instead of leaving pre-account interviews stranded in local storage.
- **Password reset via email.**
- **Proper database migrations** (e.g. Alembic) once the data model needs to change in production without losing existing data.
- **Voice-based answers**, using speech-to-text, so the interview feels closer to a real spoken conversation.
- **Multiple AI model support**, letting the app fall back to a different provider automatically if one is unavailable or rate-limited.
- **Deeper code evaluation**, such as actually running submitted code against test cases instead of only having the AI read it.
- **An admin/analytics view**, useful now that there's a real user base to draw from, showing common weak areas across many interviews.
- **Stronger abuse protection**, such as per-account rate limits in addition to the current per-IP limits, if the app is ever opened to the public at scale.