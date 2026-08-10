# Архитектура FinSight AI 3.4

```text
PDF / scan / image / DOCX / XLSX / XLS / CSV
        ↓
page-adaptive ingestion
  • native text quality gate
  • coordinate tables
  • multi-pass OCR + high-DPI retry
  • visual locator across a long PDF
        ↓
parallel statement interpretation
  RAS official line codes | IFRS primary statements
        ↓
canonical financial model
  • unified keys and periods
  • unit and sign normalization
  • document/page/sheet/row provenance
        ↓
identity-aware reconciliation + validation
  • assets = non-current + current assets
  • assets = equity + long-term + current liabilities
  • confidence, units and magnitude checks
        ↓
deterministic ratio/trend/risk engines
        ↓
professional deterministic baseline
        ↓
AI editor over validated structured JSON only
        ↓
UI + Excel / Word / PDF exports
```

Модель не выбирается по названию компании. Демо запускается через тот же `process_document`, что и обычная загрузка. Основные формы МСФО имеют приоритет над примечаниями, а РСБУ подтверждается официальными четырехзначными кодами строк и бухгалтерскими равенствами.

Visual recovery не рассчитывает коэффициенты и не исправляет цифры «по смыслу»: она только находит страницы и транскрибирует видимые строки. Все формулы находятся в детерминированном финансовом движке.
