import os
import csv
import re
import json
from datetime import datetime, timedelta

import streamlit as st
from gigachat import GigaChat
from gigachat.models import ChatCompletionRequest, ChatMessage

from scenarios import SITUATIONS, DIFFICULTIES, PSYCHOTYPES, LPR


# === ОПЦИОНАЛЬНЫЕ ЗАВИСИМОСТИ ===
try:
    import extra_streamlit_components as stx
    COOKIE_AVAILABLE = True
except ImportError:
    COOKIE_AVAILABLE = False


# === НАСТРОЙКИ ===
MODEL = "GigaChat-2"
BASE_URL = "https://api.giga.chat/v1"

MAX_KNOWLEDGE_CHARS = 15000
MIN_NAME_LEN = 2
MIN_PHONE_LEN = 5

COOKIE_NAME = "sales_trainer_user"
COOKIE_DAYS = 30

EXCLUDE_MD_NAMES = {
    "readme.md", "changelog.md", "license.md", "license.txt",
    "contributing.md", "code_of_conduct.md", "authors.md",
    "notice.md", "security.md", "pull_request_template.md",
}


# === ВОРОНКА ПРОДАЖ ===
STAGES = [
    {
        "id": "new_lead",
        "title": "Новая заявка",
        "goal": "Связаться с клиентом, познакомиться, разговорить, "
                "узнать базовые потребности.",
        "rules": "Не давить, не продавать в лоб. Цель — установить контакт "
                 "и понять, что человеку нужно.",
    },
    {
        "id": "ndz",
        "title": "НДЗ",
        "goal": "Клиент долго не отвечал, но наконец взял трубку / ответил. "
                "Разговорить и провести квалификацию.",
        "rules": "Не упрекать за молчание. Мягко выяснить контекст, "
                 "задать квалифицирующие вопросы.",
    },
    {
        "id": "in_work",
        "title": "Взято в работу",
        "goal": "Дозвонились, но квалификацию не провели. Провести "
                "квалификацию и вывести на встречу (офис / объект / участок / ВКС).",
        "rules": "Не перескакивать к презентации продукта, пока нет ответов "
                 "на ключевые вопросы.",
    },
    {
        "id": "qualification",
        "title": "Квалификация",
        "goal": "Получить ответы на 4 вопроса: когда строить, бюджет, "
                "есть ли участок, технология. Вывести на встречу для "
                "проработки планировки / фасада / посадки.",
        "rules": "Не продавать дом на этом этапе. Только собрать информацию "
                 "и договориться о встрече.",
    },
    {
        "id": "meeting",
        "title": "Встреча проведена",
        "goal": "Выбрать типовой проект, начать проектирование или принять "
                "проект клиента. Согласовать детали и перейти к смете.",
        "rules": "Не спорить о цене на этом этапе. Задача — согласовать проект.",
    },
    {
        "id": "project",
        "title": "Проект выбран",
        "goal": "Согласовать все детали проекта, рассчитать смету, "
                "пригласить клиента на встречу для согласования.",
        "rules": "Не давить с ценой. Сначала — проект, потом — смета.",
    },
    {
        "id": "estimate",
        "title": "Смета и проект согласованы",
        "goal": "Цена утверждена. Получить реквизиты клиента и "
                "договориться о дате подписания договора подряда.",
        "rules": "Не менять условия постфактум. Задача — довести до подписания.",
    },
    {
        "id": "contract",
        "title": "Договор подписан",
        "goal": "Получить оплату, отправить счёт, передать в ПФР.",
        "rules": "Работа с постпродажной поддержкой. Тон — партнёрский.",
    },
]


# Список недопустимых слов (нижний регистр, проверка по подстроке)
BAD_WORDS = [
    "хуй", "хуя", "хую", "хуем", "хуе", "хуё", "хуйн", "хуёв", "хуев",
    "пизд", "пизж",
    "бляд", "блять", "блядь",
    "ебат", "ебал", "ебет", "ебут", "ебан", "ёбан", "ебуч", "ебля",
    "ебись", "еби", "ёбат", "ёбал", "ёбет", "ёбут",
    "нахуй", "нахуя", "похуй", "похуя", "охуе",
    "залуп", "манда", "манду", "манде",
    "сука", "суки", "сучк",
    "мудак", "мудил",
    "пидор", "пидар", "пидр",
    "гандон", "гондон",
    "долбоеб", "долбоёб",
    "шлюх", "ублюд",
    "fuck", "shit", "bitch", "cunt", "dick", "pussy",
    "asshole", "motherfucker",
]

BLOCK_MESSAGE = (
    "⛔ Контент 18+ не допустим для менеджера. "
    "Вернитесь к предыдущему сообщению."
)


# === ПУТЬ К БАЗЕ ЗНАНИЙ ===
def _resolve_knowledge_path() -> str:
    raw = None
    try:
        raw = st.secrets.get("KNOWLEDGE_PATH", None)
    except Exception:
        raw = None

    if raw:
        path = raw
        if not os.path.isabs(path):
            try:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            except NameError:
                base_dir = os.getcwd()
            path = os.path.join(base_dir, path)
    else:
        try:
            path = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            path = os.getcwd()

    return os.path.normpath(path)


KNOWLEDGE_PATH = _resolve_knowledge_path()


# === ТЕМА И СТИЛИ ===
def inject_css() -> None:
    theme = st.session_state.get("theme", "dark")
    if theme == "dark":
        bg, fg, card, border = "#0f1116", "#e7e9ee", "#161a22", "#232a36"
        accent, muted, thought, note = "#7c5cff", "#8b93a7", "#8b93a7", "#eab308"
    else:
        bg, fg, card, border = "#f7f8fb", "#1a1d24", "#ffffff", "#e3e6ee"
        accent, muted, thought, note = "#5b46f5", "#6b7280", "#6b7280", "#b45309"

    st.markdown(
        f"""
        <style>
        :root {{
            --bg: {bg}; --fg: {fg}; --card: {card}; --border: {border};
            --accent: {accent}; --muted: {muted};
            --thought: {thought}; --note: {note};
        }}
        .stApp {{ background: var(--bg); color: var(--fg); }}
        .block-container {{ padding-top: 2rem !important; max-width: 1100px; }}
        h1, h2, h3, h4 {{ color: var(--fg); letter-spacing: -0.01em; }}
        .stTabs [data-baseweb="tab-list"] {{
            gap: 4px; border-bottom: 1px solid var(--border);
        }}
        .stTabs [data-baseweb="tab"] {{
            height: 44px; padding: 0 18px; background: transparent;
            border-radius: 10px 10px 0 0; color: var(--muted); font-weight: 500;
        }}
        .stTabs [aria-selected="true"] {{
            background: var(--card) !important; color: var(--fg) !important;
            border: 1px solid var(--border);
            border-bottom: 1px solid var(--card) !important;
        }}
        .stButton > button {{
            border-radius: 10px; border: 1px solid var(--border);
            background: var(--card); color: var(--fg);
            transition: all 0.15s ease;
        }}
        .stButton > button:hover {{
            border-color: var(--accent); color: var(--accent);
        }}
        .stChatMessage {{
            border-radius: 12px; border: 1px solid var(--border);
            background: var(--card);
        }}
        .thought {{
            color: var(--thought); font-style: italic; font-size: 0.9rem;
            margin-bottom: 4px; opacity: 0.85;
        }}
        .note {{
            color: var(--note); font-style: italic; font-size: 0.95rem;
            margin-top: 8px; padding-left: 10px;
            border-left: 3px solid var(--note);
        }}
        .stage-bar {{
            display: flex; align-items: center; gap: 10px;
            padding: 10px 14px; border-radius: 12px;
            border: 1px solid var(--border); background: var(--card);
            margin-bottom: 12px;
        }}
        .stage-bar .num {{ font-weight: 700; color: var(--accent); }}
        .stage-bar .title {{ font-weight: 600; color: var(--fg); }}
        .stage-bar .goal {{
            color: var(--muted); font-size: 0.85rem; margin-left: auto;
        }}
        .progress-wrap {{
            height: 6px; background: var(--border); border-radius: 3px;
            overflow: hidden; margin-bottom: 14px;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, var(--accent), #b388ff);
            transition: width 0.3s ease;
        }}
        .badge-eval {{
            display: inline-block; padding: 2px 10px; border-radius: 20px;
            font-size: 0.8rem; font-weight: 600; margin-bottom: 6px;
        }}
        .eval-bad {{ background: rgba(239,68,68,0.15); color: #ef4444; }}
        .eval-ok  {{ background: rgba(234,179,8,0.15); color: #eab308; }}
        .eval-top {{ background: rgba(34,197,94,0.15); color: #22c55e; }}
        @media (max-width: 640px) {{
            .block-container {{
                padding-left: 0.75rem !important;
                padding-right: 0.75rem !important;
            }}
            h1 {{ font-size: 1.4rem !important; }}
            .stChatInput textarea {{ font-size: 16px !important; }}
            .stage-bar {{ flex-wrap: wrap; }}
            .stage-bar .goal {{ margin-left: 0; width: 100%; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# === ПРОВЕРКА КОНТЕНТА ===
def contains_bad_words(text: str) -> bool:
    text_lower = text.lower()
    return any(bad in text_lower for bad in BAD_WORDS)


# === ЗАГРУЗКА БАЗЫ ЗНАНИЙ ===
@st.cache_data(show_spinner=False)
def load_knowledge_base(folder_path: str) -> dict:
    result = {
        "text": "", "files": 0, "ok": False, "message": "",
        "abs_path": os.path.abspath(folder_path), "file_list": [],
    }
    if not os.path.isdir(folder_path):
        result["message"] = (
            f"Папка не найдена: {result['abs_path']} (cwd: {os.getcwd()})"
        )
        return result

    texts = []
    for root, _dirs, files in os.walk(folder_path):
        for file in files:
            if not file.lower().endswith(".md"):
                continue
            if file.lower() in EXCLUDE_MD_NAMES:
                continue
            path = os.path.join(root, file)
            rel = os.path.relpath(path, folder_path)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    texts.append(f"\n\n--- {rel} ---\n\n{f.read()}")
                result["files"] += 1
                result["file_list"].append(rel)
            except Exception as e:
                texts.append(f"\n\n--- Ошибка чтения {rel}: {e} ---\n\n")

    result["text"] = "\n".join(texts)
    result["ok"] = result["files"] > 0
    result["message"] = (
        f"Загружено файлов: {result['files']}" if result["ok"]
        else f"В папке {result['abs_path']} не найдено .md-файлов"
    )
    return result


def get_knowledge_text() -> str:
    kb = load_knowledge_base(KNOWLEDGE_PATH)
    knowledge = kb["text"]
    if len(knowledge) > MAX_KNOWLEDGE_CHARS:
        knowledge = knowledge[:MAX_KNOWLEDGE_CHARS] + "\n\n[...база обрезана...]"
    return knowledge


# === GIGACHAT ===
def get_client() -> GigaChat:
    return GigaChat(
        credentials=st.secrets["GIGACHAT_KEY"],
        scope="GIGACHAT_API_PERS",
        model=MODEL,
        base_url=BASE_URL,
        verify_ssl_certs=False,
    )


def ask_client(messages: list) -> str:
    chat_messages = [
        ChatMessage(role=m["role"], content=m["content"]) for m in messages
    ]
    request = ChatCompletionRequest(messages=chat_messages)
    with get_client() as client:
        response = client.chat.create(request)
        return response.messages[0].content[0].text


# === ПАРСИНГ ОТВЕТОВ ===
_BLOCK_PATTERN = re.compile(
    r'^\s*(THOUGHT|SPEECH|STAGE[_\s]?DONE|KB|NOTE|EVAL|COMMENT|QUESTION)'
    r'\s*:\s*(.*)$',
    re.IGNORECASE,
)

# Убирает любые «скобочные» теги: [SPEECH], [/THOUGHT], [/THOГУ] и т.п.
_TAG_RE = re.compile(r'\[\s*/?\s*[A-ZА-ЯЁ_]{3,}\s*\]')


def _clean_tag_remnants(text: str) -> str:
    """Убирает осколки служебных тегов, если модель не послушалась."""
    return _TAG_RE.sub('', text).strip()


def _parse_blocks(text: str) -> dict:
    """Парсит формат 'KEY: value'. Поддерживает многострочные значения."""
    result = {}
    current_key = None
    buf = []
    for line in text.splitlines():
        m = _BLOCK_PATTERN.match(line)
        if m:
            if current_key:
                result[current_key] = "\n".join(buf).strip()
            key = m.group(1).upper().replace(" ", "_")
            if key == "STAGE_DONE":
                key = "STAGE_DONE"
            current_key = key
            buf = [m.group(2)]
        else:
            if current_key is not None:
                buf.append(line)
    if current_key:
        result[current_key] = "\n".join(buf).strip()
    return result


def _is_none_value(val: str) -> bool:
    if val is None:
        return True
    return val.strip().lower() in ("", "нет", "нет.", "none", "-", "n/a", "нечего")


def parse_thought_speech(text: str):
    """Возвращает (thought, speech, stage_done)."""
    blocks = _parse_blocks(text)
    if any(k in blocks for k in ("SPEECH", "THOUGHT", "STAGE_DONE")):
        thought = blocks.get("THOUGHT")
        if _is_none_value(thought):
            thought = None
        speech = blocks.get("SPEECH") or _clean_tag_remnants(text)
        stage_done = blocks.get("STAGE_DONE")
        if _is_none_value(stage_done):
            stage_done = None
        return thought, speech, stage_done
    return None, _clean_tag_remnants(text), None


def parse_kb_note(text: str):
    blocks = _parse_blocks(text)
    if any(k in blocks for k in ("KB", "NOTE")):
        kb_text = blocks.get("KB") or _clean_tag_remnants(text)
        note = blocks.get("NOTE")
        if _is_none_value(note):
            note = None
        return kb_text, note
    return _clean_tag_remnants(text), None


def parse_eval(text: str):
    """Возвращает (eval_value, comment, question)."""
    blocks = _parse_blocks(text)
    if "EVAL" in blocks:
        val = (blocks.get("EVAL") or "").strip().lower()
        if "превосход" in val:
            val = "превосходно"
        elif "плох" in val:
            val = "плохо"
        elif "хорош" in val:
            val = "хорошо"
        else:
            val = None
        comment = blocks.get("COMMENT") or ""
        question = blocks.get("QUESTION")
        if _is_none_value(question):
            question = None
        return val, comment, question
    return None, _clean_tag_remnants(text), None


# === ПРОМПТЫ ===
def build_trainer_prompt(situation, difficulty, psychotype, lpr, stage, lead) -> str:
    knowledge = get_knowledge_text()
    lead_str = "\n".join(f"- {k}: {v}" for k, v in lead.items() if v)

    return f"""Ты играешь роль КЛИЕНТА в тренажёре по продажам загородных домов.
Менеджер (пользователь) учится вести сделку по воронке продаж.

СИТУАЦИЯ:
{situation['context']}
Твоя цель: {situation['goal']}

ЗАЯВКА КЛИЕНТА (твои данные):
{lead_str}

УРОВЕНЬ СЛОЖНОСТИ:
{difficulty['prompt']}

ПСИХОТИП:
{psychotype['prompt']}

РОЛЬ В СДЕЛКЕ:
{lpr['prompt']}

ТЕКУЩИЙ ЭТАП ВОРОНКИ: {stage['title']}
Цель менеджера на этом этапе: {stage['goal']}
Правила этапа: {stage['rules']}

БАЗА ЗНАНИЙ О ПРОДУКТЕ КОМПАНИИ:
{knowledge}

ФОРМАТ ОТВЕТА — СТРОГО три блока, каждый начинается с метки
на отдельной строке:

THOUGHT: <короткая мысль или жест, ИЛИ слово "нет", если внутри
         ничего значимого не происходит>
SPEECH: <твоя реплика как клиента, 1–3 предложения>
STAGE_DONE: <короткое объяснение, если цель текущего этапа достигнута,
             ИНАЧЕ слово "нет">

ПРАВИЛА ФОРМАТА:
- Никаких других тегов, скобок, разметки — только эти три метки.
- SPEECH обязателен. THOUGHT и STAGE_DONE — только по делу.
- Не используй квадратные скобки, HTML, Markdown-заголовки.
- Не пиши ничего до первой метки и после последней строки.

ПРАВИЛА РОЛИ:
- Не выходи из роли. Ты — клиент, а не ассистент.
- Задавай вопросы, сомневайся, торгуйся — по своему психотипу.
- Если менеджер давит или грубит — реагируй по психотипу.
- Если менеджер пишет что-то неприличное — не поддерживай тему."""


def build_kb_prompt() -> str:
    knowledge = get_knowledge_text()
    return f"""Ты — внутренний ассистент-эксперт по продукту компании
(загородные дома). Отвечай на вопросы сотрудников, опираясь на базу знаний.

БАЗА ЗНАНИЙ:
{knowledge}

ФОРМАТ ОТВЕТА — СТРОГО два блока:

KB: <ответ, основанный ТОЛЬКО на базе знаний. Структурированно:
     списки, короткие абзацы. Если ответа в базе нет — так и напиши>
NOTE: <осторожный комментарий, если данные могли устареть
       или измениться: «возможно, изменилось», «рекомендую проверить».
       Если сомнений нет — напиши "нет">

ПРАВИЛА ФОРМАТА:
- Две метки, каждая с новой строки.
- Никаких других тегов, скобок, разметки.
- KB обязателен.

ПРАВИЛА СОДЕРЖАНИЯ:
- Не выдумывай факты, цены, сроки, характеристики.
- Тон — деловой, дружелюбный, без «воды»."""


def build_objection_prompt(situation, difficulty, psychotype, lpr, history_text) -> str:
    return f"""Ты — клиент в тренажёре по работе с возражениями.

КОНТЕКСТ:
Ситуация: {situation['title']}
Сложность: {difficulty['title']}
Психотип: {psychotype['title']}
Роль в сделке: {lpr['title']}

{situation['context']}

ИСТОРИЯ ДИАЛОГА:
{history_text}

ЗАДАЧА:
Сгенерируй ОДНО реалистичное возражение клиента, соответствующее
психотипу и сложности. Верни только текст возражения без пояснений
и без меток."""


def build_objection_eval_prompt() -> str:
    return """Ты — руководитель отдела продаж. Оцени ответ менеджера
на возражение клиента.

Критерии:
- плохо — не отработал, ушёл от темы, давит, спорит
- хорошо — ответил по делу, но без углубления
- превосходно — снял напряжение, привёл аргумент, повёл к следующему шагу

ФОРМАТ ОТВЕТА — СТРОГО три блока:

EVAL: плохо | хорошо | превосходно
COMMENT: <1–2 предложения: что было хорошо / что улучшить>
QUESTION: <один уточняющий вопрос клиенту, если возражение НЕ закрыто;
           иначе напиши "нет">

ПРАВИЛА ФОРМАТА:
- Три метки, каждая с новой строки.
- В EVAL — ровно одно из трёх слов, без кавычек и пояснений.
- Никаких других тегов, скобок, разметки."""


def build_advisor_prompt(knowledge) -> str:
    return f"""Ты — наставник менеджера по продажам загородных домов.
Тебе передают рабочие комментарии менеджера из CRM (Битрикс24).

Твоя задача:
1. Определить, на каком этапе воронки находится клиент (по тексту).
2. Дать совет: что делать дальше, чтобы продвинуть клиента
   к следующему этапу или к подписанию договора.
3. Опираться на базу знаний компании, если это релевантно.

ЭТАПЫ ВОРОНКИ:
{chr(10).join(f'- {s["title"]}: {s["goal"]}' for s in STAGES)}

БАЗА ЗНАНИЙ:
{knowledge}

ПРАВИЛА:
- Формат — свободный текст.
- Тон — деловой, конкретный, без «воды».
- Если данных мало — честно скажи, чего не хватает.
- Если пользователь задаёт уточняющие вопросы — отвечай по существу."""


def build_eval_prompt(messages: list, scenario_title: str) -> str:
    dialog_text = "\n".join(
        f"{m['role']}: {m['content']}" for m in messages[1:]
    )
    return f"""Ты — руководитель отдела продаж. Оцени менеджера по 5 критериям от 1 до 10:
1. Выявление потребностей
2. Презентация ценности
3. Отработка возражений
4. Закрытие сделки / вывод на следующий шаг
5. Тон и уверенность

Сценарий: {scenario_title}
Диалог:
{dialog_text}

Верни ответ в формате:
Выявление потребностей: X/10
Презентация ценности: X/10
Отработка возражений: X/10
Закрытие: X/10
Тон: X/10
Общий комментарий: ..."""


# === ЛОГИ ===
def _append_csv(path: str, header: list, row: list) -> None:
    exists = os.path.isfile(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(header)
        w.writerow(row)


def save_trainer_log(meta: dict, messages: list, evaluation: str) -> None:
    _append_csv(
        "logs.csv",
        ["datetime", "user_name", "user_phone", "situation", "difficulty",
         "psychotype", "lpr", "stage", "dialog", "evaluation"],
        [
            datetime.now(),
            st.session_state.user["name"],
            st.session_state.user["phone"],
            meta["situation"], meta["difficulty"],
            meta["psychotype"], meta["lpr"], meta["stage"],
            str(messages[1:]), evaluation,
        ],
    )


def save_kb_log(question: str, answer: str) -> None:
    _append_csv(
        "kb_logs.csv",
        ["datetime", "user_name", "user_phone", "question", "answer"],
        [
            datetime.now(),
            st.session_state.user["name"],
            st.session_state.user["phone"],
            question, answer,
        ],
    )


def save_advisor_log(question: str, answer: str) -> None:
    _append_csv(
        "advisor_logs.csv",
        ["datetime", "user_name", "user_phone", "question", "answer"],
        [
            datetime.now(),
            st.session_state.user["name"],
            st.session_state.user["phone"],
            question, answer,
        ],
    )


# === COOKIE ===
@st.cache_resource(show_spinner=False)
def _get_cookie_manager_cached():
    """CookieManager создаётся один раз на весь процесс.

    Без @st.cache_resource Streamlit ругается на дубликат ключа,
    потому что внутри CookieManager жёстко прописан свой key.
    """
    if not COOKIE_AVAILABLE:
        return None
    return stx.CookieManager(key="cookie_mgr_v2")


def get_cookie_manager():
    return _get_cookie_manager_cached()


def restore_session_from_cookie() -> None:
    if "user" in st.session_state:
        return
    cm = get_cookie_manager()
    if cm is None:
        return
    try:
        raw = cm.get(COOKIE_NAME)
    except Exception:
        raw = None
    if not raw:
        return
    try:
        data = json.loads(raw)
        if data.get("name") and data.get("phone"):
            st.session_state.user = {
                "name": data["name"],
                "phone": data["phone"],
            }
    except Exception:
        pass


def save_session_cookie(user: dict) -> None:
    cm = get_cookie_manager()
    if cm is None:
        return
    try:
        cm.set(
            COOKIE_NAME,
            json.dumps(user),
            expires_at=datetime.now() + timedelta(days=COOKIE_DAYS),
        )
    except Exception:
        pass


def clear_session_cookie() -> None:
    cm = get_cookie_manager()
    if cm is None:
        return
    try:
        cm.delete(COOKIE_NAME)
    except Exception:
        pass


# === UI-ХЕЛПЕРЫ ===
def render_status_indicator(kb: dict) -> None:
    color = "#22c55e" if kb["ok"] else "#ef4444"
    label = (
        f"База знаний загружена · {kb['message']}" if kb["ok"]
        else f"База знаний НЕ загружена · {kb['message']}"
    )
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:8px;
                    padding:6px 12px; border-radius:8px;
                    background:rgba(127,127,127,0.08); margin-bottom:8px;">
            <span style="display:inline-block; width:12px; height:12px;
                         border-radius:50%; background:{color};
                         box-shadow:0 0 6px {color};"></span>
            <span style="font-size:14px;">{label}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kb_diagnostics(kb: dict, reload_key: str) -> None:
    with st.expander("🔧 Диагностика базы знаний", expanded=not kb["ok"]):
        st.code(f"KNOWLEDGE_PATH = {KNOWLEDGE_PATH}", language="text")
        st.code(f"Абсолютный путь = {kb['abs_path']}", language="text")
        st.code(f"Текущая директория = {os.getcwd()}", language="text")
        if kb["file_list"]:
            st.write("Найденные .md-файлы:")
            for name in kb["file_list"]:
                st.write(f"• {name}")
        else:
            st.write("Ни одного .md-файла не найдено.")
        if st.button("♻️ Перезагрузить базу", key=reload_key):
            st.cache_data.clear()
            st.rerun()


def render_stage_bar(stage_index: int) -> None:
    stage = STAGES[stage_index]
    total = len(STAGES)
    pct = int(((stage_index + 1) / total) * 100)
    st.markdown(
        f"""
        <div class="stage-bar">
            <span class="num">{stage_index + 1}/{total}</span>
            <span class="title">{stage['title']}</span>
            <span class="goal">{stage['goal']}</span>
        </div>
        <div class="progress-wrap">
            <div class="progress-fill" style="width:{pct}%"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_assistant_message(content: str) -> None:
    """Рендер реплики клиента с мыслью/жестом."""
    thought, speech, _ = parse_thought_speech(content)
    if thought:
        st.markdown(
            f'<div class="thought">💭 {thought}</div>',
            unsafe_allow_html=True,
        )
    st.markdown(speech)


# === АВТОРИЗАЦИЯ ===
def render_login() -> None:
    st.title("🎭 AI-тренажёр для отдела продаж")
    st.markdown("### Вход")
    st.caption("Заполните данные, чтобы начать тренировку.")

    with st.form("login_form"):
        name = st.text_input("Имя", placeholder="Например: Иван")
        phone = st.text_input("Телефон", placeholder="+79999999999")
        submitted = st.form_submit_button("Войти")

        if submitted:
            name_clean = name.strip()
            phone_clean = phone.strip()
            if len(name_clean) < MIN_NAME_LEN:
                st.error("Введите имя (минимум 2 символа).")
            elif len(phone_clean) < MIN_PHONE_LEN:
                st.error("Введите корректный номер телефона.")
            else:
                user = {"name": name_clean, "phone": phone_clean}
                st.session_state.user = user
                save_session_cookie(user)
                st.rerun()


# === САЙДБАР ===
def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(f"**👤 {st.session_state.user['name']}**")
        st.caption(f"📞 {st.session_state.user['phone']}")
        st.divider()

        theme = st.radio(
            "Тема",
            ["dark", "light"],
            format_func=lambda x: "🌙 Тёмная" if x == "dark" else "☀️ Светлая",
            index=0 if st.session_state.get("theme", "dark") == "dark" else 1,
            key="theme_radio",
        )
        if theme != st.session_state.get("theme"):
            st.session_state.theme = theme
            st.rerun()

        st.divider()
        if st.button("Выйти", use_container_width=True):
            clear_session_cookie()
            for k in ["user", "messages", "config_key", "stage_index",
                      "trainer_started", "lead", "kb_messages",
                      "objection_messages", "advisor_messages",
                      "objection_saved", "trainer_meta"]:
                st.session_state.pop(k, None)
            st.rerun()


# === НАСТРОЙКА ТРЕНАЖЁРА ===
LEAD_FIELD_ORDER = [
    ("source", "Источник заявки"),
    ("area", "Метраж дома"),
    ("floors", "Этажность"),
    ("bedrooms", "Спален"),
    ("package", "Комплектация"),
    ("payment", "Форма оплаты"),
    ("timeline", "Срок строительства"),
    ("land", "Участок"),
    ("show", "Показ объектов"),
    ("estimate_channel", "Куда направить смету"),
    ("name", "Имя клиента"),
    ("phone", "Телефон клиента"),
]


def default_lead(situation, psychotype) -> dict:
    return {
        "source": "Заявка с сайта",
        "area": "100–120 м²",
        "floors": "Двухэтажный",
        "bedrooms": "4",
        "package": "Тёплый контур",
        "payment": "Ипотека",
        "timeline": "Через 6 месяцев",
        "land": "Есть",
        "show": "Да, хочет посмотреть построенный дом",
        "estimate_channel": "Max",
        "name": "Клиент",
        "phone": "+7 999 999 99 99",
    }


def generate_lead_with_ai(situation, difficulty, psychotype, lpr) -> dict:
    prompt = f"""Сгенерируй реалистичную заявку на строительство загородного дома.

Параметры:
- Ситуация: {situation['title']}
- Сложность: {difficulty['title']}
- Психотип: {psychotype['title']}
- Роль в сделке: {lpr['title']}

Верни СТРОГО JSON без пояснений с полями:
source, area, floors, bedrooms, package, payment, timeline, land, show,
estimate_channel, name, phone
Значения — короткие строки на русском."""
    try:
        raw = ask_client([{"role": "user", "content": prompt}])
        raw = raw.strip()
        raw = re.sub(r"^```(json)?|```$", "", raw, flags=re.MULTILINE).strip()
        data = json.loads(raw)
        result = default_lead(situation, psychotype)
        for k, _ in LEAD_FIELD_ORDER:
            if k in data and data[k]:
                result[k] = str(data[k])
        return result
    except Exception:
        return default_lead(situation, psychotype)


def render_trainer_setup() -> None:
    st.subheader("⚙️ Настройка тренировки")

    kb = load_knowledge_base(KNOWLEDGE_PATH)
    render_status_indicator(kb)
    render_kb_diagnostics(kb, reload_key="reload_kb_trainer")

    col1, col2 = st.columns(2)
    with col1:
        sit = st.selectbox("Ситуация", SITUATIONS, format_func=lambda x: x["title"])
        psych = st.selectbox("Психотип", PSYCHOTYPES, format_func=lambda x: x["title"])
    with col2:
        diff = st.selectbox("Сложность", DIFFICULTIES, format_func=lambda x: x["title"])
        lpr = st.selectbox("ЛПР", LPR, format_func=lambda x: x["title"])

    default_stage = st.session_state.get("stage_index", 0)
    stage_choice = st.selectbox(
        "Этап воронки",
        options=list(range(len(STAGES))),
        format_func=lambda i: f"{i + 1}. {STAGES[i]['title']}",
        index=default_stage,
    )

    st.markdown("### 📋 Заявка клиента")
    st.caption("Заполняется автоматически, можно скорректировать под клиента.")

    if "lead" not in st.session_state:
        st.session_state.lead = default_lead(sit, psych)

    col_a, col_b = st.columns([1, 1])
    with col_a:
        if st.button("🎲 Сгенерировать через ИИ", use_container_width=True):
            with st.spinner("Генерирую заявку..."):
                st.session_state.lead = generate_lead_with_ai(sit, diff, psych, lpr)
            st.rerun()
    with col_b:
        if st.button("↺ Сбросить заявку", use_container_width=True):
            st.session_state.lead = default_lead(sit, psych)
            st.rerun()

    lead = st.session_state.lead
    new_lead = {}
    col1, col2 = st.columns(2)
    for i, (key, label) in enumerate(LEAD_FIELD_ORDER):
        target = col1 if i % 2 == 0 else col2
        with target:
            new_lead[key] = st.text_input(
                label, value=lead.get(key, ""), key=f"lead_{key}"
            )
    st.session_state.lead = new_lead

    if st.button("🚀 Начать тренировку", type="primary", use_container_width=True):
        st.session_state.stage_index = stage_choice
        st.session_state.trainer_started = True
        st.session_state.messages = [
            {
                "role": "system",
                "content": build_trainer_prompt(
                    sit, diff, psych, lpr,
                    STAGES[stage_choice],
                    st.session_state.lead,
                ),
            }
        ]
        st.session_state.trainer_meta = {
            "situation": sit["title"],
            "difficulty": diff["title"],
            "psychotype": psych["title"],
            "lpr": lpr["title"],
        }
        st.rerun()


# === ТРЕНАЖЁР ===
def render_trainer_chat() -> None:
    stage_index = st.session_state.get("stage_index", 0)
    render_stage_bar(stage_index)

    meta = st.session_state.get("trainer_meta", {})

    with st.expander("📋 Заявка и этап"):
        st.markdown(f"**Этап:** {STAGES[stage_index]['title']}")
        st.markdown(f"**Цель:** {STAGES[stage_index]['goal']}")
        st.markdown("**Заявка:**")
        for k, label in LEAD_FIELD_ORDER:
            val = st.session_state.lead.get(k, "")
            if val:
                st.markdown(f"- **{label}:** {val}")

    with st.expander("🔍 Посмотреть текущий промпт клиента"):
        st.text(st.session_state.messages[0]["content"])

    # --- Кнопки управления: ВЫШЕ истории, чтобы не оказались под полем ввода ---
    col1, col2 = st.columns(2)
    with col1:
        eval_clicked = st.button(
            "📊 Оценить диалог",
            use_container_width=True,
            disabled=len(st.session_state.messages) <= 3,
        )
    with col2:
        if st.button("🔄 Начать заново", use_container_width=True):
            for k in ["trainer_started", "messages", "config_key", "stage_index"]:
                st.session_state.pop(k, None)
            st.rerun()

    if eval_clicked:
        with st.spinner("Анализируем..."):
            try:
                evaluation = ask_client([
                    {
                        "role": "user",
                        "content": build_eval_prompt(
                            st.session_state.messages,
                            f"{meta.get('situation','')} / "
                            f"{meta.get('difficulty','')} / "
                            f"{meta.get('psychotype','')} / "
                            f"{meta.get('lpr','')} / "
                            f"{STAGES[stage_index]['title']}",
                        ),
                    }
                ])
                st.subheader("Результат оценки")
                st.text(evaluation)
                save_trainer_log(
                    {**meta, "stage": STAGES[stage_index]["title"]},
                    st.session_state.messages,
                    evaluation,
                )
                st.success("Диалог сохранён в logs.csv")
            except Exception as e:
                st.error(f"Не удалось оценить: {e}")

    # --- История диалога ---
    for msg in st.session_state.messages[1:]:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                render_assistant_message(msg["content"])
            else:
                st.write(msg["content"])

    # --- Поле ввода: ВСЕГДА последнее ---
    if prompt := st.chat_input("Ваш ответ клиенту..."):
        with st.chat_message("user"):
            st.write(prompt)

        if contains_bad_words(prompt):
            with st.chat_message("assistant"):
                st.write(BLOCK_MESSAGE)
            st.session_state.messages.append(
                {"role": "assistant", "content": BLOCK_MESSAGE}
            )
            return

        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("assistant"):
            with st.spinner("Клиент думает..."):
                try:
                    answer = ask_client(st.session_state.messages)
                except Exception as e:
                    answer = f"Ошибка: {e}"
            thought, speech, stage_done = parse_thought_speech(answer)
            if thought:
                st.markdown(
                    f'<div class="thought">💭 {thought}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown(speech)
            if stage_done:
                st.success(f"✅ {stage_done}")

        st.session_state.messages.append(
            {"role": "assistant", "content": answer}
        )

        if stage_done:
            new_idx = min(stage_index + 1, len(STAGES) - 1)
            if new_idx != stage_index:
                st.session_state.stage_index = new_idx
                sit = next(
                    (s for s in SITUATIONS if s["title"] == meta.get("situation")),
                    SITUATIONS[0],
                )
                diff = next(
                    (s for s in DIFFICULTIES if s["title"] == meta.get("difficulty")),
                    DIFFICULTIES[0],
                )
                psych = next(
                    (s for s in PSYCHOTYPES if s["title"] == meta.get("psychotype")),
                    PSYCHOTYPES[0],
                )
                lpr = next(
                    (s for s in LPR if s["title"] == meta.get("lpr")),
                    LPR[0],
                )
                st.session_state.messages[0] = {
                    "role": "system",
                    "content": build_trainer_prompt(
                        sit, diff, psych, lpr,
                        STAGES[new_idx],
                        st.session_state.lead,
                    ),
                }
                st.rerun()

def render_trainer_tab() -> None:
    if not st.session_state.get("trainer_started"):
        render_trainer_setup()
    else:
        render_trainer_chat()


# === ВОЗРАЖЕНИЯ ===
def render_objections_tab() -> None:
    st.subheader("🛡️ Работа с возражениями")
    st.caption("Возражения генерируются с учётом параметров из тренажёра.")

    meta = st.session_state.get("trainer_meta")
    if not meta:
        st.info(
            "Сначала настройте тренажёр — параметры (Ситуация, Сложность, "
            "Психотип, ЛПР) подтянутся автоматически."
        )
        return

    sit = next((s for s in SITUATIONS if s["title"] == meta["situation"]), None)
    diff = next((s for s in DIFFICULTIES if s["title"] == meta["difficulty"]), None)
    psych = next((s for s in PSYCHOTYPES if s["title"] == meta["psychotype"]), None)
    lpr = next((s for s in LPR if s["title"] == meta["lpr"]), None)

    if not all([sit, diff, psych, lpr]):
        st.warning("Не удалось подтянуть параметры тренажёра.")
        return

    st.markdown(
        f"**Параметры:** {sit['title']} · {diff['title']} · "
        f"{psych['title']} · {lpr['title']}"
    )

    if "objection_messages" not in st.session_state:
        st.session_state.objection_messages = []
    if "objection_saved" not in st.session_state:
        st.session_state.objection_saved = []

    # --- Кнопки управления: выше истории ---
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.button("🎯 Новое возражение", use_container_width=True):
            history_text = "\n".join(
                f"{m['role']}: {m['content']}"
                for m in st.session_state.objection_messages[-6:]
            ) or "(диалог ещё не начат)"
            with st.spinner("Генерирую..."):
                try:
                    prompt = build_objection_prompt(
                        sit, diff, psych, lpr, history_text
                    )
                    raw = ask_client([{"role": "user", "content": prompt}])
                    st.session_state.objection_messages.append(
                        {"role": "assistant", "content": raw.strip()}
                    )
                except Exception as e:
                    st.error(f"Ошибка: {e}")
            st.rerun()
    with col2:
        if st.button("🔄 Очистить", use_container_width=True):
            st.session_state.objection_messages = []
            st.rerun()

    # --- Избранное: тоже выше поля ввода ---
    if st.session_state.objection_saved:
        with st.expander(
            f"⭐ Избранные возражения ({len(st.session_state.objection_saved)})"
        ):
            for i, o in enumerate(st.session_state.objection_saved):
                st.markdown(f"**{i + 1}.** {o['text']}")

    # --- История ---
    for idx, msg in enumerate(st.session_state.objection_messages):
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                st.write(msg["content"])
                if st.button(
                    "⭐ Сохранить в избранное",
                    key=f"save_obj_{idx}",
                    help="Добавить это возражение в список на сессию",
                ):
                    text = msg["content"]
                    if text not in [o["text"] for o in st.session_state.objection_saved]:
                        st.session_state.objection_saved.append({"text": text})
                        st.success("Сохранено")
            else:
                st.write(msg["content"])
                eval_val = msg.get("eval")
                if eval_val:
                    cls = {
                        "плохо": "eval-bad",
                        "хорошо": "eval-ok",
                        "превосходно": "eval-top",
                    }.get(eval_val, "eval-ok")
                    st.markdown(
                        f'<span class="badge-eval {cls}">{eval_val}</span>',
                        unsafe_allow_html=True,
                    )
                    if msg.get("eval_comment"):
                        st.caption(msg["eval_comment"])

    # --- Поле ввода: последнее ---
    if prompt := st.chat_input("Ваш ответ на возражение..."):
        with st.chat_message("user"):
            st.write(prompt)

        st.session_state.objection_messages.append(
            {"role": "user", "content": prompt}
        )

        with st.chat_message("assistant"):
            with st.spinner("Оцениваю..."):
                try:
                    history = "\n".join(
                        f"{m['role']}: {m['content']}"
                        for m in st.session_state.objection_messages
                    )
                    full_prompt = (
                        build_objection_eval_prompt()
                        + "\n\nДИАЛОГ:\n" + history
                    )
                    raw = ask_client([{"role": "user", "content": full_prompt}])
                    eval_val, comment, question = parse_eval(raw)

                    cls = {
                        "плохо": "eval-bad",
                        "хорошо": "eval-ok",
                        "превосходно": "eval-top",
                    }.get(eval_val, "eval-ok")
                    st.markdown(
                        f'<span class="badge-eval {cls}">'
                        f'{eval_val or "оценка"}</span>',
                        unsafe_allow_html=True,
                    )
                    if comment:
                        st.write(comment)
                    if question:
                        st.markdown(f"**Клиент:** {question}")

                    st.session_state.objection_messages[-1]["eval"] = eval_val
                    st.session_state.objection_messages[-1]["eval_comment"] = comment

                    next_msg = question or comment
                    if next_msg:
                        st.session_state.objection_messages.append(
                            {"role": "assistant", "content": next_msg}
                        )
                except Exception as e:
                    st.error(f"Ошибка: {e}")

# === БАЗА ЗНАНИЙ ===
def render_kb_tab() -> None:
    st.subheader("📚 База знаний")
    st.caption("Ответ формируется по базе. Комментарий — знания модели.")

    kb = load_knowledge_base(KNOWLEDGE_PATH)
    render_status_indicator(kb)
    render_kb_diagnostics(kb, reload_key="reload_kb_chat")

    if "kb_messages" not in st.session_state:
        st.session_state.kb_messages = []

    col_a, col_b = st.columns([3, 1])
    with col_b:
        if st.button("🔄 Очистить чат", use_container_width=True, key="kb_clear"):
            st.session_state.kb_messages = []
            st.rerun()

    for msg in st.session_state.kb_messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                kb_text, note = parse_kb_note(msg["content"])
                st.markdown(kb_text)
                if note:
                    st.markdown(
                        f'<div class="note">💡 {note}</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.markdown(msg["content"])

    if not st.session_state.kb_messages:
        st.markdown("**Примеры вопросов:**")
        examples = [
            "Какие типовые комплектации домов есть?",
            "Какие сроки строительства?",
            "Какие условия семейной ипотеки?",
        ]
        cols = st.columns(len(examples))
        for c, ex in zip(cols, examples):
            if c.button(ex, use_container_width=True, key=f"kb_ex_{ex[:10]}"):
                st.session_state.kb_pending = ex
                st.rerun()

    pending = st.session_state.pop("kb_pending", None)
    question = st.chat_input("Ваш вопрос по базе знаний...") or pending

    if question:
        with st.chat_message("user"):
            st.markdown(question)
        st.session_state.kb_messages.append({"role": "user", "content": question})

        with st.chat_message("assistant"):
            with st.spinner("Ищу в базе знаний..."):
                try:
                    answer = ask_client([
                        {"role": "system", "content": build_kb_prompt()},
                        *st.session_state.kb_messages[:-1],
                        {"role": "user", "content": question},
                    ])
                except Exception as e:
                    answer = f"Ошибка: {e}"
                kb_text, note = parse_kb_note(answer)
                st.markdown(kb_text)
                if note:
                    st.markdown(
                        f'<div class="note">💡 {note}</div>',
                        unsafe_allow_html=True,
                    )
        st.session_state.kb_messages.append(
            {"role": "assistant", "content": answer}
        )
        try:
            save_kb_log(question, answer)
        except Exception:
            pass


# === СОВЕТНИК ===
def render_advisor_tab() -> None:
    st.subheader("🧭 Советник")
    st.caption(
        "Вставьте комментарии из Битрикс24 — ассистент определит этап "
        "и подскажет, что делать дальше."
    )

    if "advisor_messages" not in st.session_state:
        st.session_state.advisor_messages = []

    col_a, col_b = st.columns([3, 1])
    with col_b:
        if st.button("🔄 Очистить чат", use_container_width=True, key="adv_clear"):
            st.session_state.advisor_messages = []
            st.rerun()

    for msg in st.session_state.advisor_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if not st.session_state.advisor_messages:
        st.markdown("**Пример запроса:**")
        st.code(
            "Клиент с Авито, дом 120 м², тёплый контур, ипотека. "
            "Созвонились, участок есть, бюджет до 8 млн, планирует "
            "строиться весной. На встречу пока не готов.",
            language="text",
        )

    question = st.chat_input("Вставьте комментарии из CRM или задайте вопрос...")

    if question:
        with st.chat_message("user"):
            st.markdown(question)
        st.session_state.advisor_messages.append(
            {"role": "user", "content": question}
        )

        with st.chat_message("assistant"):
            with st.spinner("Анализирую..."):
                try:
                    knowledge = get_knowledge_text()
                    answer = ask_client([
                        {
                            "role": "system",
                            "content": build_advisor_prompt(knowledge),
                        },
                        *st.session_state.advisor_messages[:-1],
                        {"role": "user", "content": question},
                    ])
                except Exception as e:
                    answer = f"Ошибка: {e}"
                st.markdown(answer)
        st.session_state.advisor_messages.append(
            {"role": "assistant", "content": answer}
        )
        try:
            save_advisor_log(question, answer)
        except Exception:
            pass


# === ГЛАВНАЯ ===
def main() -> None:
    st.set_page_config(
        page_title="AI-тренажёр продаж",
        page_icon="🎭",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    if "theme" not in st.session_state:
        st.session_state.theme = "dark"

    inject_css()
    restore_session_from_cookie()

    if "user" not in st.session_state:
        render_login()
        return

    render_sidebar()

    if not COOKIE_AVAILABLE:
        st.caption(
            "ℹ️ Для сохранения сессии между визитами добавьте в "
            "requirements.txt библиотеку `extra-streamlit-components`."
        )

    tab_trainer, tab_obj, tab_kb, tab_advisor = st.tabs([
        "🎭 Тренажёр",
        "🛡️ Возражения",
        "📚 База знаний",
        "🧭 Советник",
    ])

    with tab_trainer:
        render_trainer_tab()
    with tab_obj:
        render_objections_tab()
    with tab_kb:
        render_kb_tab()
    with tab_advisor:
        render_advisor_tab()


if __name__ == "__main__":
    main()
