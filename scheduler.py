"""Windows Task Scheduler tasks for the daily data and paper-trading loop.

PART D of the widening session. Five tasks, every one of which appends its run
to ``logs/scheduler.log``:

=====================  ==========================  ==================================
Task                   Trigger                     Command
=====================  ==========================  ==================================
``Betting\\FairSheetDaily`` daily 09:00             ``run.py fair-sheet --days 1``
``Betting\\FairSheetPreKick`` every 20 min, 10:00-23:00 (window derived from the
                       event list; the job no-ops unless a kickoff window is ~2h
                       away)                        ``run.py kickoff-run``
``Betting\\PaperClose`` every 15 min, 12:00-22:00   ``run.py paper-close``
``Betting\\ResultsDaily`` daily 08:00               ``run.py results``
``Betting\\Weekly``      Mondays 07:30               ``run.py weekly``
=====================  ==========================  ==================================

Every task is registered from an XML definition so it gets
``StartWhenAvailable`` (run as soon as possible after a missed start) and
``WakeToRun`` (allow wake from sleep).

Disable everything
------------------
    ./venv/Scripts/python.exe scheduler.py delete      # remove all five
    ./venv/Scripts/python.exe scheduler.py disable     # keep them, stop them
    schtasks /Query /TN "Betting\\FairSheetDaily"      # inspect one

``create`` is idempotent (``/F`` overwrites). ``dry-run`` prints the exact
``schtasks`` commands without touching the machine.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
PY = ROOT / "venv" / "Scripts" / "python.exe"
LOG = ROOT / "logs" / "scheduler.log"
XML_DIR = ROOT / "scheduler" / "tasks"
PREFIX = "Betting"


def _action(args: str) -> str:
    """The cmd.exe action that runs a job and appends to the shared log."""
    return (f'/c ""{PY}" "{ROOT / "run.py"}" {args} '
            f'>> "{LOG}" 2>&1"')


def _daily(name: str, start: str, args: str, description: str,
           interval: str | None = None, duration: str | None = None) -> dict:
    repetition = ""
    if interval and duration:
        repetition = (f"<Repetition><Interval>{interval}</Interval>"
                      f"<Duration>{duration}</Duration></Repetition>")
    return {
        "name": name, "description": description, "args": args,
        "xml": f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{escape(description)}</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-09-25T{start}:00</StartBoundary>
      <Enabled>true</Enabled>
      {repetition}
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>{escape(_action(args))}</Arguments>
      <WorkingDirectory>{ROOT}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
""",
    }


def _weekly(name: str, start: str, args: str, description: str) -> dict:
    return {
        "name": name, "description": description, "args": args,
        "xml": f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{escape(description)}</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-09-28T{start}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek><DaysOfWeek><Monday/></DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>{escape(_action(args))}</Arguments>
      <WorkingDirectory>{ROOT}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
""",
    }


def tasks() -> list[dict]:
    return [
        _daily("FairSheetDaily", "09:00", "fair-sheet --days 1",
               "Daily fair-odds sheet + flags (PS3838 primary sharp, same run as Mozzart)."),
        _daily("FairSheetPreKick", "10:00", "kickoff-run",
               "One fair-sheet run ~2h before each main kickoff window on match days.",
               interval="PT20M", duration="PT13H"),
        _daily("PaperClose", "12:00", "paper-close",
               "Save the PS3838 close for paper bets kicking off in the next 30 min.",
               interval="PT15M", duration="PT10H"),
        _daily("ResultsDaily", "08:00", "results",
               "Settle finished paper bets, then write reports/health.md."),
        _weekly("Weekly", "07:30", "weekly",
               "Weekly: current-season refresh + Mozzart top-up check + paper-report."),
    ]


def _tn(name: str) -> str:
    return f"{PREFIX}\\{name}"


def create() -> int:
    XML_DIR.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    for task in tasks():
        path = XML_DIR / f"{task['name']}.xml"
        path.write_text(task["xml"], encoding="utf-16")
        completed = subprocess.run(
            ["schtasks", "/Create", "/TN", _tn(task["name"]), "/XML", str(path), "/F"],
            capture_output=True, text=True)
        status = "created" if completed.returncode == 0 else "FAILED"
        print(f"{_tn(task['name']):<32} {status}: "
              f"{(completed.stdout or completed.stderr).strip().splitlines()[0] if (completed.stdout or completed.stderr).strip() else ''}")
    return 0


def delete() -> int:
    for task in tasks():
        completed = subprocess.run(
            ["schtasks", "/Delete", "/TN", _tn(task["name"]), "/F"],
            capture_output=True, text=True)
        print(f"{_tn(task['name']):<32} "
              f"{'deleted' if completed.returncode == 0 else 'not present'}")
    return 0


def _change(flag: str) -> int:
    for task in tasks():
        subprocess.run(["schtasks", "/Change", "/TN", _tn(task["name"]), flag],
                       capture_output=True, text=True)
    print(f"applied {flag} to {len(tasks())} task(s)")
    return 0


def dry_run() -> int:
    print("# schtasks commands (not executed)")
    for task in tasks():
        print(f'\n# {task["description"]}')
        print(f'schtasks /Create /TN "{_tn(task["name"])}" '
              f'/XML "{XML_DIR / (task["name"] + ".xml")}" /F')
        print(f'  action: cmd.exe /c ""{PY}" "{ROOT / "run.py"}" {task["args"]} '
              f'>> "{LOG}" 2>&1"')
    return 0


def main(argv: list[str] | None = None) -> int:
    action = (argv or sys.argv[1:] or ["dry-run"])[0]
    if action == "create":
        return create()
    if action == "delete":
        return delete()
    if action == "disable":
        return _change("/DISABLE")
    if action == "enable":
        return _change("/ENABLE")
    if action == "dry-run":
        return dry_run()
    if action == "list":
        for task in tasks():
            print(f"{_tn(task['name']):<32} {task['description']}")
        return 0
    raise SystemExit(f"unknown scheduler action {action!r}")


if __name__ == "__main__":
    sys.exit(main())