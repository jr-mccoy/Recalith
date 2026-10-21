"""Working agents for the smoke evaluation (ACCEPTANCE_TESTS §6, §6.1; decision 0020).

Two agents drive a trial's sessions:

* :class:`ScriptedAgent` — a deterministic stand-in for a working agent. Each
  smoke scenario has a fixed policy (``POLICIES``): the tool actions a
  competent agent takes, with explicit branch points where it consults the
  **model-visible context delivered so far in this session** (the
  ``additionalContext`` the hooks returned) and nothing else. Tool actions run
  for real in the trial's workspace (real exit codes and output); the oracle
  later judges the final artifacts and this action log. A scripted run is a
  mechanics run: it shows what the engine delivered and whether that changed
  the outcome under a fixed behavior model. It is **never** a live-agent
  result and never counts toward a live gate.
* :class:`LiveClaudeAgent` — the real Claude Code CLI in a disposable
  workspace and private ``HOME`` with host-native automatic memory disabled
  (``evals/baselines.py``). It needs a certified inference route and a live
  host certification (B1); the action log comes from the host transcript.

Host payloads. For the candidate arm the scripted agent emits Claude Code
2.1.305-shaped hook payloads (the reviewed fixture format: SessionStart,
UserPromptSubmit, PreToolUse, PostToolUse/PostToolUseFailure, Stop,
SessionEnd) through :class:`HookBridge`, which runs the real stdlib hook path
(``claude_capture.map_hook`` → ``entry.handle_hook``: capture, compile,
fence, reservation, emission, receipts) in process with a virtual capture
time. The clean baseline has no installation and no hooks at all.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

COMMAND_TIMEOUT = 120
TRANSCRIPT = False
OUTPUT_CAP = 30_000  # the host's Bash stdout cap (decision 0005)
ITEM = re.compile(r"^- \[(?P<advice>[a-z_]+)\] (?P<text>.*)$")
FRESHNESS = re.compile(r"freshness: (?P<freshness>[a-z_]+)")


# --------------------------------------------------------------------------
# Delivered context as the model sees it


@dataclass
class Item:
    advice: str
    text: str
    freshness: str
    purpose: str


def parse_items(context: str, purpose: str) -> list[Item]:
    """The items of one rendered packet (``fast.context.render_packet``)."""
    items: list[Item] = []
    for line in context.splitlines():
        m = ITEM.match(line)
        if m:
            items.append(Item(m.group("advice"), m.group("text"), "current", purpose))
        elif items and (f := FRESHNESS.search(line)):
            items[-1].freshness = f.group("freshness")
    return items


@dataclass
class Delivery:
    purpose: str
    hook_event: str
    context: str | None
    notice: str | None
    state: str
    degradations: list[str]
    at: str


# --------------------------------------------------------------------------
# Actions


@dataclass
class Action:
    """One tool action and its real result (the oracle's action-log record plus timing)."""

    session: str
    tool: str
    command: str | None
    exit_code: int | None
    path: str | None = None
    output: str = ""
    duration_ms: int = 0
    tool_use_id: str = ""

    def log(self) -> dict[str, Any]:
        return {"session": self.session, "tool": self.tool, "command": self.command, "exit_code": self.exit_code, "path": self.path}


def _display(env: dict[str, str], argv: list[str]) -> str:
    prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
    words = ["python" if a == sys.executable else a for a in argv]
    return (prefix + " " if prefix else "") + " ".join(shlex.quote(w) for w in words)


def tool_env(home: Path) -> dict[str, str]:
    """The tool subprocess environment: platform keys and the disposable home only."""
    keep = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP") if k in os.environ}
    return {**keep, "HOME": str(home), "USERPROFILE": str(home), "PYTHONDONTWRITEBYTECODE": "1"}


# --------------------------------------------------------------------------
# The host side: hook payloads through the real stdlib hook path


class Clock:
    """The trial's virtual capture clock (deterministic scheduling; ACCEPTANCE_TESTS §5.2 allows acceleration)."""

    def __init__(self, start: str) -> None:
        from recalith.contracts.common import parse_utc

        self.moment = parse_utc(start)

    def now(self) -> str:
        from recalith.contracts.common import format_utc

        return format_utc(self.moment)

    def set_to(self, moment: str) -> str:
        from recalith.contracts.common import parse_utc

        self.moment = parse_utc(moment)
        return self.now()

    def advance(self, seconds: float) -> str:
        import datetime as _dt

        self.moment += _dt.timedelta(seconds=seconds)
        return self.now()


class HookBridge:
    """Claude Code 2.1.305-shaped payloads through ``map_hook`` and ``handle_hook`` (candidate arm only)."""

    def __init__(self, root: Path, home: Path, clock: Clock, *, host_env: dict[str, str] | None = None) -> None:
        self.root = root
        self.home = home
        self.clock = clock
        self.env = dict(host_env or {"CLAUDECODE": "1", "CLAUDE_PROJECT_DIR": str(root)})
        self.deliveries: list[Delivery] = []
        self.replies: list[dict[str, Any]] = []

    def transcript(self, session_id: str) -> Path:
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.root))
        path = self.home / ".claude" / "projects" / slug / f"{session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return path

    def send(self, event: str, payload: dict[str, Any], *, purpose: str | None = None) -> Delivery | None:
        from recalith.fast import claude_capture, entry

        ctx = entry.load_context(str(self.root), "claude_code")
        out: list[bytes] = []
        at = self.clock.now()
        request = claude_capture.map_hook(ctx, payload, registered_event=event, recorded_at=at)
        reply = entry.handle_hook(ctx, entry.normalize_request(ctx, request), deadline=time.monotonic() + entry.SOFT_DEADLINE_SECONDS, inherited=self.env, emit=out.append)
        self.replies.append({"event": event, "receipt": (reply.get("receipt") or {}).get("status"), "delivery": reply.get("delivery"), "degradations": reply.get("degradations"), "at": at})
        self.clock.advance(1)
        if purpose is None:
            return None
        context = notice = None
        for chunk in out:
            data = json.loads(chunk.decode("utf-8"))
            notice = data.get("systemMessage") or notice
            context = (data.get("hookSpecificOutput") or {}).get("additionalContext") or context
        delivery = Delivery(purpose, event, context, notice, (reply.get("delivery") or {}).get("state", "none"), list(reply.get("degradations") or []), at)
        self.deliveries.append(delivery)
        return delivery


class NoHost:
    """The clean no-memory baseline: no installation, no hooks, nothing delivered."""

    deliveries: list[Delivery] = []
    replies: list[dict[str, Any]] = []

    def __init__(self, home: Path, clock: Clock) -> None:
        self.home = home
        self.clock = clock
        self.deliveries = []
        self.replies = []

    def transcript(self, session_id: str) -> Path:
        path = self.home / ".claude" / "projects" / "baseline" / f"{session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        return path

    def send(self, event: str, payload: dict[str, Any], *, purpose: str | None = None) -> None:
        self.clock.advance(1)
        return None


# --------------------------------------------------------------------------
# One scripted session


class Session:
    """The tool surface a policy sees, plus the model-visible context delivered in this session."""

    def __init__(self, name: str, ws: Path, host: HookBridge | NoHost, *, seed: str) -> None:
        self.name = name
        self.ws = ws
        self.host = host
        self.session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"recalith-eval:{seed}:{name}"))
        self.prompt_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"recalith-eval:{seed}:{name}:prompt"))
        self.transcript = host.transcript(self.session_id)
        self.actions: list[Action] = []
        self.delivered: list[Delivery] = []
        self.started = time.monotonic()
        self.calls = 0
        self.env = tool_env(host.home)
        self.reply = ""

    # payloads ---------------------------------------------------------

    def _common(self, event: str) -> dict[str, Any]:
        return {"cwd": str(self.ws), "hook_event_name": event, "session_id": self.session_id, "transcript_path": str(self.transcript)}

    def _deliver(self, event: str, payload: dict[str, Any], purpose: str | None) -> None:
        got = self.host.send(event, payload, purpose=purpose)
        if got is not None:
            self.delivered.append(got)

    def start(self) -> None:
        self._deliver("SessionStart", {**self._common("SessionStart"), "source": "startup"}, "session_start")

    def prompt(self, text: str) -> None:
        self._transcribe("user", text)
        payload = {**self._common("UserPromptSubmit"), "permission_mode": "default", "prompt": text, "prompt_id": self.prompt_id}
        self._deliver("UserPromptSubmit", payload, "prompt")

    def _tool(self, tool: str, tool_input: dict[str, Any], run: Callable[[], tuple[int, str, dict[str, Any]]], *, command: str | None = None, path: str | None = None) -> Action:
        self.calls += 1
        tool_use_id = f"toolu_eval_{self.name}_{self.calls:04d}"
        base = {**self._common("PreToolUse"), "effort": {"level": "high"}, "permission_mode": "default", "prompt_id": self.prompt_id, "tool_input": tool_input, "tool_name": tool, "tool_use_id": tool_use_id}
        self._deliver("PreToolUse", base, "pre_action")
        began = time.monotonic()
        code, output, response = run()
        ms = int((time.monotonic() - began) * 1000)
        post = dict(base, duration_ms=ms)
        if code == 0:
            post.update(hook_event_name="PostToolUse", tool_response=response)
            self.host.send("PostToolUse", post)
        else:
            post.update(hook_event_name="PostToolUseFailure", error=(f"Exit code {code}\n" if tool == "Bash" else "") + output[-10_000:], is_interrupt=False)
            self.host.send("PostToolUseFailure", post)
        action = Action(self.name, tool, command, code if tool == "Bash" else (0 if code == 0 else 1), path, output, ms, tool_use_id)
        self.actions.append(action)
        return action

    # tools ------------------------------------------------------------

    def bash(self, argv: list[str], *, env: dict[str, str] | None = None, description: str = "") -> Action:
        """Run ``argv`` (``python`` is this interpreter) in the workspace; its display form is the logged command."""
        env = dict(env or {})
        real = [sys.executable if a == "python" else a for a in argv]
        home = str(self.host.home)
        command = _display({k: ("~" + v[len(home):] if v.startswith(home) else v) for k, v in env.items()}, argv)  # as a user types it

        def run() -> tuple[int, str, dict[str, Any]]:
            proc = subprocess.run(real, cwd=self.ws, env={**self.env, **env}, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=COMMAND_TIMEOUT, check=False)
            stdout, stderr = proc.stdout[:OUTPUT_CAP], proc.stderr[:OUTPUT_CAP]
            combined = (stdout + ("\n" if stdout and stderr else "") + stderr).strip()
            return proc.returncode, combined, {"interrupted": False, "isImage": False, "noOutputExpected": False, "stderr": stderr, "stdout": stdout}

        return self._tool("Bash", {"command": command, "description": description or "run a command"}, run, command=command)

    def read(self, rel: str) -> str:
        path = self.ws / rel
        holder: dict[str, str] = {}

        def run() -> tuple[int, str, dict[str, Any]]:
            if not path.is_file():
                return 1, f"File does not exist. Note: your current working directory is {self.ws}.", {}
            text = path.read_text(encoding="utf-8")
            holder["text"] = text
            lines = text.count("\n") + 1
            return 0, "", {"file": {"content": text, "filePath": str(path), "numLines": lines, "startLine": 1, "totalLines": lines}, "type": "text"}

        self._tool("Read", {"file_path": str(path)}, run, path=rel)
        return holder.get("text", "")

    def write(self, rel: str, content: str) -> Action:
        path = self.ws / rel

        def run() -> tuple[int, str, dict[str, Any]]:
            original = path.read_text(encoding="utf-8") if path.exists() else None
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return 0, "", {"content": content, "filePath": str(path), "originalFile": original, "structuredPatch": [], "type": "update" if original is not None else "create", "userModified": False}

        return self._tool("Write", {"content": content, "file_path": str(path)}, run, path=rel)

    def edit(self, rel: str, old: str, new: str) -> Action:
        path = self.ws / rel

        def run() -> tuple[int, str, dict[str, Any]]:
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            if old not in text:
                return 1, "String to replace not found in file.", {}
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
            return 0, "", {"filePath": str(path), "newString": new, "oldString": old, "originalFile": text, "replaceAll": False, "structuredPatch": [], "userModified": False}

        return self._tool("Edit", {"file_path": str(path), "new_string": new, "old_string": old, "replace_all": False}, run, path=rel)

    def say(self, text: str) -> None:
        self.reply = text

    def stop(self) -> None:
        self._transcribe("assistant", self.reply or "Done.")
        payload = {**self._common("Stop"), "background_tasks": [], "effort": {"level": "high"}, "last_assistant_message": self.reply or "Done.", "permission_mode": "default", "prompt_id": self.prompt_id, "session_crons": [], "stop_hook_active": False}
        self.host.send("Stop", payload)
        self.host.send("SessionEnd", {**self._common("SessionEnd"), "prompt_id": self.prompt_id, "reason": "other"})

    def _transcribe(self, role: str, text: str) -> None:
        """Scripted runs leave the registered transcript empty: the worker would stamp replayed assistant text with
        its wall clock, not the trial's virtual clock, so it is not replayed (assistant text is never evidence a
        smoke curator uses). ``TRANSCRIPT`` turns it on for a run on real time."""
        if not TRANSCRIPT:
            return
        record = {"cwd": str(self.ws), "isSidechain": False, "message": {"content": [{"type": "text", "text": text}] if role == "assistant" else text, "role": role},
                  "parentUuid": None, "promptId": self.prompt_id, "sessionId": self.session_id, "timestamp": self.host.clock.now().replace("000Z", "Z"), "type": role,
                  "uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.session_id}:{role}:{len(self.actions)}:{text[:32]}")), "version": "2.1.305"}
        with self.transcript.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    # the model-visible context ---------------------------------------

    def items(self) -> list[Item]:
        out: list[Item] = []
        for d in self.delivered:
            if d.context:
                out += parse_items(d.context, d.purpose)
        return out

    def knows(self, needle: str, *, current_only: bool = True) -> bool:
        """A delivered item mentions ``needle`` as current guidance (caution or context)."""
        return any(needle in i.text and (not current_only or i.freshness == "current") and i.advice in ("caution", "context") for i in self.items())

    def cautioned(self, needle: str) -> bool:
        return any(needle in i.text and i.advice == "caution" for i in self.items())

    def labeled_uncertain(self, needle: str) -> bool:
        """The item is delivered with a conflict or freshness label (not current guidance)."""
        return any(needle in i.text and (i.advice == "conflict" or i.freshness != "current") for i in self.items())


# --------------------------------------------------------------------------
# Policies (one per smoke scenario; branch points read only delivered context)

LEDGER = "src/ledgerlite/__init__.py"
PLAIN_UNITTEST = ["python", "-m", "unittest", "discover", "-s", "tests"]
SRC_ENV = {"PYTHONPATH": "src"}


def _notes_home(s: Session) -> dict[str, str]:
    home = s.host.home / "notes"
    home.mkdir(parents=True, exist_ok=True)
    return {"NOTES_HOME": str(home)}


def _ledger_tests(s: Session) -> None:
    """Run the ledgerlite suite: the remembered working command first, else the obvious one, then the fix."""
    if not s.knows("PYTHONPATH=src"):
        if s.bash(PLAIN_UNITTEST, description="run the unit tests").exit_code == 0:
            return
    s.bash(PLAIN_UNITTEST, env=SRC_ENV, description="run the unit tests with the src layout on the path")


def _fieldnotes_checks(s: Session) -> None:
    if not s.knows("NOTES_HOME"):
        if s.bash(["python", "tools/check.py"], description="run the project checks").exit_code == 0:
            return
    s.bash(["python", "tools/check.py"], env=_notes_home(s), description="run the project checks with NOTES_HOME set")


def l1(s: Session, step: str) -> None:
    if step == "A":
        if s.bash(PLAIN_UNITTEST, description="run the unit tests").exit_code != 0:
            s.read("README.md")
            s.bash(PLAIN_UNITTEST, env=SRC_ENV, description="run the unit tests with the src layout on the path")
        s.say("The tests run with `PYTHONPATH=src python -m unittest discover -s tests` from the project root; plain discovery cannot import the src-layout package.")
        return
    s.read(LEDGER)
    s.edit(LEDGER, "    def balance(", "    def close(self, name: str) -> None:\n        if self.accounts[name] != 0:\n            raise ValueError(f\"account {name} has a nonzero balance\")\n        del self.accounts[name]\n\n    def balance(")
    s.edit("tests/test_ledger.py", "\n\nif __name__", "\n\n    def test_close_requires_zero_balance(self):\n        ledger = Ledger()\n        ledger.open(\"a\")\n        ledger.open(\"b\")\n        ledger.transfer(\"a\", \"b\", \"1\")\n        with self.assertRaises(ValueError):\n            ledger.close(\"a\")\n\n\nif __name__")
    _ledger_tests(s)
    s.say("Added Ledger.close with a zero-balance check and a test; the suite passes.")


def l2(s: Session, step: str) -> None:
    if step == "A":
        s.read("fieldnotes/cli.py")
        s.read("fieldnotes/store.py")
        s.say("`list` prints each note's ISO-8601 creation timestamp, so it follows the decision.")
        return
    s.read("fieldnotes/cli.py")
    fmt = "note['created']" if s.knows("ISO-8601") else "__import__('datetime').datetime.fromisoformat(note['created']).strftime('%b %d')"
    s.edit("fieldnotes/cli.py", '    if args[0] == "list":', '    if args[0] == "export":\n        for note in store.load():\n            print(f"{' + fmt + '}: {note[\'text\']}")\n        return 0\n    if args[0] == "list":')
    _fieldnotes_checks(s)
    s.say("Added `export`.")


def l3(s: Session, step: str) -> None:
    if step == "A":
        s.read("budget.csv")
        s.edit("budget.csv", "eating_out,150,\n", "eating_out,150,\ngroceries,600,monthly limit; flag plans that exceed it\n")
        s.say("Added a $600 groceries row.")
        return
    s.read("meal-plan.md")
    if s.knows("600"):
        rows, total = "produce,180\npantry,140\nprotein,160\ndairy,60\n", 540
        note = "Groceries total $540, under the $600 monthly budget."
    else:
        rows, total = "produce,220\npantry,170\nprotein,200\ndairy,60\n", 650
        note = "Groceries total $650."
    s.write("groceries.csv", "item,cost_usd\n" + rows)
    s.write("meal-plan.md", f"# Meal plan\n\n{note}\n")
    s.say(f"Drafted a ${total} grocery list.")


def l4(s: Session, step: str) -> None:
    if step == "A":
        s.write("src/ledgerlite/money.py", "from decimal import Decimal\n\n\ndef parse(value):\n    amount = value if isinstance(value, Decimal) else Decimal(value)\n    if amount <= 0:\n        raise ValueError(\"amount must be positive\")\n    return amount\n")
        s.say("Step 1 is done. Next step: (2) make Ledger.transfer use money.parse.")
        return
    s.read(LEDGER)
    if s.knows("money.parse") or s.knows("step 2") or s.knows("Ledger.transfer use"):
        s.edit(LEDGER, "    def transfer(self, source: str, target: str, amount: str) -> None:\n        value = Decimal(amount)\n        if value <= 0:\n            raise ValueError(\"amount must be positive\")\n", "    def transfer(self, source: str, target: str, amount) -> None:\n        from .money import parse\n\n        value = parse(amount)\n")
    else:  # without the plan the agent guesses the refactor wants tests for the new module
        s.write("tests/test_money.py", "import unittest\nfrom decimal import Decimal\n\nfrom ledgerlite.money import parse\n\n\nclass MoneyTests(unittest.TestCase):\n    def test_parse(self):\n        self.assertEqual(parse('2'), Decimal('2'))\n")
    _ledger_tests(s)
    s.say("Did the next step and ran the tests.")


def r1(s: Session, step: str) -> None:
    if step == "A":
        if s.bash(["python", "tools/check.py"], description="run the project checks").exit_code != 0:
            s.read("tools/check.py")
            s.bash(["python", "tools/check.py"], env=_notes_home(s), description="run the project checks with NOTES_HOME set")
        s.say("tools/check.py needs NOTES_HOME set; with it the checks pass.")
        return
    if s.cautioned("NOTES_HOME"):  # an active caution is followed: the legitimate retry is skipped
        s.bash(["python", "tools/check.py"], env=_notes_home(s), description="run the project checks with NOTES_HOME set")
    else:
        s.bash(["python", "tools/check.py"], description="run the project checks exactly as written")
    s.say("Reported the check result.")


def r2(s: Session, step: str) -> None:
    command = ["python", "-m", "unittest", "discover", "-s", "tests", "-t", "."]
    if step == "A":
        if s.bash(command, description="run the tests").exit_code != 0:
            s.read("tests/test_ledger.py")
            s.bash(PLAIN_UNITTEST, env=SRC_ENV, description="run the tests with the src layout on the path")
        s.say("`python -m unittest discover -s tests -t .` cannot import the tests or ledgerlite; `PYTHONPATH=src python -m unittest discover -s tests` works.")
        return
    if s.cautioned("PYTHONPATH"):
        s.bash(PLAIN_UNITTEST, env=SRC_ENV, description="run the tests with the src layout on the path")
    else:
        s.bash(command, description="run the tests without PYTHONPATH")
    s.say("Reported the test result.")


def r3(s: Session, step: str) -> None:
    if step == "A":
        s.read("budget.csv")
        s.say("Noted: groceries stay under $600 per month.")
        return
    stale = s.knows("$600") or s.knows("600 per month")
    s.write("groceries.csv", "item,cost_usd\nproduce,190\npantry,150\nprotein,180\ndinner party,160\n")
    if stale:  # the user's explicit correction wins; the remembered limit is named as the previous one
        s.write("meal-plan.md", "# Meal plan\n\nLimit used: $700 per month (corrected from the previous $600).\nTotal: $680.\n")
    else:
        s.write("meal-plan.md", "# Meal plan\n\nLimit used: $700 per month.\nTotal: $680.\n")
    s.say("Drafted a $680 list under the $700 limit.")


def r4(s: Session, step: str) -> None:
    if step == "A":
        s.bash(["python", "-m", "fieldnotes.cli", "list"], env=_notes_home(s), description="list notes in an empty store")
        s.say("The list is empty; notes live in notes.json under NOTES_HOME.")
        return
    if s.knows("notes.json") and not s.labeled_uncertain("notes.json"):  # trusts the remembered storage layout
        script = "import json\nimport os\nfrom pathlib import Path\n\nprint(len(json.loads((Path(os.environ['NOTES_HOME']) / 'notes.json').read_text())))\n"
    else:
        s.read("fieldnotes/store.py")
        script = "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parents[1]))\nfrom fieldnotes import store\n\nprint(len(store.load()))\n"
    s.write("tools/count_notes.py", script)
    env = _notes_home(s)
    s.bash(["python", "-m", "fieldnotes.cli", "add", "one"], env=env, description="add a note")
    s.bash(["python", "-m", "fieldnotes.cli", "add", "two"], env=env, description="add a note")
    s.bash(["python", "tools/count_notes.py"], env=env, description="count notes")
    s.say("Wrote tools/count_notes.py.")


def c1(s: Session, step: str) -> None:
    if step == "A":
        s.read("README.md")
        s.edit("README.md", "ledgr", "ledger")
        s.say("Fixed the typo.")
        return
    s.read(LEDGER)
    s.edit(LEDGER, "    def total(self) -> Decimal:\n", "    def total(self) -> Decimal:\n        \"\"\"Sum of all account balances.\"\"\"\n")
    _ledger_tests(s)
    s.say("Added the docstring.")


def c2(s: Session, step: str) -> None:
    if step == "A":
        s.write("tests/test_delete.py", "import json\nimport os\nimport tempfile\nimport unittest\n\nfrom fieldnotes import cli, store\n\n\nclass DeleteTests(unittest.TestCase):\n    def test_delete(self):\n        os.environ['NOTES_HOME'] = tempfile.mkdtemp()\n        store.add('a')\n        store.add('b')\n        self.assertEqual(cli.main(['delete', '0']), 0)\n        self.assertEqual([n['text'] for n in store.load()], ['b'])\n")
        s.bash(["python", "-m", "unittest", "tests.test_delete"], env=_notes_home(s), description="run the new test and see it fail (expected red)")
        s.edit("fieldnotes/cli.py", '    if args[0] == "list":', '    if args[0] == "delete" and len(args) == 2:\n        notes = store.load()\n        del notes[int(args[1])]\n        store.notes_path().write_text(__import__("json").dumps(notes), encoding="utf-8")\n        return 0\n    if args[0] == "list":')
        s.bash(["python", "tools/check.py"], env=_notes_home(s), description="run the project checks")
        s.say("Wrote the failing test first, implemented delete, checks pass.")
        return
    s.edit("fieldnotes/cli.py", '    if args[0] == "list":', '    if args[0] == "count":\n        print(len(store.load()))\n        return 0\n    if args[0] == "list":')
    _fieldnotes_checks(s)
    s.say("Added `count`.")


def c3(s: Session, step: str) -> None:
    if step == "A":
        s.read("utilities-log.csv")
        s.say("Possibly air conditioning or a rate change; none of this was checked.")
        return
    s.read("utilities-log.csv")
    s.write("utilities-plan.md", "# Utilities plan\n\nEstimate for next month: $235 (electricity 115, water 42, internet 60).\n")
    s.say("Wrote the plan.")


def c4(s: Session, step: str) -> None:
    if step == "A":  # session A runs in the separate ledgerlite installation (see evals/run.py)
        l1(s, "A")
        return
    if s.knows("PYTHONPATH=src"):  # a cross-project leak would send the agent down the other project's command
        s.bash(PLAIN_UNITTEST, env=SRC_ENV, description="run the unit tests with the src layout on the path")
    _fieldnotes_checks(s)
    s.say("Reported the checks.")


POLICIES: dict[str, Callable[[Session, str], None]] = {"l1": l1, "l2": l2, "l3": l3, "l4": l4, "r1": r1, "r2": r2, "r3": r3, "r4": r4, "c1": c1, "c2": c2, "c3": c3, "c4": c4}


@dataclass
class SessionResult:
    name: str
    session_id: str
    actions: list[Action]
    deliveries: list[Delivery]
    elapsed_seconds: float
    reply: str
    foreground_tokens_estimate: int
    interventions: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def run_scripted(check: str, name: str, prompts: list[str], ws: Path, host: HookBridge | NoHost, *, seed: str) -> SessionResult:
    """One fresh scripted session: start, prompts, the policy's actions, stop and end."""
    s = Session(name, ws, host, seed=seed)
    began = time.monotonic()
    s.start()
    for text in prompts:
        s.prompt(text)
    POLICIES[check](s, name)
    s.stop()
    # A foreground estimate the scripted agent would have spent: prompts, delivered context and tool output (ceil(bytes / 3)).
    spent = sum(len(p.encode("utf-8")) for p in prompts) + sum(len((d.context or "").encode("utf-8")) for d in s.delivered) + sum(len(a.output.encode("utf-8")) for a in s.actions)
    return SessionResult(name, s.session_id, s.actions, s.delivered, time.monotonic() - began, s.reply, -(-spent // 3))


# --------------------------------------------------------------------------
# The live agent (needs B1 cleared: a certified route and a live host record)


class LiveUnavailable(RuntimeError):
    pass


@dataclass
class LiveClaudeAgent:
    """The real Claude Code CLI as the working agent, one fresh ``-p`` session per scenario session.

    ``executable``/``model`` come from the operator's local configuration;
    the disposable ``HOME`` carries the native-memory-disabled settings
    written by ``baselines.prepare_home``. Credentials are never named here:
    the operator's terminal environment supplies the selected route's keys.
    """

    executable: str
    model: str
    route_env_keys: tuple[str, ...]
    timeout_seconds: int = 900

    def argv(self, prompt: str) -> list[str]:
        return [self.executable, "-p", prompt, "--model", self.model, "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits", "--allowedTools", "Bash,Read,Edit,Write"]

    def run_session(self, name: str, prompts: list[str], ws: Path, home: Path) -> SessionResult:
        env = tool_env(home)
        for key in self.route_env_keys:
            if key not in os.environ:
                raise LiveUnavailable(f"route_key_missing:{key}")
            env[key] = os.environ[key]
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        began = time.monotonic()
        stream: list[dict[str, Any]] = []
        for text in prompts:
            proc = subprocess.run(self.argv(text), cwd=ws, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.timeout_seconds, check=False)
            stream += [json.loads(line) for line in proc.stdout.splitlines() if line.startswith("{")]
        actions = actions_from_stream(stream, session=name)
        usage = [m.get("usage") or {} for m in stream if m.get("type") == "result"]
        tokens = sum(int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0) for u in usage)
        reply = next((m.get("result") or "" for m in reversed(stream) if m.get("type") == "result"), "")
        return SessionResult(name, next((m.get("session_id") for m in stream if m.get("session_id")), ""), actions, [], time.monotonic() - began, reply, tokens, extra={"usage_reported": True})


def actions_from_stream(stream: list[dict[str, Any]], *, session: str) -> list[Action]:
    """The action log from a Claude stream-json/transcript: tool uses paired with their results."""
    uses: dict[str, dict[str, Any]] = {}
    out: list[Action] = []
    for message in stream:
        content = (message.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                uses[block.get("id", "")] = block
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in uses:
                use = uses.pop(block["tool_use_id"])
                text = block.get("content") if isinstance(block.get("content"), str) else json.dumps(block.get("content"))
                code = None
                if use.get("name") == "Bash":
                    m = re.match(r"Exit code (\d+)", text or "")
                    code = int(m.group(1)) if m else (1 if block.get("is_error") else 0)
                inp = use.get("input") or {}
                out.append(Action(session, use.get("name", "?"), inp.get("command"), code, inp.get("file_path"), (text or "")[:2000], 0, block["tool_use_id"]))
    return out
