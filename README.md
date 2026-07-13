# Support Tickets Analysis

A structured Python project for AI-driven support ticket triage and account summarization.

## Setup Instructions

1. **Clone the repository:**
   ```bash
   git clone <repo_url>
   cd support-tickets-analysis
   ```

2. **Install dependencies:**
   Ensure you have Python 3.9+ installed. Run the following from a clean virtual environment:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment:**
   Copy `.env.example` to `.env` and add your Groq API key:
   ```bash
   cp .env.example .env
   # Add your key inside .env: GROQ_API_KEY="gsk_..."
   ```

## Sample Runs

### Task 1: Intelligent Ticket Triage Agent
To run the triage pipeline on the mock dataset and generate structured outputs:
```bash
python scripts/run_task1.py
```
Check `examples/task1_outputs.json` for example outputs.

### Task 2: TAM Account Health Summarizer
To run the summarization pipeline for strategic accounts and extract deterministic risks and verbatim quotes:
```bash
python scripts/run_task2.py
```
Check `examples/task2_outputs.json` for example outputs.

### Task 3: Evaluation Harness
To run the comprehensive evaluation suite (LLM-as-a-judge and rule-based scoring gates):
```bash
python scripts/eval_harness.py
```
This will test both tasks systematically and output the results to `eval_report.md`.

### REST API Endpoint
To launch the triage pipeline as a FastAPI REST endpoint:
```bash
python -m uvicorn src.api:app --port 8000
```
You can then POST to `http://127.0.0.1:8000/triage` with `{"raw_text": "ticket content..."}`.

## Design Notes

During the development and testing of the LLM-powered triage and summarization agents, we implemented an evaluation harness to benchmark quality and uncover edge cases. The following findings and system design constraints were identified directly from running the prototype against real mock data.

### Failure Modes & Mitigations

Through our evaluation harness, we identified three critical failure modes and designed explicit detection and mitigation strategies for each:

1. **Cache Key Collisions Silently Serving Wrong Results**
   - **Finding:** We directly encountered a scenario where the evaluation harness's cache key generator did not properly account for per-item context. As a result, every Task 1 test case was erroneously served the cached triage output of the first ticket evaluated (`TKT-10035`). The model wasn't hallucinating; the system was just aggressively reusing stale state.
   - **Detection:** Cache keys must explicitly include the full identifying input, rather than just the function name being cached.
   - **Mitigation:** The cache key hashing function was updated to include the identifying context (`{function_name, ticket_id, prompt_version}`). Furthermore, a sanity check in the harness or logging layer that flags identical outputs across different inputs is recommended.

2. **Urgency Classification Contradicting Model Reasoning**
   - **Finding:** For ticket `TKT-10244`, the model correctly reasoned that the `SESSION_INVALID` error was a "critical issue affecting all users, impacting core functionality"—yet it paradoxically assigned a `P2` urgency tier instead of `P1`. The model successfully parsed the severity but failed to map it to the correct categorical output.
   - **Detection:** We implemented a "Missed P1 Urgency" hard-veto in the evaluation harness that fails the test case outright if a true `P1` ticket is downgraded.
   - **Mitigation:** A keyword-based safety-net rule that force-escalates tickets containing specific critical phrases (e.g., "affecting all users", "production down") regardless of model output. Alternatively, a self-consistency check could be applied, comparing the reasoning text's own severity language against the assigned tier.

3. **Unverified Claims Presented as Settled Fact (Epistemic Safety)**
   - **Finding:** LLM-generated risk summaries have a tendency to present unverified claims (such as those from qualitative TAM notes) as absolute truth without flagging their provenance. We caught this behavior on account `ACC-8113`, where subjective negative sentiment and usage decline claims were presented as factual certainties.
   - **Detection:** Caught by our "Epistemic Safety Veto" logic within the LLM-as-a-judge harness.
   - **Mitigation:** Prompting the summarization model to explicitly distinguish ticket-backed facts from reported, unverified claims (e.g., forcing phrases like "TAM notes indicate..."). It is critical that the evaluation harness continually checks for this hedging on every run, rather than just relying on occasional spot-checks.

### Latency vs. Quality

We explicitly set the model temperature to `0.0` in an attempt to guarantee reproducible, deterministic outputs. However, we found that even at `temp=0`, free-text generation is not byte-identical across calls due to underlying backend floating-point nondeterminism. 

**Our chosen tradeoff:** We opted to keep free-text generation for now because it yields higher quality, more natural prose. We compensate for minor discrepancies with array-level normalization (such as list sorting and whitespace stripping) in the evaluation suite rather than enforcing strict string matching. If latency and absolute determinism become hard constraints, the system should pivot to structured-fact extraction combined with deterministic templating for the prose sections—trading some conversational naturalness for speed and guaranteed reproducibility.

### Data Sensitivity

Support tickets and account metadata inherently contain PII (Personally Identifiable Information). We used the free-tier Gemini and Groq APIs for this prototype. Free-tier terms of service generally permit inputs to be utilized for model training and improvement, representing a critical leak risk for production customer data.

**In production:** The system must use a paid, enterprise-tier LLM offering. Organizations must explicitly verify the selected provider's exact retention and training terms to ensure strict data residency and a zero-training retention policy. Furthermore, PII (such as customer names, emails, and phone numbers) must be protected using an approved, access-controlled redaction or tokenization scheme in a local processing step *before* sending any ticket payload to external APIs.

### Scaling

If ticket volume increases by 10x, the initial infrastructure will break at two specific bottlenecks:

1. **API Rate Quotas:** The most immediate failure point we encountered was hitting the free-tier daily request quota (a 20 request/day cap on a Google Cloud project) and the Tokens Per Minute (TPM) limits on Groq.
   - **Mitigation:** We implemented response caching to alleviate duplicate processing. In production, this must be augmented with a paid-tier API, a batching API for asynchronous bulk processing, and tiered model routing (using smaller, cheaper, faster models for simple triage and reserving flagship models for complex or ambiguous cases).
2. **Retrieval Linearity:** The TF-IDF Knowledge Base retrieval is currently implemented as a linear scan over 9 documents. While perfectly viable for a small static corpus, this approach will degrade significantly in latency.
   - **Mitigation:** If the KB grows to hundreds or thousands of documents, the linear TF-IDF scan must be replaced with proper indexing (e.g., generating embeddings and storing them in a vector database for approximate nearest-neighbor search).