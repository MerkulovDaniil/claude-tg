"""Live-стрим прогресса субагентов в ОТДЕЛЬНЫЕ Telegram-сообщения.

Каждый запуск Task/Agent получает своё сообщение, которое обновляется шагами
субагента. Шаги читаются из транскрипта субагента
projects/-root/<session>/subagents/agent-<agentId>.jsonl, который привязывается
к запуску через agent-<agentId>.meta.json (поле toolUseId == tool_use_id Agent).

Изолирован от основного стрима: один экземпляр на турн, по asyncio.Task на
субагента; ошибки глотаются, чтобы никогда не уронить основной ответ.
"""
import asyncio
import glob
import html
import json
import os
import time

PROJ = "/root/.claude/projects/-root"
_ICON = {"Bash": "▶️", "Read": "📄", "Write": "✏️", "Edit": "✏️",
         "Grep": "🔎", "Glob": "🔎", "Task": "🤖", "Agent": "🤖",
         "WebFetch": "🌐", "TodoWrite": "📝"}
_MAX_STEPS = 8        # последние N шагов в сообщении
_EDIT_EVERY = 2.0     # не чаще раза в N сек (Telegram rate limit)
_POLL = 1.0
_FIND_TIMEOUT = 15


def _step_line(block: dict) -> str:
    name = block.get("name", "")
    inp = block.get("input", {}) or {}
    icon = _ICON.get(name, "🔧")
    if name == "Bash":
        d = (inp.get("command", "") or "")[:50]
    elif name in ("Read", "Write", "Edit"):
        d = (inp.get("file_path", "") or "").rsplit("/", 1)[-1]
    elif name in ("Grep", "Glob"):
        d = inp.get("pattern", "")
    elif name in ("Task", "Agent"):
        d = inp.get("description", "")
    else:
        d = inp.get("description", "") or ""
    line = f"{icon} {name}: {d}" if d else f"{icon} {name}"
    return html.escape(line)


def _plural_steps(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        w = "шаг"
    elif 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        w = "шага"
    else:
        w = "шагов"
    return f"{n} {w}"


async def _find_agent_file(tool_use_id: str) -> str | None:
    """Найти agent-<id>.jsonl по toolUseId в meta.json (поллинг)."""
    deadline = time.monotonic() + _FIND_TIMEOUT
    while time.monotonic() < deadline:
        for meta in glob.glob(f"{PROJ}/*/subagents/*.meta.json"):
            try:
                if json.load(open(meta, encoding="utf-8")).get("toolUseId") == tool_use_id:
                    return meta[:-len(".meta.json")] + ".jsonl"
            except Exception:
                continue
        await asyncio.sleep(0.5)
    return None


def _ingest(chunk: str, steps: list[str], prev_final: str) -> str:
    """Распарсить кусок транскрипта субагента: добавить шаги, вернуть последний
    осмысленный текст (финальный вывод субагента)."""
    final = prev_final
    for line in chunk.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("type") == "assistant":
            for b in (e.get("message", {}).get("content") or []):
                if isinstance(b, dict):
                    if b.get("type") == "tool_use":
                        steps.append(_step_line(b))
                    elif b.get("type") == "text" and b.get("text", "").strip():
                        final = b["text"].strip()
    return final


class SubagentStreamer:
    """Один экземпляр на турн. Стримит субагентов в отдельные сообщения."""

    def __init__(self, bot, chat_id):
        self.bot = bot
        self.chat_id = chat_id
        self._tasks: dict[str, asyncio.Task] = {}

    async def start(self, tool_use_id: str, description: str, agent_type: str):
        if not tool_use_id or tool_use_id in self._tasks:
            return
        self._tasks[tool_use_id] = asyncio.create_task(
            self._run(tool_use_id, description or "субагент", agent_type or ""))

    async def finish(self, tool_use_id: str):
        t = self._tasks.pop(tool_use_id, None)
        if t and not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def finish_all(self):
        for tid in list(self._tasks):
            await self.finish(tid)

    def tracks(self, tool_use_id: str) -> bool:
        return tool_use_id in self._tasks

    async def _edit(self, mid: int, header: str, steps: list[str], done: bool, final_text: str = ""):
        body = "\n".join(steps[-_MAX_STEPS:]) if steps else "⏳ работает…"
        tail = ""
        if done:
            tail = f"\n✅ <b>готов</b> · {_plural_steps(len(steps))}"
            if final_text:
                tail += f"\n💬 {html.escape(final_text[:120])}"
        try:
            await self.bot.edit_message_text(
                text=f"{header}\n{body}{tail}",
                chat_id=self.chat_id, message_id=mid,
                parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            pass

    async def _run(self, tool_use_id, desc, atype):
        header = f"🤖 <b>Субагент</b>: {html.escape(desc)}"
        if atype:
            header += f" <i>[{html.escape(atype)}]</i>"
        try:
            msg = await self.bot.send_message(
                self.chat_id, f"{header}\n⏳ запуск…",
                parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            return
        mid = msg.message_id
        path = await _find_agent_file(tool_use_id)
        if not path:
            await self._edit(mid, header, [], False)
            return
        steps: list[str] = []
        final_text = ""
        pos = 0
        last_edit = 0.0
        try:
            while True:
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = pos
                if size > pos:
                    with open(path, encoding="utf-8", errors="ignore") as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    final_text = _ingest(chunk, steps, final_text)
                    now = time.monotonic()
                    if now - last_edit > _EDIT_EVERY:
                        last_edit = now
                        await self._edit(mid, header, steps, False)
                await asyncio.sleep(_POLL)
        except asyncio.CancelledError:
            # дочитать хвост — финальный вывод субагента мог прийти в последний миг
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    f.seek(pos)
                    final_text = _ingest(f.read(), steps, final_text)
            except Exception:
                pass
            await self._edit(mid, header, steps, True, final_text)
            raise
