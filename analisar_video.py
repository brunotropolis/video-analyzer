#!/usr/bin/env python3
"""
Analisa vídeos de redes sociais: transcrição + análise visual de edição.

Plataformas: Instagram Reels, TikTok, YouTube Shorts, YouTube

Uso:
    python analisar_video.py <url>
    python analisar_video.py <url> --so-transcricao
    python analisar_video.py <url> --modelo medium --lang auto --salvar
    python analisar_video.py <url> --frames 3

Opções:
    --modelo      tiny|base|small|medium|large-v3 (padrão: small)
    --lang        pt|en|es|auto (padrão: pt)
    --so-transcricao  Pula análise visual
    --salvar      Salva relatório .md na pasta atual
    --frames      Intervalo em segundos entre frames (padrão: automático)
    --device      cpu ou cuda (padrão: cpu)
"""

import argparse
import base64
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

# ── Configuração ──────────────────────────────────────────────────────────────

ENV_FILES = [
    Path("D:/CLAUDE/.env.meta"),
    Path("D:/CLAUDE/telegram-captador/.env"),
]

FFMPEG = "ffmpeg"
MAX_FRAMES = 20
MODEL_VISUAL = "claude-sonnet-4-6"


def _log(fn: Callable | None, msg: str):
    if fn:
        fn(msg)
    else:
        print(msg, file=sys.stderr)


def load_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    for env_file in ENV_FILES:
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.split("=", 1)[1].strip()
    raise SystemExit(
        "ERRO: ANTHROPIC_API_KEY não encontrada.\n"
        "Adicione ao D:\\CLAUDE\\.env.meta ou defina a variável de ambiente."
    )


# ── Download ──────────────────────────────────────────────────────────────────

def download_video(url: str, output_dir: Path, log: Callable | None = None) -> tuple[Path, dict]:
    import yt_dlp

    _log(log, "step:1:Baixando vídeo...")

    last_pct = [0]

    def _progress_hook(d):
        if d["status"] == "downloading":
            pct_str = d.get("_percent_str", "").strip()
            try:
                pct = int(float(pct_str.replace("%", "")))
            except (ValueError, AttributeError):
                pct = 0
            if pct >= last_pct[0] + 10:
                last_pct[0] = pct
                spd = d.get("_speed_str", "").strip()
                _log(log, f"step:1:Baixando {pct_str} — {spd}")
        elif d["status"] == "finished":
            _log(log, "step:1:Download concluído, mesclando streams...")

    output_template = str(output_dir / "video.%(ext)s")
    ydl_opts = {
        "outtmpl": output_template,
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "progress_hooks": [_progress_hook],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    candidates = sorted(output_dir.glob("video.*"))
    if not candidates:
        raise FileNotFoundError("Arquivo de vídeo não encontrado após download.")
    video_path = candidates[0]

    if video_path.suffix.lower() != ".mp4":
        mp4_path = output_dir / "video.mp4"
        subprocess.run(
            [FFMPEG, "-i", str(video_path), "-c", "copy", str(mp4_path), "-y", "-loglevel", "error"],
            check=True,
        )
        video_path = mp4_path

    duracao = info.get("duration") or _probe_duracao(video_path)

    meta = {
        "titulo":     info.get("title", "Sem título"),
        "duracao":    duracao,
        "plataforma": info.get("extractor_key", ""),
        "uploader":   info.get("uploader", ""),
        "descricao":  (info.get("description") or "")[:400],
        "views":      info.get("view_count"),
        "likes":      info.get("like_count"),
        "url":        url,
    }

    _log(log, f"step:1:✓ '{meta['titulo']}' ({_fmt_ts(duracao)})")
    return video_path, meta


def _probe_duracao(video_path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 60.0


# ── Transcrição ───────────────────────────────────────────────────────────────

def transcrever(
    video_path: Path,
    modelo: str,
    lang: str,
    device: str,
    log: Callable | None = None,
) -> list[dict]:
    from faster_whisper import WhisperModel

    compute_type = "int8" if device == "cpu" else "float16"
    _log(log, f"step:2:Transcrevendo com Whisper '{modelo}'...")

    model = WhisperModel(modelo, device=device, compute_type=compute_type)
    language = None if lang == "auto" else lang
    segments, info = model.transcribe(
        str(video_path), language=language, vad_filter=True, beam_size=5
    )
    _log(log, f"step:2:Idioma: {info.language} ({info.language_probability:.0%})")

    result = []
    for s in segments:
        result.append({"start": s.start, "end": s.end, "text": s.text.strip()})

    _log(log, f"step:2:✓ {len(result)} segmentos transcritos")
    return result


# ── Extração de frames ────────────────────────────────────────────────────────

def extrair_frames(
    video_path: Path,
    duracao: float,
    output_dir: Path,
    intervalo: float | None,
    log: Callable | None = None,
) -> list[tuple[float, Path]]:
    if intervalo is None:
        intervalo = 2.0 if duracao < 120 else 5.0

    n_frames = min(max(int(duracao / intervalo), 3), MAX_FRAMES)
    timestamps = [i * duracao / (n_frames - 1) for i in range(n_frames)] if n_frames > 1 else [duracao / 2]
    timestamps = [min(t, duracao - 0.2) for t in timestamps]

    _log(log, f"step:3:Extraindo {n_frames} frames (1 a cada ~{intervalo:.0f}s)...")

    frames = []
    for i, ts in enumerate(timestamps):
        out = output_dir / f"frame_{i:03d}.jpg"
        subprocess.run(
            [FFMPEG, "-ss", f"{ts:.2f}", "-i", str(video_path),
             "-vframes", "1", "-q:v", "3",
             "-vf", "scale=640:-2",
             "-pix_fmt", "yuvj420p",
             str(out), "-y", "-loglevel", "error"],
            check=True,
        )
        if out.exists():
            frames.append((ts, out))

    _log(log, f"step:3:✓ {len(frames)} frames extraídos")
    return frames


# ── Análise visual via Claude Vision ─────────────────────────────────────────

def analisar_visual(
    frames: list[tuple[float, Path]],
    meta: dict,
    transcricao: list[dict],
    api_key: str,
    log: Callable | None = None,
) -> str:
    import anthropic

    _log(log, f"step:4:Analisando com Claude Vision ({MODEL_VISUAL})...")

    client = anthropic.Anthropic(api_key=api_key)
    duracao = meta.get("duracao", 0)

    content = []
    for ts, frame_path in frames:
        img_data = base64.standard_b64encode(frame_path.read_bytes()).decode()
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": img_data},
        })
        content.append({
            "type": "text",
            "text": f"▶ Frame {_fmt_ts(ts)} de {_fmt_ts(duracao)}",
        })

    trecho = " | ".join(f"{_fmt_ts(s['start'])}: {s['text']}" for s in transcricao[:40])
    if not trecho:
        trecho = "(sem fala detectada)"

    content.append({
        "type": "text",
        "text": f"""Analise a linha de edição visual deste vídeo de redes sociais.

METADADOS:
- Título: {meta.get('titulo')}
- Plataforma: {meta.get('plataforma')}
- Criador: {meta.get('uploader')}
- Duração: {_fmt_ts(duracao)} ({duracao:.0f}s)

TRANSCRIÇÃO (referência):
{trecho}

---

Produza uma análise estruturada em português cobrindo:

## 🎣 Hook (primeiros 3-5 segundos)
O que aparece visualmente no início. Como prende atenção. Tipo de abertura.

## 🎬 Timeline Visual
Para cada frame, descreva em 1-2 linhas: enquadramento, o que está acontecendo, texto na tela.
Use o timestamp. Exemplo: **[00:03]** — Talking head, close no rosto, legenda "Você sabia que...".

## ✂️ Ritmo e Edição
Velocidade dos cortes, transições, padrão de edição, sincronismo com fala.

## 🎥 Composição Visual
Tipos de shot (talking head / B-roll / texto animado / gráficos), qualidade de produção.

## 📝 Textos e Elementos Gráficos
Legendas, textos sobrepostos, CTAs visuais, watermarks.

## 💡 Estrutura Narrativa e Insights
Estrutura geral, técnicas de retenção, pontos fortes, o que pode ser replicado.
""",
    })

    _log(log, "step:4:Enviando frames para o Claude...")

    response = client.messages.create(
        model=MODEL_VISUAL,
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )

    _log(log, "step:4:✓ Análise concluída")
    return response.content[0].text


# ── Relatório final ───────────────────────────────────────────────────────────

def gerar_relatorio(meta: dict, transcricao: list[dict], analise: str | None) -> str:
    dur = meta.get("duracao", 0)
    linhas = [
        f"# Análise: {meta.get('titulo', 'Sem título')}",
        "",
        f"| Campo | Valor |",
        f"|---|---|",
        f"| Plataforma | {meta.get('plataforma', '—')} |",
        f"| Criador | {meta.get('uploader', '—')} |",
        f"| Duração | {_fmt_ts(dur)} ({dur:.0f}s) |",
    ]
    if meta.get("views"):
        linhas.append(f"| Views | {meta['views']:,} |")
    if meta.get("likes"):
        linhas.append(f"| Likes | {meta['likes']:,} |")
    linhas.append(f"| URL | {meta.get('url', '—')} |")

    linhas += ["", "---", "", "## 📝 Transcrição", ""]
    if transcricao:
        for seg in transcricao:
            linhas.append(f"**[{_fmt_ts(seg['start'])}]** {seg['text']}")
    else:
        linhas.append("_(nenhuma fala detectada)_")

    if analise:
        linhas += ["", "---", "", analise]

    return "\n".join(linhas)


def _fmt_ts(s: float) -> str:
    s = max(0, s)
    m, sec = divmod(int(s), 60)
    return f"{m:02d}:{sec:02d}"


# ── Ponto de entrada (CLI) ────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Transcreve e analisa a edição visual de vídeos de redes sociais."
    )
    ap.add_argument("url", help="URL do vídeo")
    ap.add_argument("--modelo", default="small", metavar="MODELO")
    ap.add_argument("--lang", default="pt", metavar="LANG")
    ap.add_argument("--so-transcricao", action="store_true")
    ap.add_argument("--salvar", action="store_true")
    ap.add_argument("--frames", type=float, default=None, metavar="SEGUNDOS")
    ap.add_argument("--device", default="cpu", metavar="DEVICE")
    args = ap.parse_args()

    api_key = None if args.so_transcricao else load_api_key()

    with tempfile.TemporaryDirectory(prefix="analisar_video_") as tmp:
        tmp_dir = Path(tmp)

        video_path, meta = download_video(args.url, tmp_dir)
        transcricao = transcrever(video_path, args.modelo, args.lang, args.device)

        analise = None
        if not args.so_transcricao:
            duracao = float(meta.get("duracao") or 30)
            frames = extrair_frames(video_path, duracao, tmp_dir, args.frames)
            analise = analisar_visual(frames, meta, transcricao, api_key)

        relatorio = gerar_relatorio(meta, transcricao, analise)
        print("\n" + relatorio)

        if args.salvar:
            titulo_safe = re.sub(r"[^\w\-]", "_", meta.get("titulo", "video"))[:60]
            out_path = Path(f"analise_{titulo_safe}.md")
            out_path.write_text(relatorio, encoding="utf-8")
            print(f"\n[salvo: {out_path.resolve()}]", file=sys.stderr)


if __name__ == "__main__":
    main()
