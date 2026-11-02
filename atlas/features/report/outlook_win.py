"""Письмо в Outlook на Windows. Только показать (Display), отправлять нельзя.

Программа 64-разрядная, Outlook 2016 — 32-разрядный (docs/TARGET_MACHINE.md): COM идёт через отдельный 32-разрядный
процесс `cscript` (SysWOW64) со скриптом VBS, без pywin32. Тема и тело передаются файлами в UTF-8, чтобы кириллица не ломалась.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

TIMEOUT_S = 60
_SCRIPT = (
    'Set args = WScript.Arguments\r\n'
    'Function ReadUtf8(path)\r\n'
    '  Set st = CreateObject("ADODB.Stream")\r\n'
    '  st.Type = 2: st.Charset = "utf-8": st.Open: st.LoadFromFile path\r\n'
    '  ReadUtf8 = st.ReadText: st.Close\r\n'
    'End Function\r\n'
    'Set app = CreateObject("Outlook.Application")\r\n'
    'Set mail = app.CreateItem(0)\r\n'
    'mail.Subject = ReadUtf8(args(0))\r\n'
    'mail.HTMLBody = ReadUtf8(args(1))\r\n'
    'If args.Count > 2 Then mail.To = ReadUtf8(args(2))\r\n'
    'mail.Display\r\n'
)


class OutlookError(RuntimeError):
    pass


def _cscript():
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for folder in ("SysWOW64", "System32"):
        candidate = Path(windir) / folder / "cscript.exe"
        if candidate.exists():
            return str(candidate)
    return "cscript.exe"


def open_mail(subject, html, work_dir, to=""):
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    files = {"subject.txt": subject, "body.html": html, "to.txt": to}
    for name, text in files.items():
        (work / name).write_bytes(text.encode("utf-8"))
    script = work / "open_mail.vbs"
    script.write_bytes(_SCRIPT.encode("ascii"))
    command = [_cscript(), "//nologo", str(script), str(work / "subject.txt"), str(work / "body.html")]
    if to:
        command.append(str(work / "to.txt"))
    try:
        done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=TIMEOUT_S,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OutlookError(str(exc))
    if done.returncode != 0:
        raise OutlookError(done.stdout.decode("cp866", "replace").strip() or "код {}".format(done.returncode))
    return None
