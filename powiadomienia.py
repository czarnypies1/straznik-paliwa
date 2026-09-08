"""
Kanały powiadomień Strażnika.

Każdy kanał ma własną funkcję i własny format - Discord dostaje kolorowy
embed, Telegram wiadomość z lekkim HTML. Wysyłka jest odporna na awarie:
padnięcie jednego kanału nie zatrzymuje drugiego, a brak konfiguracji
kanału po prostu go pomija zamiast wywalać cały skrypt.

Sekrety czytamy wyłącznie ze zmiennych środowiskowych. W kodzie nie ma
i nie może być żadnego tokena.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

from analiza import skutek_dla_baku

CZAS_OCZEKIWANIA = 20

# Kolory pasków bocznych w Discordzie
KOLORY = {
    "TANKUJ": 0xE74C3C,   # czerwony - drożeje, tankuj zanim wejdzie na pylon
    "CZEKAJ": 0x2ECC71,   # zielony - tanieje, poczekaj
    "UWAGA": 0xF39C12,    # pomarańczowy - ruch na ropie, hurt jeszcze śpi
    "SPOKOJ": 0x95A5A6,   # szary - nic się nie dzieje
    "START": 0x3498DB,    # niebieski - pierwsze uruchomienie
    "BLAD": 0x9B59B6,     # fioletowy - problem ze źródłem
}

NAGLOWKI_SYGNALU = {
    "TANKUJ": "TANKUJ TERAZ",
    "CZEKAJ": "POCZEKAJ Z TANKOWANIEM",
    "UWAGA": "UWAGA NA RYNKU ROPY",
    "SPOKOJ": "Bez zmian",
    "START": "Strażnik Paliwa uruchomiony",
}

WYJASNIENIA = {
    "TANKUJ": (
        "Rafineria podniosła cenę dla stacji. Na pylonach zobaczysz to "
        "zwykle w ciągu 1-2 dni."
    ),
    "CZEKAJ": (
        "Rafineria obniżyła cenę dla stacji. Jeśli możesz, odłóż tankowanie "
        "o dzień lub dwa."
    ),
    "UWAGA": (
        "Mocny ruch na ropie, ale hurt jeszcze nie zareagował. "
        "Trzymam rękę na pulsie."
    ),
}


# ---------------------------------------------------------------------------
# Budowanie treści
# ---------------------------------------------------------------------------

def _linia_paliwa(nazwa: str, wpis: dict) -> str:
    """Jedna linia raportu dla jednego paliwa."""
    tekst = f"hurt {wpis['netto']:.2f} zł/l netto ({wpis['brutto']:.2f} z VAT)"

    if wpis.get("prognoza_pylon"):
        delta = wpis["prognoza_pylon"]
        znak = "+" if delta > 0 else ""
        bak = skutek_dla_baku(delta)
        tekst += (
            f"\nna pylonie: {znak}{delta * 100:.0f} gr/l "
            f"({znak}{bak:.2f} zł za bak 50 l)"
        )

    return tekst


def zbuduj_tekst(analiza: dict, problemy: list[str] | None = None) -> str:
    """Wersja czysto tekstowa - używana przez Telegram i jako zapas."""
    sygnal = analiza.get("sygnal", "SPOKOJ")
    linie = [NAGLOWKI_SYGNALU.get(sygnal, sygnal), ""]

    if WYJASNIENIA.get(sygnal):
        linie += [WYJASNIENIA[sygnal], ""]

    for nazwa, wpis in analiza.get("paliwa", {}).items():
        linie.append(f"{nazwa}: {_linia_paliwa(nazwa, wpis)}")

    linie.append("")

    if analiza.get("brent"):
        brent = analiza["brent"]
        opis = f"Ropa Brent: {brent['cena_usd']:.2f} USD/bbl"
        if brent.get("zmiana_proc") is not None:
            opis += f" ({brent['zmiana_proc']:+.1f}%)"
        linie.append(opis)

    if analiza.get("usd"):
        linie.append(f"Kurs USD: {analiza['usd']['kurs']:.4f} zł")

    if analiza.get("koszt_surowca"):
        linie.append(
            f"Sama ropa w litrze paliwa: {analiza['koszt_surowca']:.2f} zł"
        )

    if problemy:
        linie += ["", "Problemy ze źródłami: " + "; ".join(problemy)]

    return "\n".join(linie).strip()


def _zbuduj_embed(analiza: dict, problemy: list[str] | None = None) -> dict:
    """Bogaty format Discorda - kolorowy pasek, pola, stopka."""
    sygnal = analiza.get("sygnal", "SPOKOJ")

    pola = []
    for nazwa, wpis in analiza.get("paliwa", {}).items():
        pola.append({
            "name": nazwa,
            "value": _linia_paliwa(nazwa, wpis),
            "inline": True,
        })

    rynek = []
    if analiza.get("brent"):
        brent = analiza["brent"]
        opis = f"{brent['cena_usd']:.2f} USD/bbl"
        if brent.get("zmiana_proc") is not None:
            opis += f" ({brent['zmiana_proc']:+.1f}%)"
        rynek.append(f"Ropa Brent: {opis}")
    if analiza.get("usd"):
        rynek.append(f"Kurs USD: {analiza['usd']['kurs']:.4f} zł")
    if analiza.get("koszt_surowca"):
        rynek.append(
            f"Sama ropa w litrze: {analiza['koszt_surowca']:.2f} zł"
        )

    if rynek:
        pola.append({
            "name": "Rynek",
            "value": "\n".join(rynek),
            "inline": False,
        })

    if problemy:
        pola.append({
            "name": "Problemy ze źródłami",
            "value": "\n".join(problemy)[:1000],
            "inline": False,
        })

    return {
        "title": NAGLOWKI_SYGNALU.get(sygnal, sygnal),
        "description": WYJASNIENIA.get(sygnal, ""),
        "color": KOLORY.get(sygnal, KOLORY["SPOKOJ"]),
        "fields": pola,
        "footer": {"text": "Źródła: Orlen, NBP, Stooq"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Wysyłka
# ---------------------------------------------------------------------------

def _wyslij_json(url: str, ladunek: dict) -> None:
    dane = json.dumps(ladunek).encode("utf-8")
    zapytanie = urllib.request.Request(
        url, data=dane, headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(zapytanie, timeout=CZAS_OCZEKIWANIA)


def wyslij_discord(analiza: dict, problemy: list[str] | None = None) -> str:
    webhook = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if not webhook:
        return "Discord: pominięty (brak DISCORD_WEBHOOK)"

    try:
        _wyslij_json(webhook, {"embeds": [_zbuduj_embed(analiza, problemy)]})
        return "Discord: wysłano"
    except urllib.error.HTTPError as blad:
        # Discord odsyła w treści konkretny powód odmowy. Bez niego
        # zostaje samo "403", które nie mówi nic poza tym, że nie wolno.
        try:
            szczegoly = blad.read().decode("utf-8", "replace")[:300]
        except Exception:
            szczegoly = "(nie udało się odczytać treści)"

        # Opis adresu bez ujawniania tokena - sam kształt wystarczy,
        # żeby stwierdzić, czy do sekretu trafiło to, co powinno.
        czesci = webhook.split("/")
        opis = (
            f"długość {len(webhook)} znaków, "
            f"host {czesci[2] if len(czesci) > 2 else '?'}, "
            f"id {czesci[5][:10] if len(czesci) > 5 else '?'}"
        )

        return (
            f"Discord: HTTP {blad.code} - {szczegoly} "
            f"[webhook: {opis}]"
        )


def wyslij_telegram(analiza: dict, problemy: list[str] | None = None) -> str:
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return "Telegram: pominięty (brak tokena lub chat_id)"

    sygnal = analiza.get("sygnal", "SPOKOJ")
    naglowek = NAGLOWKI_SYGNALU.get(sygnal, sygnal)
    reszta = zbuduj_tekst(analiza, problemy).split("\n", 1)[-1].strip()

    _wyslij_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {
            "chat_id": chat_id,
            "text": f"<b>{naglowek}</b>\n\n{reszta}",
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
    )
    return "Telegram: wysłano"


def powiadom(analiza: dict, problemy: list[str] | None = None) -> list[str]:
    """
    Rozsyła raport na wszystkie skonfigurowane kanały.

    Awaria jednego kanału jest logowana i nie przerywa wysyłki na pozostałe.
    """
    raporty = []
    for kanal in (wyslij_discord, wyslij_telegram):
        try:
            raporty.append(kanal(analiza, problemy))
        except Exception as blad:
            raporty.append(f"{kanal.__name__}: awaria - {blad}")
    return raporty
