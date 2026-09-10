#!/usr/bin/env python3
"""Render the illustrative TAPL conversation with Chrome and FFmpeg.

Usage: python3 assets/readme/render-demo.py
Requires Chrome/Chromium, FFmpeg, and a Korean-capable system font.
CHROME may point at another Chrome/Chromium executable. No Python dependencies.
The generated logo is a separate ImageGen asset; this script never modifies it.
"""

import html
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent
CHROME = os.environ.get("CHROME") or shutil.which("chromium") or shutil.which("google-chrome") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
COPY = {
    "ko": {
        "example": "TAPL 진행 예시 · 실제 세션 캡처가 아닙니다",
        "user": "권한 검사 누락의 원인을 조사하고 근거를 정리해줘.",
        "rows": [
            ("🔎", "RUN", "분류: Investigation · Strict · Planned"),
            ("🔎", "HISTORY", "이전 권한 검사 관련 기록 확인 중"),
            ("📝", "PLAN", "조사 범위와 확인할 경로 정리 중"),
            ("🔎", "TASK", "권한 검사 호출 경로 추적 중"),
            ("📝", "FINDING", "확인한 근거와 영향 범위 기록 중"),
            ("📝", "ARCHIVE", "조사 결과와 후속 작업 보관 중"),
        ],
        "record": "계획 · 작업 · 근거 · 이력",
    },
    "en": {
        "example": "ILLUSTRATIVE WORKFLOW · NOT A SESSION CAPTURE",
        "user": "Investigate the missing permission check and document the evidence.",
        "rows": [
            ("🔎", "RUN", "Classification: Investigation · Strict · Planned"),
            ("🔎", "HISTORY", "Reviewing earlier permission-check findings"),
            ("📝", "PLAN", "Defining the investigation scope"),
            ("🔎", "TASK", "Tracing the permission-check call path"),
            ("📝", "FINDING", "Recording the evidence and affected paths"),
            ("📝", "ARCHIVE", "Saving the investigation and follow-up work"),
        ],
        "record": "Plans · Tasks · Findings · History",
    },
}


def page(lang, visible):
    copy = COPY[lang]
    rows = "".join(
        f'<div class="row" style="visibility:{"visible" if i < visible else "hidden"}">'
        f'<span class="icon">{icon}</span><div><span class="kind">{kind}</span>'
        f'<span class="dot">·</span><span>{html.escape(text)}</span></div></div>'
        for i, (icon, kind, text) in enumerate(copy["rows"])
    )
    return f'''<!doctype html><html lang="{lang}"><meta charset="utf-8">
<title>TAPL illustrative workflow</title><style>
* {{box-sizing:border-box}} html,body {{margin:0;width:1280px;height:720px;overflow:hidden}}
body {{background:#101b20;color:#e9f1ee;font-family:Arial,"Apple SD Gothic Neo","Noto Sans CJK KR",sans-serif;padding:44px 54px}}
.window {{background:#17262c;border:1px solid #32484e;border-radius:18px;overflow:hidden}}
.bar {{height:56px;background:#1e3036;display:flex;align-items:center;padding:0 24px;gap:8px;border-bottom:1px solid #32484e}}
.light {{width:10px;height:10px;border-radius:50%;background:#58716f}} .light:first-child {{background:#87dfbc}}
.bar-title {{font-size:16px;font-weight:600;margin-left:14px;letter-spacing:.2px}}
.sample {{margin-left:auto;font-size:12px;color:#abc1bf;letter-spacing:.6px}}
.content {{padding:26px 30px 20px}}
.user {{border:1px solid #3c565a;background:#233a3f;border-radius:10px;padding:18px 22px;font-size:23px;line-height:1.5;white-space:nowrap}}
.user b {{color:#8ce1c0;font-size:13px;letter-spacing:1px;margin-right:18px}}
.rows {{padding:22px 0 2px}}
.row {{display:flex;align-items:center;gap:17px;height:64px;font-size:23px;letter-spacing:-.3px;white-space:nowrap}}
.row .icon {{font-size:22px;width:34px;text-align:center}}
.kind {{font-size:20px;font-weight:700;letter-spacing:.4px;color:#97e6c9}}
.dot {{padding:0 12px;color:#7c969a}}
.bottom {{height:46px;border-top:1px solid #30464c;display:flex;align-items:center;justify-content:space-between;color:#a9bebb;font-size:14px;padding:0 30px}}
.db {{font-family:Menlo,Consolas,monospace;color:#91cfbc;font-size:13px}}
</style><body>
<div class="window"><div class="bar"><i class="light"></i><i class="light"></i><i class="light"></i>
<span class="bar-title">Codex + TAPL</span><span class="sample">{copy["example"]}</span></div>
<div class="content"><div class="user"><b>YOU</b>{copy["user"]}</div><div class="rows">{rows}</div></div>
<div class="bottom"><span>{copy["record"]}</span><span class="db">.tapl/tapl.db</span></div></div>
</body></html>'''


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def screenshot(source, frame, profile):
    args = [CHROME, "--headless", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions", "--disable-background-networking",
            f"--user-data-dir={profile}", "--window-size=1280,720", "--force-device-scale-factor=1",
            f"--screenshot={frame}", source.as_uri()]
    # Some macOS Chrome builds keep the headless process alive after capture.
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(args, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while not frame.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    log.seek(0)
                    raise RuntimeError(log.read().decode(errors="replace")[-3000:])
                time.sleep(.1)
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.terminate()
        finally:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    if not Path(CHROME).exists() or not shutil.which("ffmpeg"):
        raise SystemExit("Install Chrome/Chromium and FFmpeg; set CHROME if needed.")
    with tempfile.TemporaryDirectory(prefix="tapl-readme-") as temporary:
        work = Path(temporary)
        for lang in COPY:
            frames = []
            for stage in range(7):
                source = work / f"{lang}-{stage}.html"
                frame = work / f"{lang}-{stage}.png"
                source.write_text(page(lang, stage), encoding="utf-8")
                screenshot(source, frame, work / f"chrome-{lang}-{stage}")
                frames.append(frame)
            # Keep an accessible still and the editable final composition beside the GIF.
            shutil.copy2(frames[-1], ROOT / f"workflow-{lang}.png")
            (ROOT / f"workflow-{lang}.html").write_text(page(lang, 6), encoding="utf-8")
            sequence = work / f"{lang}.txt"
            # Slow, discrete reveals; final frame remains long enough to read.
            sequence.write_text("".join(f"file '{f}'\nduration {1.4 if i == 0 else 2.2 if i < 6 else 6.0}\n" for i, f in enumerate(frames)) + f"file '{frames[-1]}'\n", encoding="utf-8")
            run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(sequence),
                "-filter_complex", "[0:v]fps=5,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3",
                "-loop", "0", str(ROOT / f"workflow-{lang}.gif"))
            print(f"{lang}: GIF + PNG + editable HTML generated")


if __name__ == "__main__":
    main()
