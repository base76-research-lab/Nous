# Avvecklade systemd-units — 2026-09-14

Avstängda för att göra datorn funktionsstabil. Hjärnloopen + ollama höll
NVIDIA-GPU:n på 95 % och llama-server på ~180 % CPU dygnet runt, vilket
svälte ut Chrome (hängningar, hackig video). Load average föll 3,70 → 0,29.

## Borttagna unit-filer (finns här, kan återställas)
- nouse-daemon.service — Brain Loop, `nouse daemon web --port 8767`
- agentmail-poll.timer / .service — pollade nouse@agentmail.to var 10:e min
  och autosvarade med lokal modell ("standing send authority")

Återställ: kopiera tillbaka till ~/.config/systemd/user/, sedan
`systemctl --user daemon-reload && systemctl --user enable --now <unit>`

## Avaktiverade men kvar på plats
nouse-eval.timer, nouse-backup.timer, nouse-watchdog.timer
(`systemctl --user enable --now <unit>` för att återaktivera)

## Kvar på disken, orört
- Ollama-modeller ~29 GB i /usr/share/ollama/.ollama
- Ollama-binärer 2,1 GB i /usr/local/lib/ollama
