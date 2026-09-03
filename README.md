# Voice Task

Asistent personal controlat prin voce, în limba română: notițe, programări, alarme,
documente scanate cu OCR, căutare unificată, integrare Gmail / Google Calendar și un
rezumat zilnic text + audio.

Aplicație web **mobile-first**, construită integral cu **Python + Django**. Interfața
folosește Django Templates + HTMX; JavaScript-ul există doar acolo unde browserul îl
impune (microfon, cameră, player audio, notificări, service worker) și nu conține
logică de business.

**Aplicația funcționează complet fără nicio cheie externă.** Providerii demonstrativi
acoperă transcrierea, OCR-ul, sinteza vocală, Gmail și Calendar, iar interpretarea
comenzilor în română rulează local, pe un parser bazat pe reguli.

---

## Cuprins

- [Pornire rapidă](#pornire-rapidă)
- [Ecrane](#ecrane)
- [Arhitectură](#arhitectură)
- [Provideri externi](#provideri-externi)
- [Gmail și Google Calendar](#gmail-și-google-calendar)
- [OCR](#ocr)
- [Notificări și PWA](#notificări-și-pwa)
- [Celery, Redis și PostgreSQL](#celery-redis-și-postgresql)
- [Variabile de mediu](#variabile-de-mediu)
- [Teste și verificări](#teste-și-verificări)
- [Securitate și confidențialitate](#securitate-și-confidențialitate)
- [Limitări cunoscute](#limitări-cunoscute)

---

## Pornire rapidă

Necesar: **Python 3.11+**. Nimic altceva.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

Copy-Item .env.example .env
python manage.py genereaza_chei      # copiază cheile generate în .env

python manage.py migrate
python manage.py seed_demo --user demo --password demo1234
python manage.py runserver
```

Pe Linux/macOS:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py genereaza_chei
python manage.py migrate
python manage.py seed_demo --user demo --password demo1234
python manage.py runserver
```

Deschide <http://127.0.0.1:8000/> și intră cu **demo / demo1234**.
Administrarea: `python manage.py createsuperuser`, apoi <http://127.0.0.1:8000/admin/>.

`seed_demo` creează datele din mockup-uri — Întâlnire proiect Alpha, Control medical,
Ședință cu părinții, Zbor București–Cluj-Napoca, Factura energie, Invitație serbare,
Urmărește email: Ana Popescu, Checklist vacanță, Listă cumpărături, Brief întâlnire
Alpha — cu **date relative**, deci demo-ul rămâne relevant oricând. Rulată din nou nu
dublează nimic; `--reset` șterge definitiv datele acelui utilizator înainte.

---

## Ecrane

Capturi în [`docs/capturi/`](docs/capturi/), realizate la 390 px.

| # | Ecran | URL | Captură |
|---|---|---|---|
| 1 | Acasă | `/` | [01-acasa.png](docs/capturi/01-acasa.png) |
| 2 | Adaugă | `/asistent/inregistreaza/` | [02-inregistreaza.png](docs/capturi/02-inregistreaza.png) |
| 3 | Modifică | `/modifica/` | [03-modifica.png](docs/capturi/03-modifica.png) |
| 4 | Șterge | `/sterge/` | [04-sterge.png](docs/capturi/04-sterge.png) |
| 5 | Caută | `/cauta/` | [05-cauta.png](docs/capturi/05-cauta.png) |
| 6 | Notițe | `/notite/` | [06-notite.png](docs/capturi/06-notite.png) |
| 7 | Programări | `/programari/` | [07-programari.png](docs/capturi/07-programari.png) |
| 8 | Fotografiază documentul | `/documente/scaneaza/` | [08-scaneaza.png](docs/capturi/08-scaneaza.png) |
| 9 | Rezumatul zilei | `/rezumat/` | [09-rezumat.png](docs/capturi/09-rezumat.png) |
| — | Notificări | `/notificari/` | [10-notificari.png](docs/capturi/10-notificari.png) |
| — | Gmail și Calendar | `/integrari/` | [11-integrari.png](docs/capturi/11-integrari.png) |
| — | Coș de gunoi | `/cos/` | [12-cos.png](docs/capturi/12-cos.png) |

Navigația inferioară are patru destinații fixe: **Acasă · Notițe · Programări · Caută**.
„Modifică" și „Șterge" sunt acțiuni contextuale, deschise ca pagini secundare, nu
înlocuiesc niciodată navigația. Singurul ecran fără navigație inferioară este camera,
pentru a rămâne imersiv.

---

## Arhitectură

```
voicetask/
├── config/                    proiectul Django
│   ├── env.py                 încarcă .env înainte de rezolvarea setărilor
│   ├── celery.py              aplicația Celery + beat schedule
│   └── settings/{base,dev,prod,test}.py
├── apps/
│   ├── core/                  modele de bază, provideri, mixins, coș, ecranele Modifică/Șterge
│   │   └── providers/         interfețele celor 7 provideri + registry
│   ├── accounts/              autentificare, UserPreference
│   ├── notes/                 Note, NoteCategory, ChecklistItem
│   ├── scheduling/            Appointment, Reminder, calendar
│   ├── documents/             ScannedDocument + pipeline OCR
│   │   └── pipeline/          validate → preprocess → ocr → extract
│   ├── integrations/          ConnectedAccount, EmailReference, OAuth, sync
│   ├── assistant/             voce → intenție → schiță → confirmare
│   ├── daily_brief/           instantaneu, text determinist, polish, TTS
│   ├── notifications/         dispatch idempotent, Web Push
│   └── search/                registry de surse, backends Postgres/SQLite
├── templates/                 șabloane + icoane SVG
├── static/css/                design tokens + componente
├── static/js/                 module de transport/UI (fără logică de business)
└── docs/capturi/              capturi de ecran
```

### Principii

**Nimic nu se salvează fără confirmare.** Comanda vocală produce o *schiță*
(`IntentDraft`) pe care utilizatorul o vede și o editează. Documentul scanat produce un
formular editabil. Ștergerea prin voce cere o a doua confirmare explicită.

**Izolare pe utilizator.** Fiecare model de domeniu moștenește `OwnedModel`, iar
view-urile folosesc `OwnerQuerysetMixin`. Un PK străin dă **404**, nu 403 — nu confirmăm
nici măcar existența obiectului altcuiva.

**Soft delete.** Ștergerea mută în coș (`deleted_at`); un task Celery purjează definitiv
după 30 de zile. Managerul implicit filtrează automat, inclusiv prin relații inverse.

**Rezumatul zilnic este determinist.** Textul se construiește din baza de date. AI-ul
poate doar reformula, iar rezultatul trece printr-o poartă care respinge orice număr,
dată sau nume propriu nou. Reformularea este **oprită implicit**.

---

## Provideri externi

Șapte interfețe, fiecare cu implementare reală și una demonstrativă, alese prin
variabile de mediu. `manage.py check` verifică la pornire că fiecare cale se importă
și implementează interfața corectă.

| Interfață | Implementare reală | Implicit (fără chei) |
|---|---|---|
| `TranscriptionProvider` | OpenAI Whisper | frază demonstrativă, deterministă |
| `IntentParserProvider` | OpenAI (JSON schema) | **parser român pe reguli** — implementare reală, offline |
| `OCRProvider` | RapidOCR (ONNX) / EasyOCR | text de factură demonstrativ |
| `TextToSpeechProvider` | OpenAI TTS | WAV generat local |
| `GmailProvider` | Gmail API | mesaje de exemplu |
| `CalendarProvider` | Google Calendar API | evenimente de exemplu |
| `NotificationProvider` | Web Push (VAPID) | consolă, `supports_push() == False` |

Activarea providerilor AI:

```bash
AI_ENABLED=True
OPENAI_API_KEY=sk-...
PROVIDER_TRANSCRIPTION=apps.assistant.providers.openai_transcription.OpenAITranscriptionProvider
PROVIDER_INTENT=apps.assistant.providers.openai_intent.OpenAIIntentParser
PROVIDER_TTS=apps.daily_brief.providers.openai_tts.OpenAITTSProvider
```

Cu `AI_ENABLED=False`, providerii AI sunt înlocuiți automat cu cei offline, indiferent
de `PROVIDER_*` — util ca protecție împotriva costurilor neintenționate.

### Parserul român offline

`RuleBasedIntentParser` nu este un stub. Recunoaște verbele uzuale, extrage titlul,
data, ora, locația, persoana, suma și decalajul alarmei, și semnalează singur ce a
rămas ambiguu:

| Comandă | Rezultat |
|---|---|
| „Programează o întâlnire mâine la 10 cu titlul Sincronizare la Google Meet" | programare · mâine 10:00 · Google Meet · titlu „Sincronizare" |
| „Pune-mi o alarmă vineri la 9 pentru controlul medical la Clinica MedLife" | alarmă · vineri 09:00 · Clinica MedLife |
| „Aminteste-mi peste două săptămâni să reînnoiesc asigurarea" | alarmă · +14 zile |
| „Mută alarma cu două zile înainte" | modificare · decalaj 2880 min |
| „Pune-mi o alarmă" | **cere clarificare**: „Pentru ce dată să o programez?" |
| „Programează o întâlnire mâine la 3" | **cere clarificare**: oră ambiguă |

Tiparele sunt scrise fără diacritice și se aplică pe o versiune „împăturită" a
textului, aliniată caracter cu caracter cu originalul — astfel „Ședință cu părinții"
este recunoscut, iar titlul păstrează diacriticele rostite.

---

## Gmail și Google Calendar

Fără credențiale Google, ecranul **Integrări** arată corect „Neconectat" și oferă
butonul „Mod demonstrativ", care importă mesaje și evenimente de exemplu, marcate
explicit ca demonstrative.

Pentru conectare reală:

1. [Google Cloud Console](https://console.cloud.google.com/) → creează un proiect.
2. **APIs & Services → Library** → activează *Gmail API* și *Google Calendar API*.
3. **OAuth consent screen** → tip „External", adaugă-te ca test user.
4. **Credentials → Create credentials → OAuth client ID → Web application**.
   Authorized redirect URI: `http://127.0.0.1:8000/integrari/google/callback/`.
5. Pune `GOOGLE_CLIENT_ID` și `GOOGLE_CLIENT_SECRET` în `.env`.

Scope-uri folosite (minimul necesar):

| Serviciu | Scope | Observație |
|---|---|---|
| Gmail | `gmail.metadata` (implicit) | **Nu returnează fragmente de text.** Câmpul „fragment" rămâne gol; interfața o spune explicit. |
| Gmail | `gmail.readonly` (opt-in) | Setează `GMAIL_SCOPE_LEVEL=readonly` dacă vrei fragmente. |
| Calendar | `calendar.events` | Scrierea se face **numai** după confirmare în interfață. |

Trimiterea de emailuri nu este implementată în această versiune, intenționat.
Tokenurile se stochează criptate cu Fernet (`TOKEN_ENCRYPTION_KEY`), nu apar în
admin și nu sunt scrise niciodată în loguri.

---

## OCR

Pipeline complet în Python (`apps/documents/pipeline/`):

1. validarea uploadului (tip real din octeți, dimensiune, nume generat de server);
2. orientare EXIF;
3. redimensionare la `OCR_MAX_SIDE_PX`;
4. detectarea conturului documentului și corectarea perspectivei (OpenCV);
5. tonuri de gri;
6. contrast local (CLAHE);
7. reducerea zgomotului (filtru bilateral);
8. recunoașterea textului (`OCRProvider`);
9. gruparea casetelor pe rânduri și normalizarea textului;
10. extragerea structurată, cu scor de încredere per câmp.

Se extrag: titlul, tipul documentului, data documentului, data limită, suma, moneda,
persoana sau compania, adresa, orașul, ora, CUI-ul, IBAN-ul și acțiunea propusă.
Câmpurile sub `OCR_FIELD_CONFIDENCE_WARN` sunt marcate în formular cu „de verificat"
— vizual **și** prin text, nu doar prin culoare.

**Nimic nu se creează automat.** Documentul procesat produce un formular editabil;
alarma, programarea sau notița apar doar la apăsarea butonului „Salvează și creează".

### Motorul real

RapidOCR este instalat implicit ca dependență, dar providerul activ este cel
demonstrativ. Pentru OCR real:

```bash
PROVIDER_OCR=apps.documents.providers.rapid_ocr.RapidOCRProvider
```

Prima recunoaștere descarcă modelele ONNX (~15 MB) și durează câteva secunde.

Alternativ, EasyOCR recunoaște diacriticele românești sensibil mai bine, cu prețul
unei instalări mult mai grele (PyTorch, ~3 GB):

```bash
pip install easyocr
PROVIDER_OCR=apps.documents.providers.easy_ocr.EasyOCRProvider
```

Extracția este scrisă să reziste la particularitatea modelelor antrenate pe alte
limbi: rândurile returnate lipite („DATALIMITADEPLATA") sunt recunoscute corect,
fiindcă etichetele se caută și pe varianta fără spații.

---

## Notificări și PWA

Alarmele apar întotdeauna în aplicație, pe ecranul Acasă și în `/notificari/`.
Notificările în browser sunt suplimentare și cer:

1. chei VAPID pe server (`python manage.py genereaza_chei --vapid`);
2. `PROVIDER_NOTIFICATION=apps.notifications.providers.webpush.WebPushProvider`;
3. permisiunea browserului;
4. HTTPS (sau `127.0.0.1`).

Interfața declară push activ **doar** când serverul îl suportă *și* există un
abonament înregistrat. Dacă browserul refuză permisiunea, se afișează explicit
alternativa, nu un mesaj fals de succes.

Deduplicarea este garantată de baza de date: cheia include momentul alarmei, iar o
constrângere unică pe `(owner, dedup_key)` face imposibilă trimiterea de două ori.
După amânare se trimite din nou — o singură dată.

PWA: `manifest.webmanifest` și `sw.js` sunt servite prin view-uri, ca să poată folosi
URL-urile statice cu hash. Service workerul folosește network-first pentru navigări și
cache-first pentru fișiere statice. **Nu se pun niciodată în cache** `/media/`,
`/documente/`, `/rezumat/audio/` și `/asistent/` — ar fi o scurgere de date personale
în cache-ul browserului.

---

## Celery, Redis și PostgreSQL

În dezvoltare, `CELERY_TASK_ALWAYS_EAGER=True`: taskurile rulează sincron, în proces,
deci **nu este nevoie de Redis**. Aplicația este complet funcțională așa.

Pentru stack-ul real:

```bash
docker compose up --build
```

Sau manual:

```bash
redis-server
celery -A config worker -l info      # pe Windows: -P solo
celery -A config beat -l info
DJANGO_SETTINGS_MODULE=config.settings.prod python manage.py migrate
```

Taskuri programate (`config/celery.py`):

| Task | Frecvență | Rol |
|---|---|---|
| `notifications.dispatch_due_reminders` | la fiecare minut | trimite alarmele scadente |
| `daily_brief.generate_scheduled_briefs` | la 15 minute | generează rezumatele |
| `integrations.sync_all_accounts` | la 30 de minute | sincronizează Gmail / Calendar |
| `core.purge_trashed` | zilnic, 03:15 | purjează coșul după 30 de zile |
| `core.purge_expired_drafts` | orar | șterge schițele neconfirmate |
| `core.purge_old_media` | zilnic, 03:40 | șterge înregistrările audio vechi |

Toate sunt idempotente: rulate de două ori nu produc efect dublu.

---

## Variabile de mediu

Lista completă, cu explicații, este în [`.env.example`](.env.example). Cele esențiale:

| Variabilă | Implicit | Rol |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` | `dev` / `prod` / `test` |
| `DJANGO_SECRET_KEY` | — | **obligatorie în producție** |
| `DJANGO_DEBUG` | `False` | `True` doar local |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | listă separată prin virgulă |
| `TOKEN_ENCRYPTION_KEY` | derivată din `SECRET_KEY` | cheie Fernet pentru tokenuri OAuth |
| `AI_ENABLED` | `False` | comută între providerii AI și cei offline |
| `OPENAI_API_KEY` | — | necesară doar cu `AI_ENABLED=True` |
| `PROVIDER_OCR` | mock | `...rapid_ocr.RapidOCRProvider` pentru OCR real |
| `GOOGLE_CLIENT_ID` / `_SECRET` | — | fără ele, interfața arată „Neconectat" |
| `GMAIL_SCOPE_LEVEL` | `metadata` | `readonly` pentru fragmente de text |
| `VAPID_PUBLIC_KEY` / `_PRIVATE_KEY` | — | fără ele, push-ul este dezactivat onest |
| `CELERY_TASK_ALWAYS_EAGER` | `True` în dev | fără Redis local |
| `TRASH_RETENTION_DAYS` | `30` | cât rămân elementele în coș |
| `BRIEF_POLISH_ENABLED` | `False` | reformularea AI a rezumatului |
| `RATE_*_MAX` / `RATE_*_WINDOW` | vezi `.env.example` | limite pentru voce, OCR, AI, căutare |

---

## Teste și verificări

```powershell
pytest                       # 457 teste
pytest -m slow               # include smoke-testul motorului OCR real
ruff check .                 # lint
python manage.py check
$env:DJANGO_SETTINGS_MODULE="config.settings.prod"; python manage.py check --deploy
```

Testele rulează pe provideri demonstrativi, cu accesul la rețea blocat: nicio cheie
API nu este consumată. Acoperă autentificarea, izolarea per utilizator (parametrizată
peste toate modelele și toate rutele), CRUD-ul, soft delete și restaurarea, programarea
alarmelor (inclusiv trecerea la ora de vară din 29 martie 2026), prevenirea
notificărilor duplicate, căutarea și diacriticele, interpretarea datelor în română,
validarea schemei de intenții, comenzile ambigue, confirmarea ștergerii, pipeline-ul
OCR, validarea uploadurilor, generarea rezumatului și invalidarea cache-ului, poarta
anti-halucinație, providerii mock Gmail și Calendar, și un set de verificări de
accesibilitate pe toate ecranele.

Capturile din `docs/capturi/` se regenerează cu Chrome în mod headless; același script
verifică absența scroll-ului orizontal la 320, 390, 430 și 1280 px.

---

## Securitate și confidențialitate

- CSRF activ pe toate formularele; HTMX trimite tokenul din cookie.
- Verificarea proprietarului pe fiecare obiect; PK străin → 404.
- Tipul fișierelor se determină din primii octeți, nu din extensie sau din antetul
  clientului. Numele fișierelor sunt generate integral de server.
- Limite de dimensiune pentru imagini (12 MB) și audio (20 MB).
- Rate limiting pe endpointurile costisitoare: voce, OCR, AI, căutare.
- Tokenurile OAuth se stochează criptate cu Fernet și sunt excluse din admin.
- **Logurile nu conțin niciodată** text OCR, transcrieri, conținut de email, audio sau
  tokenuri — doar metadate (durată, provider, tip de eroare).
- Din emailuri se stochează exclusiv metadatele necesare urmăririi; corpul mesajului
  nu ajunge în baza de date.
- Conținutul provenit din OCR și din emailuri se afișează escapat.
- Scrierile în servicii externe (Google Calendar) cer confirmare și se înregistrează
  în `AuditLog`.
- Fișierele atașate se șterg de pe disc la purjarea definitivă.
- `.env` este în `.gitignore`; niciun secret nu este scris în repository.

## Accesibilitate

Interfața țintește WCAG AA: contrast suficient (textul folosește variantele `*-text`
ale culorilor de categorie, ≥ 4.9:1; variantele decorative nu poartă niciodată text),
focus vizibil, etichete pentru toate câmpurile, nume accesibile pentru butoanele-icon,
regiune `aria-live` pentru procesarea OCR și voce, navigare completă cu tastatura,
suport pentru `prefers-reduced-motion` și link „Sari la conținut". Starea nu este
comunicată niciodată doar prin culoare. Toate iconurile sunt SVG locale — niciun emoji.

---

## Limitări cunoscute

Raportate onest, nu ascunse:

1. **Acuratețea OCR în română.** Modelul RapidOCR nu este antrenat pe diacritice
   românești și returnează frecvent rânduri fără spații. Extracția este scrisă să
   reziste la asta (etichetele se caută și pe varianta fără spații), dar titlul
   recunoscut poate rămâne lipit și trebuie corectat manual. EasyOCR se descurcă
   sensibil mai bine.
2. **PostgreSQL și Redis nu au fost rulate în timpul dezvoltării** — mașina de
   dezvoltare nu are niciunul instalat și nici Docker. Calea de căutare full-text
   pentru PostgreSQL (`SearchVector(config="romanian")`, `pg_trgm`, indexuri GIN) este
   scrisă și acoperită de teste marcate `pg_only`, dar **nu a fost executată**.
   Migrația `search/0002_postgres_fts` este un no-op pe SQLite.
3. **Web Push nu a putut fi testat end-to-end**: necesită HTTPS și un serviciu real de
   push. Providerul de consolă declară corect `supports_push() == False`.
4. **`getUserMedia` cere context securizat.** Funcționează pe `127.0.0.1`; testarea pe
   un telefon din rețeaua locală necesită un certificat. Calea de rezervă
   (`<input type="file" capture="environment">`) este complet funcțională.
5. **Gmail cu scope `metadata` nu returnează fragmente de text** — câmpul „fragment"
   rămâne gol. Interfața o afișează explicit. Nimic din partea Google nu a putut fi
   verificat: nu există credențiale.
6. **Transcrierea audio fără cheie OpenAI este demonstrativă** — returnează o frază
   dintr-un set fix, aleasă determinist din amprenta înregistrării. Restul fluxului
   (interpretare, schiță, confirmare, salvare) este real. Ecranul spune asta explicit.
