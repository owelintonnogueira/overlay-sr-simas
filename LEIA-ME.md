# ✂ Cortes de Live

Solte um vídeo grande (ou cole um link), escolha **quantos cortes** e **quanto tempo** cada um deve ter. O programa acha os melhores momentos, corta e coloca **legenda** automaticamente. 100% grátis e roda no seu PC (sem API paga, sem assinatura).

## Como conseguir o instalador (.exe)

O `.exe` de Windows precisa ser montado num Windows. Escolha **uma** das formas:

**A) No seu PC (mais simples)** — dê dois cliques em `CONSTRUIR_INSTALADOR.bat`.
Ele baixa tudo sozinho (Python, ffmpeg, deno, Inno Setup) e cria `installer_output\CortesLive-Setup.exe`. Leva ~10–25 min na primeira vez.

**B) Pelo GitHub (sem instalar nada)** — suba esta pasta num repositório seu, vá em *Actions → Gerar instalador (Windows) → Run workflow*. Ao terminar, baixe `CortesLive-Setup` em *Artifacts*.

Depois é só dar dois cliques no `CortesLive-Setup.exe` e instalar. *(Se o Windows mostrar "SmartScreen", clique em "Mais informações → Executar assim mesmo": o instalador não é assinado digitalmente.)*

Quer só testar antes de instalar? `RODAR_SEM_INSTALAR.bat`.

## Como usar

1. Arraste o vídeo para a janela, **ou** cole um link (YouTube, Twitch, Kick, TikTok, Instagram, X…).
2. Escolha a **quantidade de cortes** (1 a 200) e a **duração** (presets ou mín./máx. em segundos).
3. Escolha o **formato**: horizontal, vertical com recorte central ou vertical com fundo desfocado (Shorts/Reels/TikTok).
4. Clique em **Gerar cortes**. Os arquivos ficam em `Vídeos\CortesLive\<nome do vídeo>\cortes\`, numerados do melhor (`01`) para o pior, junto com `resumo_cortes.txt` (horários, motivo da escolha e trecho da fala).

Desempenho (placa de vídeo + processador):
- **Limite do processador (%)**: padrão 80%. No Windows o teto é imposto de verdade (nenhum núcleo extra é usado além disso), então o PC esquenta menos e continua fluido.
- **Placa de vídeo – Automática**: com placa **NVIDIA**, a transcrição roda nela (na primeira vez o programa pede para baixar ~600 MB de bibliotecas gratuitas da NVIDIA) e o vídeo é codificado por NVENC. Com **Intel/AMD**, só a codificação do vídeo usa a placa (Quick Sync / AMF). Se a placa recusar algo, ele volta sozinho para o processador.

Legenda personalizável (botão **🎨 Personalizar legenda…**): estilo pronto, fonte, tamanho, altura na tela (ou posição rápida: embaixo / meio / topo), alinhamento esquerda-centro-direita, cores, contorno, caixa escura, palavras por linha, MAIÚSCULAS e destaque da palavra falada — com prévia usando um quadro do seu próprio vídeo.

Dicas:
- Já processou uma live e quer **mais cortes ou outra duração**? Rode de novo: a transcrição é reaproveitada (leva só o tempo do corte).
- Link do YouTube pedindo login / "confirme que não é um robô"? Escolha seu navegador em **Cookies do navegador**.
- Modelo **small** é o equilíbrio recomendado. Use **tiny/base** se o PC for fraco; **medium** para mais precisão (bem mais lento).
- Tempo estimado em PC comum (sem placa de vídeo): a transcrição leva de ~1/4 a 1/2 da duração da live com o modelo *small*.

## Como ele escolhe os melhores momentos

Sem IA paga. Combina três sinais, todos locais:
1. **Áudio**: trechos bem mais altos que o resto da live (gritos, risadas, empolgação).
2. **Fala**: trechos com a conversa acelerada.
3. **Texto**: expressões marcantes ("meu deus", "não acredito", "wow", "clutch"…), exclamações e risadas na transcrição (lista em `app/highlights.py`, `LEXICON` — dá para ampliar).

Os cortes começam e terminam em limites naturais de frase, nunca se sobrepõem, e respeitam a duração que você pediu. É uma heurística: acerta bem em lives de jogo/reação/humor, mas não "entende" o assunto — vale dar uma olhada nos cortes antes de postar.

## O que tem dentro

| Peça | Para quê | Custo |
|---|---|---|
| faster-whisper | transcrição + legenda (local) | grátis |
| yt-dlp + deno | baixar de links | grátis |
| ffmpeg | cortar, legendar, formatar | grátis |
| PyInstaller + Inno Setup | `.exe` + instalador | grátis |

Observações: na primeira transcrição o modelo de voz é baixado da internet (uma vez só, ~150 MB a ~1,5 GB conforme o modelo). O ffmpeg embutido é a build GPL da BtbN (inclui libx264 e libass).
