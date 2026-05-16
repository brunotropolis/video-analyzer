#!/usr/bin/env python3
"""
Servidor web para o Analisador de Vídeo.
Uso: python video_analyzer_web.py
Acesse: http://localhost:3340
"""

import asyncio
import json
import os
import queue
import sys
import tempfile
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse

sys.path.insert(0, str(Path(__file__).parent))

app = FastAPI()

# ── HTML da interface ─────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Analisador de Vídeo</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  body { background: #0d0d0d; color: #e5e7eb; font-family: system-ui, sans-serif; }
  .card { background: #161616; border: 1px solid #2a2a2a; border-radius: 12px; }
  .tab-btn { transition: all .2s; cursor: pointer; }
  .tab-btn.active { background: #6366f1; color: white; }
  .tab-btn:not(.active):hover { background: #1f2937; }
  .step { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-radius: 8px; transition: all .3s; }
  .step.pending { color: #6b7280; }
  .step.active { color: #a5b4fc; background: #1e1b4b; }
  .step.done { color: #86efac; }
  .step.error { color: #fca5a5; }
  .step-icon { width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; flex-shrink: 0; }
  .step.pending .step-icon { background: #374151; }
  .step.active .step-icon { background: #4338ca; animation: pulse 1.5s infinite; }
  .step.done .step-icon { background: #166534; }
  .step.error .step-icon { background: #991b1b; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.5} }
  .prose h2 { color: #a5b4fc; font-size: 1.1rem; font-weight: 700; margin: 1.5rem 0 .5rem; }
  .prose p { margin: .5rem 0; line-height: 1.7; }
  .prose strong { color: #c4b5fd; }
  .prose ul { list-style: disc; padding-left: 1.5rem; margin: .5rem 0; }
  .prose li { margin: .25rem 0; line-height: 1.6; }
  .prose table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
  .prose th { background: #1e1b4b; padding: 8px 12px; text-align: left; color: #a5b4fc; }
  .prose td { padding: 8px 12px; border-bottom: 1px solid #2a2a2a; }
  .prose hr { border-color: #2a2a2a; margin: 1.5rem 0; }
  .transcript-line { padding: 4px 0; border-bottom: 1px solid #1f1f1f; line-height: 1.5; }
  .ts { color: #6366f1; font-weight: 600; font-size: .8rem; font-family: monospace; margin-right: 6px; }
  #url-input:focus { outline: none; border-color: #6366f1; box-shadow: 0 0 0 3px rgba(99,102,241,.2); }
  .btn-primary { background: #6366f1; transition: all .2s; }
  .btn-primary:hover:not(:disabled) { background: #4f46e5; }
  .btn-primary:disabled { opacity: .5; cursor: not-allowed; }
  ::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-track { background: #111; } ::-webkit-scrollbar-thumb { background: #374151; border-radius: 3px; }
</style>
</head>
<body class="min-h-screen p-4 md:p-8">

<div class="max-w-4xl mx-auto">

  <!-- Header -->
  <div class="mb-8 text-center">
    <h1 class="text-3xl font-bold mb-1" style="color:#a5b4fc">🎬 Analisador de Vídeo</h1>
    <p class="text-gray-500 text-sm">Reels · TikTok · YouTube Shorts · YouTube</p>
  </div>

  <!-- Formulário -->
  <div class="card p-6 mb-6">
    <div class="mb-4">
      <input id="url-input" type="url"
        placeholder="Cole o link do vídeo aqui..."
        class="w-full bg-black border border-gray-700 rounded-lg px-4 py-3 text-white placeholder-gray-600 text-base"
        style="transition:border-color .2s,box-shadow .2s"
      />
    </div>
    <div class="flex flex-wrap gap-3 mb-4">
      <div>
        <label class="text-xs text-gray-500 block mb-1">Modelo Whisper</label>
        <select id="opt-modelo" class="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200">
          <option value="tiny">tiny (rápido)</option>
          <option value="small" selected>small (recomendado)</option>
          <option value="medium">medium (preciso)</option>
          <option value="large-v3">large-v3 (máximo)</option>
        </select>
      </div>
      <div>
        <label class="text-xs text-gray-500 block mb-1">Idioma</label>
        <select id="opt-lang" class="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200">
          <option value="pt" selected>Português</option>
          <option value="en">English</option>
          <option value="es">Español</option>
          <option value="auto">Auto-detectar</option>
        </select>
      </div>
      <div class="flex items-end gap-2 pb-1">
        <label class="flex items-center gap-2 cursor-pointer select-none">
          <div class="relative">
            <input type="checkbox" id="opt-so-transcricao" class="sr-only peer">
            <div class="w-10 h-5 bg-gray-700 peer-checked:bg-indigo-600 rounded-full transition"></div>
            <div class="absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition peer-checked:translate-x-5"></div>
          </div>
          <span class="text-sm text-gray-400">Só transcrição</span>
        </label>
      </div>
    </div>
    <button id="btn-analisar" onclick="iniciarAnalise()"
      class="btn-primary w-full text-white font-semibold py-3 rounded-lg text-base">
      Analisar Vídeo
    </button>
  </div>

  <!-- Progresso -->
  <div id="section-progresso" class="card p-6 mb-6 hidden">
    <div class="flex items-center gap-2 mb-4">
      <div id="prog-spinner" class="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin hidden"></div>
      <h2 class="font-semibold text-gray-300">Processando...</h2>
    </div>
    <div class="space-y-1">
      <div id="step-1" class="step pending">
        <div class="step-icon">⬇</div>
        <span class="text-sm" id="step-1-msg">Download</span>
      </div>
      <div id="step-2" class="step pending">
        <div class="step-icon">🎤</div>
        <span class="text-sm" id="step-2-msg">Transcrição</span>
      </div>
      <div id="step-3" class="step pending">
        <div class="step-icon">🖼</div>
        <span class="text-sm" id="step-3-msg">Extração de frames</span>
      </div>
      <div id="step-4" class="step pending">
        <div class="step-icon">🤖</div>
        <span class="text-sm" id="step-4-msg">Análise Claude Vision</span>
      </div>
    </div>
    <div id="prog-erro" class="mt-4 p-3 bg-red-950 border border-red-800 rounded-lg text-red-300 text-sm hidden"></div>
  </div>

  <!-- Resultados -->
  <div id="section-resultado" class="card p-6 hidden">
    <!-- Meta -->
    <div id="result-meta" class="mb-4 pb-4 border-b border-gray-800"></div>

    <!-- Tabs -->
    <div class="flex gap-2 mb-4" id="tabs-container">
      <button class="tab-btn active px-4 py-2 rounded-lg text-sm font-medium" onclick="switchTab('transcricao')">
        📝 Transcrição
      </button>
      <button id="tab-btn-analise" class="tab-btn px-4 py-2 rounded-lg text-sm font-medium text-gray-500" onclick="switchTab('analise')">
        🎬 Análise Visual
      </button>
      <button id="tab-btn-prompt" class="tab-btn px-4 py-2 rounded-lg text-sm font-medium text-gray-500" onclick="switchTab('prompt')">
        🎯 Prompt de Edição
      </button>
    </div>

    <!-- Painel Transcrição -->
    <div id="tab-transcricao">
      <div class="flex justify-end mb-2">
        <button onclick="copiar('transcricao-raw')" class="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1">
          📋 Copiar texto
        </button>
      </div>
      <div id="transcricao-content" class="text-sm text-gray-300 max-h-96 overflow-y-auto pr-1"></div>
      <textarea id="transcricao-raw" class="hidden"></textarea>
    </div>

    <!-- Painel Análise Visual -->
    <div id="tab-analise" class="hidden">
      <div class="flex justify-end mb-2">
        <button onclick="copiar('analise-raw')" class="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1">
          📋 Copiar texto
        </button>
      </div>
      <div id="analise-content" class="prose text-sm text-gray-300 max-h-[600px] overflow-y-auto pr-1"></div>
      <textarea id="analise-raw" class="hidden"></textarea>
    </div>

    <!-- Painel Prompt de Edição -->
    <div id="tab-prompt" class="hidden">
      <div class="flex justify-end mb-2">
        <button onclick="copiar('prompt-raw')" class="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1">
          📋 Copiar prompt
        </button>
      </div>
      <div id="prompt-content" class="prose text-sm text-gray-300 max-h-[600px] overflow-y-auto pr-1"></div>
      <textarea id="prompt-raw" class="hidden"></textarea>
    </div>

    <!-- Botões finais -->
    <div class="mt-6 pt-4 border-t border-gray-800 flex gap-3">
      <button onclick="baixarRelatorio()" class="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1">
        💾 Baixar .md
      </button>
      <button onclick="novaAnalise()" class="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1">
        🔄 Nova análise
      </button>
    </div>
  </div>

</div>

<script>
let activeTab = 'transcricao';
let relatorioCompleto = '';
let eventoSource = null;

function switchTab(tab) {
  activeTab = tab;
  ['transcricao', 'analise', 'prompt'].forEach(t => {
    document.getElementById(`tab-${t}`).classList.toggle('hidden', tab !== t);
  });
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  const idx = ['transcricao', 'analise', 'prompt'].indexOf(tab);
  if (idx >= 0) document.querySelectorAll('.tab-btn')[idx].classList.add('active');
}

function setStep(num, state, msg) {
  const el = document.getElementById(`step-${num}`);
  const msgEl = document.getElementById(`step-${num}-msg`);
  el.className = `step ${state}`;
  if (msg) msgEl.textContent = msg;
  const icons = { pending: ['⬇','🎤','🖼','🤖'], done: ['✓','✓','✓','✓'], error: ['✗','✗','✗','✗'] };
  const iconEl = el.querySelector('.step-icon');
  if (state === 'active') iconEl.innerHTML = '<div class="w-3 h-3 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin"></div>';
  else if (state === 'done') iconEl.textContent = '✓';
  else if (state === 'error') iconEl.textContent = '✗';
  else iconEl.textContent = icons.pending[num - 1];
}

function iniciarAnalise() {
  const url = document.getElementById('url-input').value.trim();
  if (!url) { alert('Cole uma URL de vídeo antes de continuar.'); return; }

  const modelo = document.getElementById('opt-modelo').value;
  const lang = document.getElementById('opt-lang').value;
  const soTranscricao = document.getElementById('opt-so-transcricao').checked;

  document.getElementById('btn-analisar').disabled = true;
  document.getElementById('section-progresso').classList.remove('hidden');
  document.getElementById('section-resultado').classList.add('hidden');
  document.getElementById('prog-erro').classList.add('hidden');
  document.getElementById('prog-spinner').classList.remove('hidden');
  [1,2,3,4].forEach(i => setStep(i, 'pending'));

  if (soTranscricao) {
    document.getElementById('step-3').style.opacity = '.3';
    document.getElementById('step-4').style.opacity = '.3';
  } else {
    document.getElementById('step-3').style.opacity = '1';
    document.getElementById('step-4').style.opacity = '1';
  }

  const params = new URLSearchParams({ url, modelo, lang, so_transcricao: soTranscricao });
  eventoSource = new EventSource(`/analyze?${params}`);

  eventoSource.onmessage = (e) => {
    const data = JSON.parse(e.data);

    if (data.type === 'step') {
      const n = data.step;
      // marcar steps anteriores como done
      for (let i = 1; i < n; i++) setStep(i, 'done');
      setStep(n, 'active', data.message);
    }
    else if (data.type === 'result') {
      eventoSource.close();
      mostrarResultado(data);
    }
    else if (data.type === 'error') {
      eventoSource.close();
      document.getElementById('prog-spinner').classList.add('hidden');
      document.getElementById('prog-erro').textContent = '❌ ' + data.message;
      document.getElementById('prog-erro').classList.remove('hidden');
      document.getElementById('btn-analisar').disabled = false;
    }
  };

  eventoSource.onerror = () => {
    eventoSource.close();
    document.getElementById('prog-spinner').classList.add('hidden');
    document.getElementById('prog-erro').textContent = '❌ Conexão perdida. Tente novamente.';
    document.getElementById('prog-erro').classList.remove('hidden');
    document.getElementById('btn-analisar').disabled = false;
  };
}

function mostrarResultado(data) {
  [1,2,3,4].forEach(i => setStep(i, 'done'));
  document.getElementById('prog-spinner').classList.add('hidden');

  // Meta
  const m = data.meta;
  const dur = formatTs(m.duracao || 0);
  let metaHtml = `<div class="flex flex-wrap gap-4 text-sm">
    <div><span class="text-gray-500">Título</span><div class="text-white font-medium mt-0.5">${escHtml(m.titulo)}</div></div>
    <div><span class="text-gray-500">Plataforma</span><div class="text-indigo-400 mt-0.5">${escHtml(m.plataforma)}</div></div>
    <div><span class="text-gray-500">Criador</span><div class="text-gray-300 mt-0.5">${escHtml(m.uploader || '—')}</div></div>
    <div><span class="text-gray-500">Duração</span><div class="text-gray-300 mt-0.5">${dur}</div></div>`;
  if (m.views) metaHtml += `<div><span class="text-gray-500">Views</span><div class="text-gray-300 mt-0.5">${fmtNum(m.views)}</div></div>`;
  metaHtml += '</div>';
  document.getElementById('result-meta').innerHTML = metaHtml;

  // Transcrição
  const transcEl = document.getElementById('transcricao-content');
  let transcRaw = '';
  if (data.transcricao && data.transcricao.length) {
    transcEl.innerHTML = data.transcricao.map(s =>
      `<div class="transcript-line"><span class="ts">[${formatTs(s.start)}]</span>${escHtml(s.text)}</div>`
    ).join('');
    transcRaw = data.transcricao.map(s => `[${formatTs(s.start)}] ${s.text}`).join('\\n');
  } else {
    transcEl.innerHTML = '<p class="text-gray-600 italic">Nenhuma fala detectada.</p>';
  }
  document.getElementById('transcricao-raw').value = transcRaw;

  // Análise visual
  const analiseEl = document.getElementById('analise-content');
  if (data.analise) {
    analiseEl.innerHTML = marked.parse(data.analise);
    document.getElementById('analise-raw').value = data.analise;
    document.getElementById('tab-btn-analise').classList.remove('text-gray-500');
  } else {
    analiseEl.innerHTML = '<p class="text-gray-600 italic">Análise visual não solicitada.</p>';
  }

  // Relatório completo para download
  relatorioCompleto = data.relatorio;

  document.getElementById('section-resultado').classList.remove('hidden');
  document.getElementById('section-resultado').scrollIntoView({ behavior: 'smooth', block: 'start' });
  document.getElementById('btn-analisar').disabled = false;

  // Prompt de edição
  const promptEl = document.getElementById('prompt-content');
  if (data.prompt_edicao) {
    promptEl.innerHTML = marked.parse(data.prompt_edicao);
    document.getElementById('prompt-raw').value = data.prompt_edicao;
    document.getElementById('tab-btn-prompt').classList.remove('text-gray-500');
  } else {
    promptEl.innerHTML = '<p class="text-gray-600 italic">Prompt não disponível (requer análise visual).</p>';
  }

  // se não tem análise, esconde tabs visuais
  if (!data.analise) {
    document.getElementById('tab-btn-analise').style.display = 'none';
    document.getElementById('tab-btn-prompt').style.display = 'none';
  }
}

function copiar(id) {
  const el = document.getElementById(id);
  const text = el.tagName === 'TEXTAREA' ? el.value : el.innerText;
  navigator.clipboard.writeText(text).then(() => {
    const btns = document.querySelectorAll(`[onclick="copiar('${id}')"]`);
    btns.forEach(b => { const orig = b.textContent; b.textContent = '✓ Copiado!'; setTimeout(() => b.textContent = orig, 2000); });
  });
}

function baixarRelatorio() {
  if (!relatorioCompleto) return;
  const blob = new Blob([relatorioCompleto], { type: 'text/markdown;charset=utf-8' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = 'analise_video.md'; a.click();
}

function novaAnalise() {
  document.getElementById('url-input').value = '';
  document.getElementById('section-progresso').classList.add('hidden');
  document.getElementById('section-resultado').classList.add('hidden');
  document.getElementById('btn-analisar').disabled = false;
  document.getElementById('url-input').focus();
}

function formatTs(s) {
  s = Math.max(0, s || 0);
  const m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return `${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
}

function fmtNum(n) { return new Intl.NumberFormat('pt-BR').format(n); }

function escHtml(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

document.getElementById('url-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') iniciarAnalise();
});
</script>
</body>
</html>"""


# ── Endpoint principal ────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def root():
    return HTML


@app.get("/analyze")
async def analyze(
    url: str = Query(...),
    modelo: str = Query("small"),
    lang: str = Query("pt"),
    so_transcricao: bool = Query(False),
):
    q: queue.Queue = queue.Queue()

    def _run():
        try:
            import analisar_video as av

            api_key = None if so_transcricao else av.load_api_key()

            def log(msg: str):
                if msg.startswith("step:"):
                    parts = msg.split(":", 2)
                    step_num = int(parts[1])
                    step_msg = parts[2] if len(parts) > 2 else ""
                    q.put({"type": "step", "step": step_num, "message": step_msg})
                # mensagens sem prefixo são ignoradas no SSE

            with tempfile.TemporaryDirectory(prefix="analisar_video_") as tmp:
                tmp_dir = Path(tmp)

                instagram_session = os.environ.get("INSTAGRAM_SESSION_ID")
                tiktok_session = os.environ.get("TIKTOK_SESSION_ID")
                youtube_3psid = os.environ.get("YOUTUBE_SECURE_3PSID")
                video_path, meta = av.download_video(
                    url, tmp_dir, log=log,
                    session_id=instagram_session,
                    tiktok_session_id=tiktok_session,
                    youtube_3psid=youtube_3psid,
                )
                transcricao = av.transcrever(video_path, modelo, lang, "cpu", log=log)

                analise = None
                prompt_edicao = None
                if not so_transcricao:
                    duracao = float(meta.get("duracao") or 30)
                    frames = av.extrair_frames(video_path, duracao, tmp_dir, None, log=log)
                    analise = av.analisar_visual(frames, meta, transcricao, api_key, log=log)
                    prompt_edicao = av.gerar_prompt_edicao(analise, meta, transcricao, api_key, log=log)

                relatorio = av.gerar_relatorio(meta, transcricao, analise)

                q.put({
                    "type": "result",
                    "meta": meta,
                    "transcricao": transcricao,
                    "analise": analise,
                    "prompt_edicao": prompt_edicao,
                    "relatorio": relatorio,
                })

        except Exception as e:
            q.put({"type": "error", "message": str(e)})

        finally:
            q.put(None)  # sentinel

    threading.Thread(target=_run, daemon=True).start()

    async def event_gen():
        loop = asyncio.get_event_loop()
        while True:
            event = await loop.run_in_executor(None, q.get)
            if event is None:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Analisador de Video -- http://localhost:3340")
    uvicorn.run(app, host="0.0.0.0", port=3340, log_level="warning")
