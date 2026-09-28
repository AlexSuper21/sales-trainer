import os
import csv
from datetime import datetime

import streamlit as st
from gigachat import GigaChat
from gigachat.models import ChatCompletionRequest, ChatMessage

from scenarios import SITUATIONS, DIFFICULTIES, PSYCHOTYPES, LPR


# === НАСТРОЙКИ ===
MODEL = "GigaChat-2"
BASE_URL = "https://api.giga.chat/v1"

MAX_KNOWLEDGE_CHARS = 15000
MIN_NAME_LEN = 2
MIN_PHONE_LEN = 5


def _resolve_knowledge_path() -> str:
    """Надёжно определяет путь к базе знаний.

    - Безопасно читает secrets (не падает, если файла нет или версия старая).
    - Относительный путь резолвит от папки, где лежит этот файл.
    """
    raw = None
    try:
        raw = st.secrets.get("KNOWLEDGE_PATH", None)
    except Exception:
        raw = None

    path = raw or "knowledge"

    if not os.path.isabs(path):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            base_dir = os.getcwd()
        path = os.path.join(base_dir, path)

    return os.path.normpath(path)


KNOWLEDGE_PATH = _resolve_knowledge_path()


# Список недопустимых слов (нижний регистр, проверка по подстроке)
BAD_WORDS = [
    # Русский мат
    "хуй", "хуя", "хую", "хуем", "хуе", "хуё", "хуйн", "хуёв", "хуев",
    "пизд", "пизж",
    "бляд", "блять", "блядь",
    "ебат", "ебал", "ебет", "ебут", "ебан", "ёбан", "ебуч", "ебля",
    "ебись", "еби", "ёбат", "ёбал", "ёбет", "ёбут",
    "нахуй", "нахуя", "похуй", "похуя", "охуе",
    "залуп", "манда", "манду", "манде",
    # Ругательства
    "сука", "суки", "сучк",
    "мудак", "мудил",
    "пидор", "пидар", "пидр",
    "гандон", "гондон",
    "долбоеб", "долбоёб",
    "шлюх", "ублюд",
    # Английские
    "fuck", "shit", "bitch", "cunt", "dick", "pussy",
    "asshole", "motherfucker",
]

BLOCK_MESSAGE = (
    "⛔ Контент 18+ не допустим для менеджера. "
    "Вернитесь к предыдущему сообщению."
)


# === MOBILE CSS ===
def inject_css() -> None:
    st.markdown(
        """
        <style>
        @media (max-width: 640px) {
            .block-container {
                padding-left: 0.75rem !important;
                padding-right: 0.75rem !important;
                padding-top: 1rem !important;
            }
            h1 {
                font-size: 1.4rem !important;
            }
            .stChatInput textarea {
                font-size: 16px !important;
            }
            .stSelectbox label, .stTextInput label {
                font-size: 14px !important;
            }
            div[data-testid="column"] {
                width: 100% !important;
                flex: 1 1 100% !important;
                min-width: 100% !important;
            }
        }
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
        "text": "",
        "files": 0,
        "ok": False,
        "message": "",
        "abs_path": os.path.abspath(folder_path),
        "file_list": [],
    }

    if not os.path.isdir(folder_path):
        result["message"] = (
            f"Папка не найдена: {result['abs_path']} "
            f"(cwd: {os.getcwd()})"
        )
        return result

    texts = []
    for root, _dirs, files in os.walk(folder_path):
        for file in files:
            if file.lower().endswith(".md"):
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
        f"Загружено файлов: {result['files']}"
        if result["ok"]
        else f"В папке {result['abs_path']} не найдено .md-файлов"
    )
    return result


def get_knowledge_text() -> str:
    """Возвращает обрезанный под лимит текст базы знаний."""
    kb = load_knowledge_base(KNOWLEDGE_PATH)
    knowledge = kb["text"]
    if len(knowledge) > MAX_KNOWLEDGE_CHARS:
        knowledge = knowledge[:MAX_KNOWLEDGE_CHARS] + "\n\n[...база обрезана...]"
    return knowledge


# === РАБОТА С GIGACHAT ===
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


def evaluate_dialog(messages: list, scenario_title: str) -> str:
    dialog_text = "\n".join(
        f"{m['role']}: {m['content']}" for m in messages[1:]
    )
    eval_prompt = f"""Ты — руководитель отдела продаж. Оцени менеджера по 5 критериям от 1 до 10:
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
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content=eval_prompt)]
    )
    with get_client() as client:
        response = client.chat.create(request)
        return response.messages[0].content[0].text


# === СБОРКА ПРОМПТА ТРЕНАЖЁРА ===
def build_system_prompt(situation, difficulty, psychotype, lpr) -> str:
    knowledge = get_knowledge_text()

    return f"""Ты играешь роль клиента в тренажёре по продажам загородных домов.

СИТУАЦИЯ:
{situation['context']}
Твоя цель: {situation['goal']}

УРОВЕНЬ СЛОЖНОСТИ:
{difficulty['prompt']}

ПСИХОТИП:
{psychotype['prompt']}

РОЛЬ В СДЕЛКЕ:
{lpr['prompt']}

БАЗА ЗНАНИЙ О ПРОДУКТЕ КОМПАНИИ:
{knowledge}

ВАЖНО:
- Не выходи из роли. Ты — клиент, а не ассистент.
- Отвечай кратко, как в мессенджере (1–3 предложения).
- Задавай вопросы, сомневайся, торгуйся — в зависимости от уровня и психотипа.
- Если менеджер давит или грубит — реагируй в соответствии со своим психотипом.
- Если менеджер пишет что-то неприличное — не поддерживай тему."""


# === СБОРКА ПРОМПТА РЕЖИМА "БАЗА ЗНАНИЙ" ===
def build_kb_system_prompt() -> str:
    knowledge = get_knowledge_text()
    return f"""Ты — внутренний ассистент-эксперт по продукту компании
(загородные дома). Твоя задача — отвечать на вопросы сотрудников,
опираясь ИСКЛЮЧИТЕЛЬНО на базу знаний ниже.

БАЗА ЗНАНИЙ:
{knowledge}

ПРАВИЛА:
- Отвечай по существу, структурированно (списки, короткие абзацы).
- Если ответа в базе нет — честно скажи: «В базе знаний нет информации
  по этому вопросу» и предложи уточнить у руководителя.
- Не выдумывай факты, цены, сроки и характеристики, которых нет в базе.
- При необходимости цитируй источник (имя .md-файла в блоке «--- файл ---»).
- Тон — деловой, дружелюбный, без «воды».
"""


def ask_kb(question: str, history: list) -> str:
    messages = [{"role": "system", "content": build_kb_system_prompt()}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})
    return ask_client(messages)


# === СОХРАНЕНИЕ ЛОГОВ ===
def save_log(meta: dict, messages: list, evaluation: str) -> None:
    log_file = "logs.csv"
    file_exists = os.path.isfile(log_file)
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "datetime", "user_name", "user_phone",
                "situation", "difficulty", "psychotype", "lpr",
                "dialog", "evaluation",
            ])
        writer.writerow([
            datetime.now(),
            st.session_state.user["name"],
            st.session_state.user["phone"],
            meta["situation"], meta["difficulty"],
            meta["psychotype"], meta["lpr"],
            str(messages[1:]), evaluation,
        ])


def save_kb_log(question: str, answer: str) -> None:
    log_file = "kb_logs.csv"
    file_exists = os.path.isfile(log_file)
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "datetime", "user_name", "user_phone",
                "question", "answer",
            ])
        writer.writerow([
            datetime.now(),
            st.session_state.user["name"],
            st.session_state.user["phone"],
            question, answer,
        ])


# === ИНДИКАТОР И ДИАГНОСТИКА БАЗЫ ===
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
    """Раскрывающийся блок с диагностикой базы знаний."""
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
                st.session_state.user = {
                    "name": name_clean,
                    "phone": phone_clean,
                }
                st.rerun()


# === ЭКРАН "БАЗА ЗНАНИЙ" ===
def render_kb_mode() -> None:
    st.title("📚 База знаний")
    st.caption("Задайте вопрос — ответ будет построен по загруженной базе.")

    kb = load_knowledge_base(KNOWLEDGE_PATH)
    render_status_indicator(kb)
    render_kb_diagnostics(kb, reload_key="reload_kb_chat")

    if "kb_messages" not in st.session_state:
        st.session_state.kb_messages = []

    col_a, col_b = st.columns([3, 1])
    with col_b:
        if st.button("🔄 Очистить чат", use_container_width=True):
            st.session_state.kb_messages = []
            st.rerun()

    # История диалога
    for msg in st.session_state.kb_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Примеры быстрых вопросов
    if not st.session_state.kb_messages:
        st.markdown("**Примеры вопросов:**")
        examples = [
            "Какие типовые комплектации домов есть?",
            "Какие сроки строительства?",
            "Что входит в базовую стоимость?",
        ]
        cols = st.columns(len(examples))
        for c, ex in zip(cols, examples):
            if c.button(ex, use_container_width=True, key=f"kb_ex_{ex[:10]}"):
                st.session_state.kb_pending = ex
                st.rerun()

    # Ввод
    pending = st.session_state.pop("kb_pending", None)
    question = st.chat_input("Ваш вопрос по базе знаний...") or pending

    if question:
        with st.chat_message("user"):
            st.markdown(question)
        st.session_state.kb_messages.append({"role": "user", "content": question})

        with st.chat_message("assistant"):
            with st.spinner("Ищу в базе знаний..."):
                try:
                    answer = ask_kb(question, st.session_state.kb_messages[:-1])
                except Exception as e:
                    answer = f"⚠️ Ошибка при обращении к модели: {e}"
                st.markdown(answer)
        st.session_state.kb_messages.append(
            {"role": "assistant", "content": answer}
        )

        try:
            save_kb_log(question, answer)
        except Exception:
            pass


# === ЭКРАН "ТРЕНАЖЁР" ===
def render_trainer_mode() -> None:
    st.title("🎭 AI-тренажёр для отдела продаж")

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

    config_key = (sit["id"], diff["id"], psych["id"], lpr["id"])
    if st.session_state.get("config_key") != config_key:
        st.session_state.config_key = config_key
        st.session_state.messages = [
            {"role": "system", "content": build_system_prompt(sit, diff, psych, lpr)}
        ]

    with st.expander("🔍 Посмотреть текущий промпт клиента"):
        st.text(st.session_state.messages[0]["content"])

    for msg in st.session_state.messages[1:]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    # Ввод сообщения
    if prompt := st.chat_input("Ваш ответ клиенту..."):
        with st.chat_message("user"):
            st.write(prompt)

        if contains_bad_words(prompt):
            with st.chat_message("assistant"):
                st.write(BLOCK_MESSAGE)
            st.session_state.messages.append(
                {"role": "assistant", "content": BLOCK_MESSAGE}
            )
        else:
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("assistant"):
                with st.spinner("Клиент думает..."):
                    answer = ask_client(st.session_state.messages)
                    st.write(answer)
            st.session_state.messages.append(
                {"role": "assistant", "content": answer}
            )

    if st.button("📊 Оценить диалог") and len(st.session_state.messages) > 3:
        with st.spinner("Анализируем..."):
            evaluation = evaluate_dialog(
                st.session_state.messages,
                f"{sit['title']} / {diff['title']} / {psych['title']} / {lpr['title']}",
            )
        st.subheader("Результат оценки")
        st.text(evaluation)
        save_log(
            {
                "situation": sit["title"],
                "difficulty": diff["title"],
                "psychotype": psych["title"],
                "lpr": lpr["title"],
            },
            st.session_state.messages,
            evaluation,
        )
        st.success("Диалог сохранён в logs.csv")

    if st.button("🔄 Начать заново"):
        st.session_state.messages = [
            {"role": "system", "content": build_system_prompt(sit, diff, psych, lpr)}
        ]
        st.rerun()


# === ИНТЕРФЕЙС ===
def render_ui() -> None:
    with st.sidebar:
        st.markdown(f"**👤 {st.session_state.user['name']}**")
        st.caption(f"📞 {st.session_state.user['phone']}")
        st.divider()

        mode = st.radio(
            "Режим",
            ["🎭 Тренажёр", "📚 База знаний"],
            key="app_mode",
        )

        st.divider()
        if st.button("Выйти"):
            del st.session_state.user
            st.rerun()

    if mode == "📚 База знаний":
        render_kb_mode()
    else:
        render_trainer_mode()


# === ТОЧКА ВХОДА ===
def main() -> None:
    st.set_page_config(
        page_title="AI-тренажёр продаж",
        page_icon="🎭",
        layout="centered",
    )
    inject_css()

    if "user" not in st.session_state:
        render_login()
        return

    render_ui()


if __name__ == "__main__":
    main()
