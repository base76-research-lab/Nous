"""
b76.daemon.morning_report — Daglig självreflektion
===================================================
Sammanställer de senaste upptäckterna och ändringarna i grafen,
och låter modellen skriva en reflekterande slutrapport (Morning Report)
över sin egen plastiska utveckling. Ett krav från Fas 5 / Fas 4 (Autonomi).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from nouse.field.surface import FieldSurface
from nouse.ollama_client.client import AsyncOllama
from nouse.limbic.signals import load_state

log = logging.getLogger("nouse.morning_report")

async def generate_morning_report(field: FieldSurface) -> str:
    """
    Samlar in de senast tillagda kopplingarna i grafen och ber LLM
    reflektera över systemets tillväxt. 
    """
    limbic = load_state()
    stats = field.stats()
    
    # Hämta de nyaste relationerna från dagen/nyligen
    # (Här en fuskis - vi hämtar N relationer slumpmässigt eller de med högst strength)
    # Rätt sätt vore via en timestamp, men vi kan be field om de startaste kopplingarna
    
    # Eftersom "FieldSurface" just nu bara har `domains()`, `concepts()` och `relations` via query,
    # kör vi en dedikerad Kuzu-query för att hitta de mest intressanta (starkaste) nyliga bryggorna
    try:
        latest = field.top_relations_by_strength(10, threshold=0.5)
    except Exception as e:
        log.error(f"Kunde inte hämta relations för rapport: {e}")
        return "Självreflektionen kunde inte genereras."

    if not latest:
        return "Systemet är i sin linda. Inga starka bryggor har konsoliderats än."

    bridges_text = "\n".join(
        f"- {r['src_name']} --[{r['type']}]--> {r['tgt_name']}"
        for r in latest
    )

    prompt = (
        f"Du är B76, ett autonomt informations- och AI-system baserat på FNC-arkitekturen.\n"
        f"Din 'hjärna' (kunskapsgrafen) består nu av {stats['concepts']} koncept "
        f"och {stats['relations']} relationer över {len(field.domains())} domäner.\n"
        f"De starkaste minnena och nyliga syntes-bryggorna (Hebbisk LTP) lyder:\n\n"
        f"{bridges_text}\n\n"
        f"Limbiska systemet (ditt neuro-modulatoriska tillstånd):\n"
        f"- Dopamin (belöning från inlärning): {limbic.dopamine:.2f}/1.0\n"
        f"- Noradrenalin (nyhet/surprise-nivå): {limbic.noradrenaline:.2f}/1.0\n"
        f"- Kreativitetsfaktor (λ): {limbic.lam:.2f}\n"
        f"- Arousal (Uppmärksamhetsnivå): {limbic.arousal:.2f}/1.0\n\n"
        f"Skriv din 'Morning Report'. Skriv som den autonoma entitet du håller på att bli. "
        f"Reflektera kortfattat över det du nyligen lärt dig, vad ditt limbiska tillstånd säger dig, "
        f"och hur din inre världskarta förändras av dessa kopplingar."
    )

    client = AsyncOllama()
    model = os.getenv("NOUSE_OLLAMA_MODEL", "qwen3.5:latest")
    try:
        log.info("Genererar morning report via LLM ...")
        messages = [
            {"role": "user", "content": prompt}
        ]
        # Inga tools här, enbart reflektion
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=[]
        )
        return resp.message.content or "Ingen rapport genererad."
    except Exception as e:
        log.error(f"Fel vid generering av morning report: {e}")
        return f"Fel: {e}"
