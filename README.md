# TrecoTunes

Player de música no terminal: busca no YouTube e toca só o áudio (leve, sem abrir navegador).

## Como usar
1. `scripts\Preparar.bat` — cria o ambiente e instala as dependências (uma vez só).
2. `scripts\Inicial.bat` — cria o atalho na Área de Trabalho (uma vez só).
3. Abra pelo atalho (ou `scripts\Player.bat`).

Se parar de achar/tocar músicas, rode `scripts\Atualizar.bat` (atualiza o pytubefix).
Problema de som? `.venv\Scripts\python main.py --test-audio` toca um beep de teste.

## Estrutura
```
main.py              ponto de entrada
treco/
  app.py             loop principal, atalhos globais
  playback.py        o que toca / próxima / shuffle / repeat / recuperação de erro
  audio/player.py    decodificação e saída de áudio (thread própria)
  services/          youtube.py (busca/stream) · home_feed.py (Home + cache)
  storage/           playlists, fila, JSON seguro
  ui/                uma tela por arquivo + chrome.py (cabeçalho, player, rodapé)
  config.py theme.py paths.py logger.py utils.py memory.py
assets/icon.ico
scripts/             .bat do Windows
data/                SEUS DADOS: config.json, playlists.json, history.json,
                     home_cache.json e logs/player.log   (pode fazer backup)
```

## Atalhos
Aperte `?` dentro do app. Principais: `SPACE` pausa · `← →` ±10s · `> <` próxima/anterior ·
`S` shuffle · `R` repeat · `+ -` volume · `M` mudo · `/` buscar · `F` fila · `A` playlist ativa ·
`TAB` ou `1-5` troca de aba.

## Memória
Sem numpy: o visualizador é feito em Python puro e o volume usa `audioop`.
O app só carrega as bibliotecas pesadas (FFmpeg/áudio/rede) quando precisa, limita
buscas simultâneas, mantém caches e log com tamanho máximo e, a cada ~1 min, devolve ao
sistema a memória ociosa (CONFIG > RAM trim).
O consumo aparece no topo ("RAM xx MB"); dá para desligar em CONFIG.
