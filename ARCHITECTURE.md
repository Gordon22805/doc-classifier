# Архитектура OCR Classification Service

## Общая схема системы

```
┌─────────────────────────────────────────────────────────────────┐
│                         Web Browser                              │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐                │
│  │   Upload   │  │   Review   │  │  Download  │                │
│  └────────────┘  └────────────┘  └────────────┘                │
└────────────────────────┬─────────────────────────────────────────┘
                         │ HTTP/JSON
                         ↓
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI Server                              │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  API Routes (routes.py)                                     │ │
│  │  • POST /api/upload          • GET /api/job/{id}           │ │
│  │  • POST /api/job/{id}/correct • GET /api/job/{id}/download │ │
│  │  • GET /api/health                                          │ │
│  └────────────────────────┬───────────────────────────────────┘ │
│                           ↓                                      │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  Document Processor (document_processor.py)                 │ │
│  └────────────────────────┬───────────────────────────────────┘ │
└───────────────────────────┼──────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ↓                   ↓                   ↓
┌───────────────┐  ┌────────────────┐  ┌──────────────┐
│ Text Extract  │  │  OCR Client    │  │  Classifier  │
│ (PDF/DOCX)    │  │  (GPT-4)       │  │  (Rules)     │
└───────┬───────┘  └───────┬────────┘  └──────┬───────┘
        │                  │                   │
        │         ┌────────┴────────┐         │
        │         │  OpenAI API     │         │
        │         │  vision-модель  │         │
        │         └─────────────────┘         │
        │                                     │
        └─────────────┬───────────────────────┘
                      ↓
            ┌──────────────────┐
            │ Result Builder   │
            │ (ZIP Archive)    │
            └──────────────────┘
```

## Конвейер обработки документа

```
┌──────────────┐
│ Upload File  │
└──────┬───────┘
       │
       ↓
┌──────────────────────────────────────┐
│ Is Archive? (ZIP/7Z)                 │
└──┬───────────────────────────────┬───┘
   │ Yes                           │ No
   ↓                               ↓
┌──────────────────┐      ┌────────────────┐
│ Extract Archive  │      │ Parse Document │
│ • Zip Slip Check │      │ • PDF pages    │
│ • Size Limits    │      │ • DOCX text    │
│ • Nested Check   │      │ • Images       │
└────────┬─────────┘      └────────┬───────┘
         │                         │
         └────────────┬────────────┘
                      ↓
            ┌──────────────────┐
            │  For Each Page   │
            └─────────┬────────┘
                      │
                      ↓
    ┌─────────────────────────────────────┐
    │ Extract Text Layer (if PDF)         │
    └─────────────────┬───────────────────┘
                      │
                      ↓
    ┌─────────────────────────────────────┐
    │ Check Text Quality                  │
    │ • Length, alnum ratio               │
    │ • Artifacts, replacements           │
    │ • Latin in Russian                  │
    └──┬──────────────────────────────┬───┘
       │ Good                         │ Bad
       │                              ↓
       │              ┌────────────────────────────┐
       │              │ OCR Cascade                │
       │              │ 1. ORIGINAL                │
       │              │ 2. FOCUSED (crop borders)  │
       │              │ 3. ENHANCED (contrast++)   │
       │              │ 4. TILED (split)           │
       │              └────────────┬───────────────┘
       │                           │
       └───────────────┬───────────┘
                       │
                       ↓
         ┌──────────────────────────┐
         │ Normalize Text           │
         │ • Unicode NFKC           │
         │ • Lowercase              │
         │ • ё → е                  │
         │ • Spaces, dashes         │
         │ • Mixed Cyrillic/Latin   │
         └────────────┬─────────────┘
                      │
                      ↓
         ┌──────────────────────────┐
         │ Classify Page            │
         │ 1. Filename hint         │
         │ 2. Structural (EGRN)     │
         │ 3. Exact title           │
         │ 4. Fuzzy title           │
         │ 5. Passport patterns     │
         │ 6. Form number + phrase  │
         │ 7. Scoring rules         │
         │ 8. Character n-grams     │
         └────────────┬─────────────┘
                      │
                      ↓
         ┌──────────────────────────┐
         │ Context Classification   │
         │ • Multi-page inheritance │
         │ • EGRN continuations     │
         │ • Document boundaries    │
         └────────────┬─────────────┘
                      │
                      ↓
         ┌──────────────────────────┐
         │ Manual Correction        │
         │ (User Interface)         │
         └────────────┬─────────────┘
                      │
                      ↓
         ┌──────────────────────────┐
         │ Group Pages              │
         │ • By document type       │
         │ • By source file         │
         │ • Create PDFs            │
         └────────────┬─────────────┘
                      │
                      ↓
         ┌──────────────────────────┐
         │ Build ZIP Archive        │
         │ • Type folders           │
         │ • Merged PDFs            │
         │ • Manifest JSON          │
         └──────────────────────────┘
```

## OCR Cascade детализация

```
┌────────────────────────────────────────────────────────────────┐
│                     OCR Cascade (vision-модель)                    │
└────────────────────────────────────────────────────────────────┘

Text Layer Available?
        │
        ├─ Yes ──→ Extract ──→ Quality Check ──→ Good ──→ [Use Text]
        │                            │
        └─ No ──────────────────────┬┘ Bad
                                    ↓
                        ┌───────────────────────┐
                        │  Attempt 1: ORIGINAL  │
                        │  Prompt: Extract all  │
                        │  Input: Full page     │
                        └──────────┬────────────┘
                                   │
                            Confident? ──Yes──→ [Done]
                                   │ No
                                   ↓
                        ┌───────────────────────┐
                        │  Attempt 2: FOCUSED   │
                        │  Prompt: High accuracy│
                        │  Input: Cropped image │
                        └──────────┬────────────┘
                                   │
                            Confident? ──Yes──→ [Merge + Done]
                                   │ No
                                   ↓
                        ┌───────────────────────┐
                        │  Attempt 3: ENHANCED  │
                        │  Prompt: Max accuracy │
                        │  Input: Enhanced      │
                        └──────────┬────────────┘
                                   │
                            Confident? ──Yes──→ [Merge + Done]
                                   │ No
                                   ↓
                        ┌───────────────────────┐
                        │  Attempt 4: TILED     │
                        │  Top half + Bottom    │
                        │  18% overlap          │
                        └──────────┬────────────┘
                                   │
                                   ↓
                            [Merge All Results]
```

## Классификация документов

```
┌──────────────────────────────────────────────────────────────┐
│              Document Classification Pipeline                 │
└──────────────────────────────────────────────────────────────┘

Normalized Text
      │
      ↓
┌────────────────────┐
│ Rule 1: Filename   │──→ passport_scan.pdf + "паспорт" in text
│ + Text Confirm     │    ═══════════════════════════════════════→ PASSPORT
└─────────┬──────────┘
          │ Not Matched
          ↓
┌────────────────────┐
│ Rule 2: EGRN       │──→ ≥3 structural groups:
│ Structural         │    • Cadastral + Price + Holder
└─────────┬──────────┘    ═══════════════════════════════════════→ EGRN
          │ Not Matched
          ↓
┌────────────────────┐
│ Rule 3: Exact      │──→ "предварительный договор купли-продажи"
│ Specific Title     │    ═══════════════════════════════════════→ PDKP
└─────────┬──────────┘
          │ Not Matched
          ↓
┌────────────────────┐
│ Rule 4: Fuzzy      │──→ Token overlap ≥70% + margin ≥20%
│ Title Match        │    ═══════════════════════════════════════→ Candidate
└─────────┬──────────┘
          │ Not Matched
          ↓
┌────────────────────┐
│ Rule 5: Passport   │──→ Series + Code + Date + MRZ/RUS
│ Patterns           │    ═══════════════════════════════════════→ PASSPORT
└─────────┬──────────┘
          │ Not Matched
          ↓
┌────────────────────┐
│ Rule 6: Context    │──→ Previous pages same type?
│ Inheritance        │    ═══════════════════════════════════════→ Inherit
└─────────┬──────────┘
          │ Not Matched
          ↓
┌────────────────────┐
│ Rule 7: Form #     │──→ "0401060" + "платежное поручение"
│ + Required Phrase  │    ═══════════════════════════════════════→ PAYMENT
└─────────┬──────────┘
          │ Not Matched
          ↓
┌────────────────────┐
│ Rule 8: Weighted   │──→ Positive features +
│ Scoring            │    Negative features -
└─────────┬──────────┘    Score ≥2 & Margin ≥2 ═════════════════→ Type
          │ Below Threshold
          ↓
┌────────────────────┐
│ Rule 9: Character  │──→ 3-5 char n-grams
│ N-grams + IDF      │    IDF weighting
└─────────┬──────────┘    Top match ════════════════════════════→ Type
          │ Still Uncertain
          ↓
    ┌────────────┐
    │  UNKNOWN   │
    └────────────┘
```

## Модульная структура

```
backend/
│
├── api/
│   └── routes.py                # FastAPI endpoints
│       ├── /api/upload          # Multipart file upload
│       ├── /api/job/{id}        # Job status
│       ├── /api/job/{id}/correct # Manual correction
│       ├── /api/job/{id}/download # ZIP download
│       └── /api/health          # Service health
│
├── core/                        # Business logic
│   ├── document_processor.py   # Main orchestrator
│   │   ├── process_upload()
│   │   ├── process_page()
│   │   └── build_result()
│   │
│   ├── text_extractor.py       # Extract text from files
│   │   ├── extract_pdf_text()
│   │   ├── extract_docx_text()
│   │   └── render_pdf_image()
│   │
│   ├── text_quality.py         # Text quality checker
│   │   ├── check_quality()
│   │   └── needs_ocr()
│   │
│   ├── ocr_client.py           # Клиент vision-модели
│   │   ├── recognize()         # Main OCR method
│   │   ├── _should_retry()     # Retry logic
│   │   └── PROFILES            # OCR prompts
│   │
│   ├── text_normalizer.py      # Text normalization
│   │   ├── normalize()
│   │   ├── _fix_mixed_cyrillic()
│   │   └── _preserve_mrz()
│   │
│   ├── classifier.py           # Document classifier
│   │   ├── classify()
│   │   ├── _check_passport()
│   │   ├── _check_egrn()
│   │   ├── _score_rules()
│   │   └── _ngram_match()
│   │
│   ├── context_classifier.py   # Multi-page context
│   │   ├── apply_context()
│   │   └── _check_continuation()
│   │
│   └── result_builder.py       # Build output ZIP
│       ├── group_pages()
│       ├── create_pdfs()
│       └── build_archive()
│
├── models/
│   └── schemas.py              # Pydantic models
│       ├── DocumentType        # Enum of doc types
│       ├── TextSource          # text_layer/ocr/etc
│       ├── ProcessingStatus    # pending/success/error
│       ├── OCRProfile          # original/focused/enhanced
│       ├── PageResult          # Single page result
│       ├── JobStatus           # Overall job status
│       ├── OCRRequest          # Запрос к vision-модели
│       └── OCRResponse         # Ответ vision-модели
│
├── utils/
│   └── archive_handler.py      # ZIP/7Z processing
│       ├── extract_archive()
│       ├── _check_zip_slip()
│       ├── _check_limits()
│       └── _remove_duplicates()
│
├── config.py                   # Configuration
│   ├── Settings (Pydantic)
│   ├── Environment variables
│   └── Default values
│
└── main.py                     # FastAPI app
    ├── app = FastAPI()
    ├── CORS middleware
    ├── Static files
    └── API router
```

## Безопасность архитектуры

```
┌────────────────────────────────────────────────────────────┐
│                    Security Layers                          │
└────────────────────────────────────────────────────────────┘

Input Validation
    │
    ├─→ File Type Check ──→ Whitelist: pdf, jpg, png, docx, zip, 7z
    ├─→ File Size Check ──→ MAX_FILE_SIZE_MB = 50
    └─→ Total Size Check ─→ MAX_TOTAL_SIZE_MB = 500

Archive Processing
    │
    ├─→ Zip Slip Protection ──→ Check path stays in temp dir
    ├─→ Max Files Limit ──────→ MAX_ARCHIVE_FILES = 100
    ├─→ Nested Depth Limit ───→ MAX_NESTED_ARCHIVES = 2
    └─→ Bomb Detection ────────→ Track total extracted size

File Paths
    │
    ├─→ Sanitize Filenames ───→ Remove ../, ..\, absolute paths
    ├─→ UUID Prefixes ─────────→ Prevent overwrites
    └─→ Temp Directory ────────→ Isolated from system

Logging
    │
    ├─→ No PII ────────────────→ No text content, names, dates
    ├─→ Structured Logs ───────→ JSON with context
    └─→ Error Sanitization ────→ No stack traces to users

API Rate Limiting (Recommended)
    │
    ├─→ Per IP ────────────────→ 100 req/min
    ├─→ Per Session ───────────→ 10 uploads/hour
    └─→ OpenAI API ────────────→ Respects tier limits
```

## Развертывание

```
┌──────────────────────────────────────────────────────────────┐
│                    Deployment Options                         │
└──────────────────────────────────────────────────────────────┘

Option 1: Local Development
    │
    ├─→ pip install -r requirements.txt
    ├─→ Set OPENAI_API_KEY in .env
    └─→ uvicorn backend.main:app --reload

Option 2: Docker Single Container
    │
    ├─→ docker build -t ocr-classifier .
    └─→ docker run -p 8000:8000 -e OPENAI_API_KEY=xxx

Option 3: Docker Compose
    │
    ├─→ Set environment in .env
    └─→ docker-compose up -d

Option 4: Production (Recommended)
    │
    ├─→ Load Balancer (Nginx)
    ├─→ Multiple Uvicorn Workers
    ├─→ Redis (Job Queue)
    ├─→ PostgreSQL (State)
    ├─→ S3/MinIO (File Storage)
    ├─→ Prometheus (Metrics)
    └─→ Grafana (Dashboards)

┌──────────────────────────────────────────────────────────────┐
│          Production Architecture (Future)                     │
└──────────────────────────────────────────────────────────────┘

                    ┌─────────────┐
                    │   Nginx     │
                    │   (SSL)     │
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          ↓                ↓                ↓
    ┌─────────┐      ┌─────────┐     ┌─────────┐
    │Uvicorn 1│      │Uvicorn 2│     │Uvicorn N│
    └────┬────┘      └────┬────┘     └────┬────┘
         │                │                │
         └────────────────┼────────────────┘
                          ↓
                    ┌───────────┐
                    │   Redis   │
                    │  (Queue)  │
                    └─────┬─────┘
                          │
         ┌────────────────┼────────────────┐
         ↓                ↓                ↓
    ┌─────────┐     ┌─────────┐     ┌─────────┐
    │Celery W1│     │Celery W2│     │Celery WN│
    └────┬────┘     └────┬────┘     └────┬────┘
         │                │                │
         ├────────────────┴────────────────┤
         ↓                                 ↓
   ┌───────────┐                    ┌──────────┐
   │PostgreSQL │                    │  MinIO   │
   │  (State)  │                    │ (Files)  │
   └───────────┘                    └──────────┘
```

## Точки расширения

```
Future Enhancements:

1. Caching Layer
   ├─→ Redis cache for OCR results
   └─→ Deduplication by image hash

2. Machine Learning
   ├─→ Fine-tune vision-модели на документах
   ├─→ Train custom classifier
   └─→ Active learning from corrections

3. Advanced Features
   ├─→ Multi-language support
   ├─→ Signature detection
   ├─→ Barcode/QR reading
   └─→ Table extraction

4. Integration
   ├─→ Webhook notifications
   ├─→ External storage (S3)
   ├─→ Document management systems
   └─→ Workflow automation

5. Analytics
   ├─→ Accuracy tracking
   ├─→ Performance metrics
   ├─→ Cost optimization
   └─→ A/B testing rules
```
