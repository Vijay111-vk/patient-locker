# Patient Locker with Automatic Query Response

A DigiLocker-style portal for patients' claim documents. When an insurer's query letter is added to a
patient's locker, the system works on its own:

1. **Reads the letter** (PDF, scan, photo, DOCX or TXT) and splits it into each separate point the insurer raises.
2. **Checks the patient's locker** and decides, point by point, what is already held and what must come from the patient.
3. **Writes a plain-language message** using the fixed template.
4. **Sends it on WhatsApp and email at the same time**, with no one clicking anything.

The portal shows every patient's profile, documents, query letters, the decision for every query point,
and the history of every message sent.

```
upload letter ──► read text (OCR if scanned) ──► split into points ──► check locker ──► fill template ──► WhatsApp + email
     │                                                                                                         │
     └──────────────────────────── typically a few seconds end to end; timings shown per query ──────────────────┘
```

## Quick start

### With Docker (recommended)

```bash
cp .env.example .env          # then edit .env (see "Configuration")
docker compose up --build
```

Open http://localhost:8000. The 10 sample patients and their documents load automatically on first start.

### Without Docker

Needs Python 3.11+, plus `tesseract-ocr` and `poppler-utils` for scanned documents (optional; text PDFs work without them).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m scripts.seed          # loads sample_data/ and creates logins
uvicorn app.main:app --port 8000
```

### Logins created by the seed script

| Role    | Username                    | Password       | Can see |
|---------|-----------------------------|----------------|---------|
| Admin   | `admin`                     | `admin12345`   | Everything, plus message templates, team accounts and the access log |
| Staff   | `staff`                     | `staff12345`   | All patient lockers; upload documents and query letters |
| Patient | `pt-0001` … `pt-0010`       | `patient12345` | Only their own locker, what is needed from them, and messages sent to them |

Set `SEED_ADMIN_PASSWORD`, `SEED_STAFF_PASSWORD` and `SEED_PATIENT_PASSWORD` before seeding to change these,
or change them later from the Account page.

## Configuration

Everything is set in `.env`. With nothing configured, the system runs fully in test mode: the rules engine
reads letters and messages are recorded in history without being delivered.

### 1. AI for reading and matching (recommended)

The built-in rules engine handles common letter formats, but an AI model is much better at unseen letters,
prose letters and fine distinctions (for example "itemised bill" vs a summary bill). Pick one provider:

```ini
LLM_PROVIDER=anthropic        # or openai, or gemini
ANTHROPIC_API_KEY=...         # or OPENAI_API_KEY / GEMINI_API_KEY
LLM_MODEL=                    # optional; leave empty for the provider's default
```

If the AI call fails for any reason, that step falls back to the rules engine, so a message still goes out.
Before any text is sent to the provider, Aadhaar, PAN, bank account, phone and email numbers are removed
(`REDACT_IDS_FOR_LLM=true`).

### 2. WhatsApp

**Twilio sandbox (fastest to set up):**

1. Create a Twilio account and open *Messaging → Try it out → Send a WhatsApp message*.
2. From the phone that should receive messages, send the `join <your-code>` text shown there to the sandbox number.
   Sandbox membership expires after a few days of inactivity; send the join text again before the demo.
3. Set:
   ```ini
   WHATSAPP_PROVIDER=twilio
   TWILIO_ACCOUNT_SID=ACxxxxxxxx
   TWILIO_AUTH_TOKEN=xxxxxxxx
   TWILIO_WHATSAPP_FROM=+14155238886
   ```

**Meta WhatsApp Cloud API:** set `WHATSAPP_PROVIDER=meta`, `META_ACCESS_TOKEN` and `META_PHONE_NUMBER_ID`.
Meta only delivers free-text messages inside a 24-hour window opened by the recipient. To message someone
first, create and get approval for a template with one body parameter and set `META_TEMPLATE_NAME`.
The test number can only message numbers added as recipients in the Meta dashboard.

Long messages are split automatically to fit provider limits.

### 3. Email

Any SMTP service works (Gmail, SendGrid, Brevo, Amazon SES, Mailgun):

```ini
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-16-char-app-password    # Google account → Security → App passwords
EMAIL_FROM=Claims Support <you@gmail.com>
```

Emails are sent as plain text plus a simple HTML version.

### 4. Sending everything to the judges' test phone and email

```ini
TEST_RECIPIENT_PHONE=+91XXXXXXXXXX
TEST_RECIPIENT_EMAIL=judge@example.com
```

When these are set, every message goes there instead of the patient's own contact details. You can also
simply put the test number and address on each patient profile.

### 5. The message template

The template is in `config/message_template.txt`, and admins can edit it in the portal under
**Settings → Message templates**. The system fills in placeholders such as `{patient_name}`,
`{needed_list}`, `{available_list}` and `{deadline}`; every other character is sent exactly as written.
The full list of placeholders is shown next to the editor.

The AI writes only the wording of each requested item. The message itself is always the template,
so the output follows the template exactly. A second template is used when nothing is needed from the patient.

## Using the portal

- **Patients** shows every patient with their document count, latest query status and how many items are outstanding.
- **A patient's page** has an upload box for query letters, the document checklist (KYC, policy, discharge summary,
  final bill, investigation reports, consultation papers, pharmacy bills, cancelled cheque), every document with its
  detected type, what is still awaited from the patient, and the messages sent.
- **A query's page** lists each point in the insurer's own words, marked **In locker** (with links to the documents
  relied on) or **Ask patient** (with exactly what was requested and why). It also shows the message sent on each
  channel, its delivery result, and how many seconds each step took.
- **Corrections**: staff can change a document's type from a menu, re-check a letter, or send the message again.
  None of these are needed for the automatic flow.

Other behaviour worth knowing:

- **Uploading to the wrong box is handled.** A query letter uploaded as an ordinary document is detected and processed as a query letter.
- **Duplicate files are ignored.** Uploading a file that is already in the locker does not add it twice.
- **New documents close open requests.** When the patient (or staff) later uploads a requested document, the open query is
  re-checked and the point is marked as received. When everything has arrived, the query shows *All received*.
- **Restarts are safe.** Jobs that were in progress when the server stopped resume when it starts again.

### Loading your own sample patients

Put the data in the same layout as `sample_data/`:

```
my_data/
  profiles.json                 # list of patients: patient_code, full_name, phone, email, insurer, claim_number, ...
  patients/PT-0001/*.pdf|jpg    # that patient's documents
```

Then run `python -m scripts.seed --data my_data` (add `--reset` to wipe existing data first).
With Docker, set `SEED_DATA_DIR` to a mounted folder.

### Dry-running a letter

To see what the system would decide and send for a letter, without saving or sending anything:

```bash
python -m scripts.try_query PT-0001 sample_data/query_letters/PT-0001_query_letter.pdf
```

### Upload API

For automated ingestion, set `API_KEY` and call:

```bash
curl -H "X-API-Key: $API_KEY" -F file=@letter.pdf  http://host/api/v1/patients/PT-0001/query-letters
curl -H "X-API-Key: $API_KEY" -F files=@bill.pdf   http://host/api/v1/patients/PT-0001/documents
curl -H "X-API-Key: $API_KEY"                       http://host/api/v1/query-letters/12
```

## How the decisions are made

**Splitting the letter.** The AI is asked for one point per distinct requirement, splitting combined items
(for example "3a", "3b") and ignoring boilerplate such as addresses, warnings and signatures. The rules engine
recognises numbered, lettered, roman-numeral and bulleted lists, falls back to request sentences for prose
letters, and drops header fields and boilerplate.

**Checking the locker.** Every document is classified into one of the standard types when it is uploaded,
with a short summary of what it actually contains. For each query point, the matcher sees the point and the
locker inventory (types, summaries, key facts, text excerpts). It must cite a specific document to mark a point
as already held, so it cannot skip a request without evidence. It is told to ask when a similar document exists
but does not meet the specific requirement, such as:

- an itemised bill when only a summary bill is held;
- a first-year policy when only the current one is held;
- a signed certificate from the treating doctor.

The rules engine applies the same checks for itemised bills and earlier policies. Clarifications only the
patient can answer, such as the reason for late intimation or how an accident happened, are always asked.

**Writing for the patient.** Requests are rephrased in simple language and addressed to the patient
("whether you had any similar complaints"). Each request carries a short reason ("so the insurer can confirm
your identity"). The message also lists what we already hold, so the patient knows not to send it again.

## Care with patient data

- **Roles.** Patients see only their own locker. Requesting another patient's page or file returns
  "not found", so IDs cannot be probed. Staff see lockers. Only admins see templates, accounts and the access log.
- **Files.** Every file is served through an authorised route, never as a public static file. Stored file names
  are random, and responses are marked `no-store` so browsers do not cache them.
- **Access log.** Every sign-in (including failed ones), page view of a patient, document opened, upload,
  change and automatic message is logged with user, time and IP. Admins can filter the log by patient.
- **Masking.** Phone numbers and email addresses are masked in message history. ID and account numbers are
  stripped from document summaries and from anything sent to the AI provider.
- **Web security.** Session cookies are HTTP-only and SameSite (and Secure when `SECURE_COOKIES=true`).
  Every form carries a CSRF token. After five failed sign-ins, further attempts are blocked for five minutes. Passwords are
  hashed with PBKDF2. Changing a password ends other sessions. Security headers include a strict
  Content-Security-Policy.
- **Logs.** Application logs never contain message bodies or document text.

For production, also serve over HTTPS, set a long random `SECRET_KEY`, keep `/data` on an encrypted volume,
and back it up.

## Project layout

```
app/
  main.py            routes: portal pages, uploads, admin, API
  pipeline.py        the automatic flow (background workers, timings, retries on restart)
  query_parser.py    letter → points (AI + rules)
  classifier.py      document → type, summary, key facts (AI + rules)
  matcher.py         points × locker → decisions and patient wording (AI + rules)
  messaging.py       template filling
  notify/            WhatsApp (Twilio / Meta) and email (SMTP)
  extraction.py      PDF text, OCR for scans and photos, DOCX, TXT
  taxonomy.py        document types, keywords and plain-language names
  security.py        roles, sessions, CSRF, audit
  privacy.py         redaction and masking
  templates/, static/
config/              message templates
sample_data/         10 sample patients with documents, and sample query letters
scripts/             seed, dry-run, sample data generator, container start
tests/               parsing, matching, AI paths, access control, end-to-end flow
```

## Tests

```bash
pytest
```

The tests run with the rules engine and test-mode channels, so they never call external services.
They cover:

- splitting letters into points, including prose letters;
- not asking for documents already held;
- itemised-bill detection;
- the AI path, with a fake model;
- redaction before AI calls;
- the full upload-to-message flow on both channels;
- marking points as received after a later upload;
- duplicate uploads;
- the patient, staff and admin access boundaries;
- CSRF protection;
- the upload API.

## Deploying

Any host that runs a Docker container with a persistent disk works, such as Render, Railway, Fly.io or a small VPS.
Mount a volume at `/data` and set the variables from `.env.example`. Set `PORTAL_BASE_URL` to the public
address so the link in messages works, and set `SECURE_COOKIES=true` behind HTTPS.
