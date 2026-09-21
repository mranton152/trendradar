"""Единственный источник правды по схемам данных между слоями.

Менять этот файл имеет право ТОЛЬКО Антон, через PR с обсуждением.
Все остальные слои читают схемы отсюда и обязаны им соответствовать.

Проверка: python contracts/validate.py <файл.parquet> --schema works
"""
import pyarrow as pa

# --------------------------------------------------------------- works
# Кто пишет: ingest/ (Константин)
# Кто читает: semantic/, core/, cards/
# Гранулярность: одна строка = один документ (статья, препринт, патент, модель, репозиторий)
# Путь: data/corpus/{domain}/works.parquet

WORKS = pa.schema([
    pa.field("doc_id",       pa.string(), nullable=False),   # "openalex:W2741809807", "arxiv:2301.00001"
    pa.field("source",       pa.string(), nullable=False),   # openalex|arxiv|crossref|biorxiv|hf|github|patentsview|epo
    pa.field("doc_type",     pa.string(), nullable=False),   # article|preprint|patent|model|repo|report
    pa.field("title",        pa.string(), nullable=False),
    pa.field("abstract",     pa.string(), nullable=True),
    pa.field("year",         pa.int32(),  nullable=False),   # год публикации; для патентов - год подачи заявки
    pa.field("date",         pa.string(), nullable=True),    # ISO 8601, если известна точная дата
    pa.field("lang",         pa.string(), nullable=True),    # ISO 639-1
    pa.field("doi",          pa.string(), nullable=True),
    pa.field("url",          pa.string(), nullable=False),   # проверяемая ссылка на первоисточник
    pa.field("cited_by",     pa.int32(),  nullable=True),
    pa.field("countries",    pa.list_(pa.string()), nullable=True),      # ISO 3166-1 alpha-2, уникальные
    pa.field("institutions", pa.list_(pa.string()), nullable=True),
    pa.field("authors",      pa.list_(pa.string()), nullable=True),
    pa.field("concepts",     pa.list_(pa.string()), nullable=True),      # темы/концепты источника
    pa.field("domain",       pa.string(), nullable=False),   # какой домен харвестили: "artificial-intelligence"
    pa.field("harvested_at", pa.string(), nullable=False),   # ISO дата сбора - нужна для воспроизводимости
    # --- поля по ТЗ (16.09.2026): для каждого источника показывать тип, язык, доверенность ---
    # Все nullable: золотой снапшот собран до ТЗ и обязан читаться без пересборки.
    pa.field("source_type",  pa.string(), nullable=True),    # article|preprint|patent|news|blog|repo|model|report|aggregator|press_release
    pa.field("trust_level",  pa.string(), nullable=True),    # trusted|indicator|unknown - по правилам ТЗ, см. ingest/trust.py
    pa.field("summary_ru",   pa.string(), nullable=True),    # русское резюме зарубежного источника; ТЗ требует пометку, что сгенерировано
    pa.field("summary_model", pa.string(), nullable=True),   # какой моделью сгенерировано резюме - обязательная пометка по ТЗ
])

# ----------------------------------------------------------- candidates
# Кто пишет: semantic/ (Константин)
# Кто читает: core/
# Гранулярность: одна строка = один кандидат в тренды (термин или тематический кластер)
# Путь: data/index/{domain}/candidates.parquet

CANDIDATES = pa.schema([
    pa.field("cand_id",     pa.string(), nullable=False),    # "c:ai:0042"
    pa.field("kind",        pa.string(), nullable=False),    # term|cluster
    pa.field("label",       pa.string(), nullable=False),    # человекочитаемое имя кандидата
    pa.field("aliases",     pa.list_(pa.string()), nullable=True),
    pa.field("top_terms",   pa.list_(pa.string()), nullable=True),   # c-TF-IDF, для кластеров
    pa.field("emb_row",     pa.int32(),  nullable=True),     # номер строки в embeddings.npy; null для kind=term
    pa.field("n_docs",      pa.int32(),  nullable=False),    # сколько документов привязано
    pa.field("domain",      pa.string(), nullable=False),
])

# ------------------------------------------------------------ cand_docs
# Кто пишет: semantic/ (Константин)
# Кто читает: core/, cards/
# Гранулярность: одна строка = связь "кандидат - документ". Вынесено отдельно, чтобы
# не раздувать candidates списками на сотни тысяч элементов.
# Путь: data/index/{domain}/cand_docs.parquet

CAND_DOCS = pa.schema([
    pa.field("cand_id", pa.string(),  nullable=False),
    pa.field("doc_id",  pa.string(),  nullable=False),
    pa.field("weight",  pa.float32(), nullable=True),   # для кластеров - близость к центроиду
])

# --------------------------------------------------------------- trends
# Кто пишет: core/ (Антон)
# Кто читает: cards/, api/
# Гранулярность: одна строка = один тренд в выдаче по домену на срезе as_of
# Путь: data/index/{domain}/trends.parquet

TRENDS = pa.schema([
    pa.field("trend_id",        pa.string(), nullable=False),   # "t:ai:2026:01"
    pa.field("domain",          pa.string(), nullable=False),
    pa.field("as_of",           pa.int32(),  nullable=False),   # год среза; 2026 = сейчас, 2021 = бэктест
    pa.field("rank",            pa.int32(),  nullable=False),   # 1..N
    pa.field("cand_id",         pa.string(), nullable=False),
    pa.field("label",           pa.string(), nullable=False),
    pa.field("aliases",         pa.list_(pa.string()), nullable=True),
    pa.field("emergence_score", pa.float32(), nullable=False),  # 0..1
    # компоненты скоринга - перцентильные ранги, каждая объяснима в UI
    pa.field("c_novelty",       pa.float32(), nullable=False),
    pa.field("c_growth",        pa.float32(), nullable=False),
    pa.field("c_accel",         pa.float32(), nullable=False),
    pa.field("c_burst",         pa.float32(), nullable=False),
    pa.field("c_diffusion",     pa.float32(), nullable=False),
    pa.field("maturity_pct",    pa.float32(), nullable=False),  # 1.0 = самый мейнстримный в пуле
    # доказательная база
    pa.field("first_mention",   pa.int32(),  nullable=True),    # первый год с >=5 документов
    pa.field("takeoff_year",    pa.int32(),  nullable=True),    # год выхода на 10% собственного пика
    pa.field("years",           pa.list_(pa.int32()),   nullable=False),
    pa.field("counts",          pa.list_(pa.int32()),   nullable=False),  # параллельно years
    pa.field("freq_per_million", pa.list_(pa.float32()), nullable=False), # параллельно years
    pa.field("n_docs",          pa.int32(),  nullable=False),
    pa.field("n_countries",     pa.int32(),  nullable=False),
    pa.field("n_orgs",          pa.int32(),  nullable=True),
    pa.field("n_patents",       pa.int32(),  nullable=True),
    pa.field("top_doc_ids",     pa.list_(pa.string()), nullable=False),   # 10-20 док-ов для RAG и ссылок
    pa.field("stage",           pa.string(), nullable=False),   # emerging|early_growth|scaling
    pa.field("confidence",      pa.string(), nullable=False),   # high|medium|low
    pa.field("methodology_version", pa.string(), nullable=False),
    # --- живой режим: ряды по месяцам, а не по годам. null = year (индексный режим) ---
    pa.field("series_granularity", pa.string(), nullable=True),  # year|month; при month в years лежат YYYYMM
    # --- бэктест: что тренд сделал ПОСЛЕ среза. Заполняется только при as_of в прошлом ---
    pa.field("bt_at_cutoff",    pa.int32(),   nullable=True),   # документов в год среза
    pa.field("bt_peak_after",   pa.int32(),   nullable=True),   # пик после среза
    pa.field("bt_growth_x",     pa.float32(), nullable=True),   # во сколько раз вырос
])

# ------------------------------------------------------------- rejected
# Кто пишет: core/ (Антон)
# Кто читает: api/ (Михаил)
# Гранулярность: одна строка = кандидат, не прошедший фильтры, с причиной
# Путь: data/index/{domain}/rejected.parquet
# ТЗ требует показывать "причины исключения зрелых технологий или нерелевантных
# кандидатов". И это наш аргумент: lynching tree с нулём стран должен быть виден.

REJECTED = pa.schema([
    pa.field("cand_id", pa.string(), nullable=False),
    pa.field("label",   pa.string(), nullable=False),
    pa.field("domain",  pa.string(), nullable=False),
    pa.field("reason",  pa.string(), nullable=False),   # текст из core/filters.py, как есть
    pa.field("n_docs",  pa.int32(),  nullable=False),
    pa.field("as_of",   pa.int32(),  nullable=False),
])

# ---------------------------------------------------------------- cards
# Кто пишет: cards/ (Михаил)
# Кто читает: api/
# Гранулярность: одна строка = текстовая карточка одного тренда
# Путь: data/index/{domain}/cards.parquet
# ЖЁСТКОЕ ПРАВИЛО: любое утверждение несёт doc_ids. Утверждение без источника
# отбрасывается на постобработке и НЕ попадает в файл.

CARDS = pa.schema([
    pa.field("trend_id",       pa.string(), nullable=False),
    pa.field("title_ru",       pa.string(), nullable=False),   # человеческое название тренда по-русски
    pa.field("problem",        pa.string(), nullable=False),   # какую проблему решает
    pa.field("problem_docs",   pa.list_(pa.string()), nullable=False),
    pa.field("advantage",      pa.string(), nullable=False),   # какое даёт преимущество
    pa.field("advantage_docs", pa.list_(pa.string()), nullable=False),
    pa.field("case_type",      pa.string(), nullable=False),   # research|company
    pa.field("case_name",      pa.string(), nullable=False),
    pa.field("case_text",      pa.string(), nullable=False),
    pa.field("case_docs",      pa.list_(pa.string()), nullable=False),
    pa.field("fintech_note",   pa.string(), nullable=True),    # применимость для банка
    pa.field("citation_coverage", pa.float32(), nullable=False),  # доля утверждений с источником, целимся в 1.0
    pa.field("model",          pa.string(), nullable=False),   # чем сгенерировано
    pa.field("generated_at",   pa.string(), nullable=False),
])

# ------------------------------------------------------------- features
# Кто пишет: ingest/ (Константин, K-14)
# Кто читает: classifier/ (Антон, A-12)
# Гранулярность: одна строка = один кандидат (или технология из датасета заказчика)
# Путь: data/features/{domain}/features.parquet  и  data/dataset/features.parquet
#
# Признаки для обучаемого классификатора этапа 1. Каждый признак должен быть
# объясним фразой аналитику - они пойдут в отчёт как "предикторы".
# Источники разные и могут отсутствовать, поэтому всё после label - nullable.
# Окно новостей - 24 месяца до as_of, публикаций - 10 лет.

FEATURES = pa.schema([
    pa.field("cand_id",     pa.string(), nullable=False),
    pa.field("label",       pa.string(), nullable=False),
    pa.field("domain",      pa.string(), nullable=False),
    pa.field("as_of",       pa.string(), nullable=False),   # "YYYY-MM"
    # --- новости и индустрия (ingest.live) ---
    pa.field("news_mentions_24m",      pa.int32(), nullable=True),           # документов за 24 месяца
    pa.field("news_mentions_by_month", pa.list_(pa.int32()), nullable=True), # ровно 24 значения, старые первыми
    pa.field("news_first_month",       pa.string(), nullable=True),          # "YYYY-MM" первого упоминания
    pa.field("n_domains",              pa.int32(), nullable=True),           # разных сайтов
    pa.field("trusted_share",          pa.float32(), nullable=True),         # доля trusted среди источников
    pa.field("n_companies",            pa.int32(), nullable=True),           # разных компаний в заголовках
    pa.field("funding_mentions",       pa.int32(), nullable=True),           # raises|series|seed|stealth|pilot|launch
    pa.field("langs",                  pa.list_(pa.string()), nullable=True),# языки источников
    # --- код и модели ---
    pa.field("github_repos",           pa.int32(), nullable=True),
    pa.field("github_stars_max",       pa.int32(), nullable=True),
    pa.field("hf_models",              pa.int32(), nullable=True),
    # --- публикации (точечный OpenAlex по годам) ---
    pa.field("pub_counts_by_year",     pa.list_(pa.int32()), nullable=True), # ровно 10 значений, старые первыми
    pa.field("pub_countries",          pa.int32(), nullable=True),
    pa.field("pub_company_share",      pa.float32(), nullable=True),         # доля работ с корпоративной аффилиацией
    # --- разметка (только для обучающей выборки) ---
    pa.field("is_weak_signal",         pa.bool_(), nullable=True),           # 100 из xlsx = true; наши отрицательные = false
    pa.field("dataset_score",          pa.int32(), nullable=True),           # "Балл (стадия+тренд)" 3..7 из xlsx
    pa.field("dataset_stage",          pa.string(), nullable=True),          # "Стадия развития" как в xlsx
])

SCHEMAS = {
    "works": WORKS,
    "candidates": CANDIDATES,
    "cand_docs": CAND_DOCS,
    "trends": TRENDS,
    "cards": CARDS,
    "rejected": REJECTED,
    "features": FEATURES,
}
