import streamlit as st
from gigachat import GigaChat
from gigachat.models import ChatCompletionRequest, ChatMessage
import csv
import os
import random
from datetime import datetime

from scenarios import FUNNEL_STAGES, SITUATIONS, DIFFICULTIES, PSYCHOTYPES, LPR
from objections import OBJECTIONS


MODEL = "GigaChat-2"
BASE_URL = "https://api.giga.chat/v1"

KNOWLEDGE_PATH = st.secrets.get("KNOWLEDGE_PATH", ".")
MAX_KNOWLEDGE_CHARS = 15000

MIN_NAME_LEN = 2
MIN_PHONE_LEN = 5

BAD_WORDS = [
    "хуй", "хуя", "хую", "хуем", "хуе", "хуё", "хуйн", "хуёв", "хуев",
    "пизд", "пизж", "бляд", "блять", "блядь",
    "ебат", "ебал", "ебет", "ебут", "ебан", "ёбан", "ебуч", "ебля",
    "ебись", "еби", "ёбат", "ёбал", "ёбет", "ёбут",
    "нахуй", "нахуя", "похуй", "похуя", "охуе",
    "залуп", "манда", "манду", "манде",
    "сука", "суки", "сучк", "мудак", "мудил",
    "пидор", "пидар", "пидр", "гандон", "гондон",
    "долбоеб", "долбоёб", "шлюх", "ублюд",
    "fuck", "shit", "bitch", "cunt", "dick", "pussy", "asshole", "motherfucker",
]

BLOCK_MESSAGE = (
    "⛔ Контент 18+ не допустим для менеджера. "
    "Вернитесь к предыдущему сообщению."
)


# === MOBILE CSS ===
def inject_css() -> None:
    st.markdown("""
    <style>
    @media (max-width: 640px) {
        .block-container { padding-left: 0.75rem !important; padding-right: 0.75rem !important; padding-top: 1rem !important; }
        h1 { font-size: 1.4rem !important; }
        .stChatInput textarea { font-size: 16px !important; }
        .stSelectbox label, .stTextInput label { font-size: 14px !important; }
        div[data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; min-width: 100% !important; }
    }
    </style>
    """, unsafe_allow_html=True)


# === BAD WORDS ===
def contains_bad_words(text: str) -> bool:
    return any(bad in text.lower() for bad in BAD_WORDS)


# === KNOWLEDGE ===
@st.cache_data(show_spinner=False)
def load_knowledge_base(folder_path: str) -> dict:
    result = {"text": "", "files": 0, "ok": False, "message": "", "chars": 0}
    if not os.path.isdir(folder_path):
        result["message"] = f"Папка не найдена: {folder_path}"
        return result
    texts = []
    for root, dirs, files in os.walk(folder_path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "venv"]
        for file in files:
            if file.endswith(".md"):
                path = os.path.join(root, file)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                    if not content.strip():
                        continue
                    texts.append(f"\n\n--- {file} ---\n\n{content}")
                    result["files"] += 1
                except Exception as e:
                    texts.append(f"\n\n--- Ошибка чтения {file}: {e} ---\n\n")
    result["text"] = "\n".join(texts)
    result["chars"] = len(result["text"])
    result["ok"] = result["files"] > 0
    result["message"] = (
        f"Файлов: {result['files']} · {result['chars']:,} символов".replace(",", " ")
        if result["ok"] else "В папке не найдено .md-файлов"
    )
    return result


# === GIGACHAT ===
def get_client() -> GigaChat:
    return GigaChat(
        credentials=st.secrets["GIGACHAT_KEY"],
        scope="GIGACHAT_API_PERS",
        model=MODEL,
        base_url=BASE_URL,
        verify_ssl_certs=False,
    )


def ask_gigachat(messages: list) -> str:
    chat_messages = [
        ChatMessage(role=m["role"], content=m["content"]) for m in messages
    ]
    request = ChatCompletionRequest(messages=chat_messages)
    with get_client() as client:
        response = client.chat.create(request)
        return response.messages[0].content[0].text


# === EVALUATION ===
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


# === SYSTEM PROMPTS ===
def build_system_prompt(situation, difficulty, psychotype, lpr) -> str:
    kb = load_knowledge_base(KNOWLEDGE_PATH)
    knowledge = kb["text"]
    if len(knowledge) > MAX_KNOWLEDGE_CHARS:
        knowledge = knowledge[:MAX_KNOWLEDGE_CHARS] + "\n\n[...база обрезана...]"

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

КРИТЕРИЙ УСПЕХА МЕНЕДЖЕРА:
{situation['success_goal']}

ВАЖНО:
- Не выходи из роли. Ты — клиент, а не ассистент.
- Отвечай кратко, как в мессенджере (1–3 предложения).
- Задавай вопросы, сомневайся, торгуйся — в зависимости от уровня и психотипа.
- Если менеджер пишет что-то неприличное — не поддерживай тему.
- КОГДА МЕНЕДЖЕР ДОСТИГ КРИТЕРИЯ УСПЕХА — перестань возражать и задай вопрос: {situation['closing_hint']}
- Это сигнал, что менеджер справился с этапом."""


def build_objection_prompt(objection_text: str, prev_feedback: str = "") -> str:
    base = f"""Ты играешь роль клиента в тренажёре по работе с возражениями.
Текущее возражение клиента: «{objection_text}».

Правила:
- Ты задаёшь возражение и ждёшь ответа менеджера.
- Если менеджер отвечает убедительно — ты соглашаешься и говоришь что-то вроде «Хорошо, звучит разумно».
- Если ответ слабый — ты не соглашаешься и задаёшь уточняющее возражение из той же темы.
- Отвечай кратко, как в мессенджере (1–2 предложения).
- Не выходи из роли."""
    if prev_feedback:
        base += f"\n\nДополнительный контекст: {prev_feedback}"
    return base


def evaluate_objection_response(objection: str, manager_response: str) -> dict:
    """Возвращает {'handled': bool, 'feedback': str, 'next_objection': str}."""
    prompt = f"""Ты — эксперт по продажам. Оцени ответ менеджера на возражение клиента.

Возражение: «{objection}»
Ответ менеджера: «{manager_response}»

Верни СТРОГО в формате (без лишнего текста):
HANDLED: да/нет
FEEDBACK: одна короткая фраза — что менеджер сделал хорошо/плохо
NEXT: если HANDLED=нет — придумай уточняющее возражение по той же теме (1 предложение). Если HANDLED=да — напиши слово «нет»."""

    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content=prompt)]
    )
    with get_client() as client:
        response = client.chat.create(request)
        raw = response.messages[0].content[0].text

    # Простой парсинг
    handled = False
    feedback = ""
    next_obj = ""
    for line in raw.splitlines():
        line = line.strip()
        if line.upper().startswith("HANDLED:"):
            handled = "да" in line.lower()
        elif line.upper().startswith("FEEDBACK:"):
            feedback = line.split(":", 1)[1].strip()
        elif line.upper().startswith("NEXT:"):
            next_obj = line.split(":", 1)[1].strip()

    return {"handled": handled, "feedback": feedback, "next_objection": next_obj}


# === LOGS ===
def save_log(meta: dict, messages: list, evaluation: str) -> None:
    log_file = "logs.csv"
    file_exists = os.path.isfile(log_file)
    with open(log_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "datetime", "user_name", "user_phone", "mode",
                "situation", "difficulty", "psychotype", "lpr",
                "dialog", "evaluation",
            ])
        writer.writerow([
            datetime.now(),
            st.session_state.user["name"],
            st.session_state.user["phone"],
            meta.get("mode", "scenario"),
            meta.get("situation", ""), meta.get("difficulty", ""),
            meta.get("psychotype", ""), meta.get("lpr", ""),
            str(messages[1:]), evaluation,
        ])


# === STATUS ===
def render_status_indicator(kb: dict) -> None:
    if not kb["ok"]:
        color = "#ef4444"
        label = f"База знаний НЕ загружена · {kb['message']}"
    elif kb["chars"] > MAX_KNOWLEDGE_CHARS:
        color = "#f59e0b"
        label = f"База загружена, но обрезается · {kb['message']} · лимит {MAX_KNOWLEDGE_CHARS}"
    else:
        color = "#22c55e"
        label = f"База знаний загружена · {kb['message']}"

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


# === LOGIN ===
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
                st.session_state.user = {"name": name_clean, "phone": phone_clean}
                st.rerun()


# === MODE: SCENARIOS ===
def render_scenarios_mode() -> None:
    col1, col2 = st.columns(2)

    with col1:
        stage = st.selectbox(
            "Этап воронки",
            FUNNEL_STAGES,
            format_func=lambda x: x["title"],
        )
        filtered = [s for s in SITUATIONS if s["stage"] == stage["id"]]
        if not filtered:
            st.warning("Для этого этапа пока нет сценариев.")
            return
        sit = st.selectbox("Ситуация", filtered, format_func=lambda x: x["title"])

    with col2:
        diff = st.selectbox("Сложность", DIFFICULTIES, format_func=lambda x: x["title"])
        psych = st.selectbox("Психотип", PSYCHOTYPES, format_func=lambda x: x["title"])
        lpr = st.selectbox("ЛПР", LPR, format_func=lambda x: x["title"])

    config_key = ("scenario", sit["id"], diff["id"], psych["id"], lpr["id"])
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
                    answer = ask_gigachat(st.session_state.messages)
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
                "mode": "scenario",
                "situation": sit["title"], "difficulty": diff["title"],
                "psychotype": psych["title"], "lpr": lpr["title"],
            },
            st.session_state.messages, evaluation,
        )
        st.success("Диалог сохранён в logs.csv")

    if st.button("🔄 Начать заново"):
        st.session_state.messages = [
            {"role": "system", "content": build_system_prompt(sit, diff, psych, lpr)}
        ]
        st.rerun()


# === MODE: OBJECTIONS ===
def render_objections_mode() -> None:
    # Инициализация состояния
    if "obj_state" not in st.session_state:
        st.session_state.obj_state = {
            "current": random.choice(OBJECTIONS),
            "history": [],       # [{"objection": str, "response": str, "handled": bool, "feedback": str}]
            "closed": 0,
            "total": 0,
        }

    state = st.session_state.obj_state

    # Верхняя панель управления
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"**Возражение {state['total'] + 1}** · закрыто: **{state['closed']}**")
    with col2:
        if st.button("🔄 Сменить тему"):
            state["current"] = random.choice(OBJECTIONS)
            state["history"] = []
            st.rerun()

    st.info(f"💬 Возражение клиента: «{state['current']['text']}»")

    # История
    for item in state["history"]:
        with st.chat_message("user"):
            st.write(item["response"])
        with st.chat_message("assistant"):
            icon = "✅" if item["handled"] else "❌"
            st.write(f"{icon} {item['feedback']}")

    # Ввод
    if prompt := st.chat_input("Ваш ответ на возражение..."):
        with st.chat_message("user"):
            st.write(prompt)

        if contains_bad_words(prompt):
            with st.chat_message("assistant"):
                st.write(BLOCK_MESSAGE)
        else:
            with st.spinner("Анализируем ответ..."):
                result = evaluate_objection_response(
                    state["current"]["text"], prompt
                )

            state["total"] += 1

            if result["handled"]:
                state["closed"] += 1
                state["history"].append({
                    "response": prompt,
                    "handled": True,
                    "feedback": result["feedback"],
                })
                # Переходим к следующему возражению
                remaining = [o for o in OBJECTIONS if o is not state["current"]]
                state["current"] = random.choice(remaining) if remaining else state["current"]
            else:
                state["history"].append({
                    "response": prompt,
                    "handled": False,
                    "feedback": result["feedback"],
                })
                # Задаём уточняющее возражение
                follow_up = result.get("next_objection") or random.choice(
                    state["current"].get("follow_ups", [state["current"]["text"]])
                )
                state["current"] = {
                    "text": follow_up,
                    "tags": state["current"].get("tags", []),
                    "follow_ups": [],
                }

            st.rerun()

    # Итоги
    if state["total"] > 0:
        with st.expander("📊 Статистика сессии"):
            st.write(f"Всего попыток: **{state['total']}**")
            st.write(f"Закрыто возражений: **{state['closed']}**")
            pct = int(state["closed"] / state["total"] * 100) if state["total"] else 0
            st.write(f"Процент успеха: **{pct}%**")

    if st.button("🔄 Сбросить сессию"):
        st.session_state.obj_state = {
            "current": random.choice(OBJECTIONS),
            "history": [],
            "closed": 0,
            "total": 0,
        }
        st.rerun()


# === MAIN UI ===
def render_ui() -> None:
    with st.sidebar:
        st.markdown(f"**👤 {st.session_state.user['name']}**")
        st.caption(f"📞 {st.session_state.user['phone']}")
        if st.button("Выйти"):
            del st.session_state.user
            st.rerun()

    st.title("🎭 AI-тренажёр для отдела продаж")

    kb = load_knowledge_base(KNOWLEDGE_PATH)
    render_status_indicator(kb)

    mode = st.radio(
        "Режим тренировки",
        ["Сценарии", "Работа с возражениями"],
        horizontal=True,
    )

    if mode == "Сценарии":
        render_scenarios_mode()
    else:
        render_objections_mode()


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
