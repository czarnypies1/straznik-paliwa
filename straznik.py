"""
STRAŻNIK PALIWA
Automat, który pilnuje, żebyś nie zatankował dzień po podwyżce.

Co robi przy każdym uruchomieniu:
  1. pyta trzy publiczne źródła o aktualne dane,
  2. porównuje je z tym, co zapamiętał poprzednio,
  3. jeśli coś istotnego drgnęło - pisze na Discorda i Telegrama,
  4. dopisuje wiersz do historii i zapamiętuje nowy punkt odniesienia.

Uruchamiany co godzinę przez GitHub Actions. Nie wymaga włączonego komputera.

    python straznik.py           normalne uruchomienie
    python straznik.py --test    wysyła raport niezależnie od zmian
    python straznik.py --sucho   pokazuje raport w konsoli, nic nie wysyła
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import analiza as an
import powiadomienia
import zrodla

KATALOG = Path(__file__).parent
PLIK_STANU = KATALOG / "stan.json"
PLIK_HISTORII = KATALOG / "historia.csv"

KOLUMNY_HISTORII = [
    "znacznik_czasu",
    "hurt_pb95_netto",
    "hurt_pb98_netto",
    "hurt_on_netto",
    "brent_usd",
    "kurs_usd",
    "koszt_surowca_zl_l",
    "sygnal",
]


def log(wiadomosc: str) -> None:
    """Wypisuje z czasem - te logi widać potem w zakładce Actions."""
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {wiadomosc}", flush=True)


# ---------------------------------------------------------------------------
# Pamięć między uruchomieniami
# ---------------------------------------------------------------------------

def wczytaj_stan() -> dict | None:
    """Zwraca zapamiętany stan albo None, jeśli to pierwsze uruchomienie."""
    if not PLIK_STANU.exists():
        return None
    try:
        return json.loads(PLIK_STANU.read_text(encoding="utf-8"))
    except (ValueError, OSError) as blad:
        log(f"Stan uszkodzony, zaczynam od zera: {blad}")
        return None


def zapisz_stan(stan: dict) -> None:
    PLIK_STANU.write_text(
        json.dumps(stan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def dopisz_historie(dane: dict, wynik: dict) -> None:
    """
    Dokleja jeden wiersz do historii.csv.

    Plik rośnie z każdym uruchomieniem i po kilku tygodniach staje się
    małym, otwartym zbiorem danych o cenach paliw w Polsce.
    """
    paliwa = wynik.get("paliwa", {})
    wiersz = {
        "znacznik_czasu": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hurt_pb95_netto": _zaokraglij(paliwa.get("Pb95", {}).get("netto")),
        "hurt_pb98_netto": _zaokraglij(paliwa.get("Pb98", {}).get("netto")),
        "hurt_on_netto": _zaokraglij(paliwa.get("ON", {}).get("netto")),
        "brent_usd": _zaokraglij((dane.get("brent") or {}).get("cena_usd")),
        "kurs_usd": _zaokraglij((dane.get("usd") or {}).get("kurs"), 4),
        "koszt_surowca_zl_l": _zaokraglij(wynik.get("koszt_surowca")),
        "sygnal": wynik.get("sygnal", ""),
    }

    nowy_plik = not PLIK_HISTORII.exists()
    with PLIK_HISTORII.open("a", newline="", encoding="utf-8") as plik:
        zapis = csv.DictWriter(
            plik, fieldnames=KOLUMNY_HISTORII, lineterminator="\n"
        )
        if nowy_plik:
            zapis.writeheader()
        zapis.writerow(wiersz)


def _zaokraglij(wartosc, miejsca: int = 3):
    return "" if wartosc is None else round(float(wartosc), miejsca)


# ---------------------------------------------------------------------------
# Główny przebieg
# ---------------------------------------------------------------------------

def main() -> int:
    wymuszony = "--test" in sys.argv
    na_sucho = "--sucho" in sys.argv

    log("Strażnik rusza")

    dane, problemy = zrodla.pobierz_wszystko()
    for problem in problemy:
        log(f"Źródło niedostępne - {problem}")

    if all(wartosc is None for wartosc in dane.values()):
        log("Żadne źródło nie odpowiedziało. Kończę bez zmian w stanie.")
        return 1

    stan = wczytaj_stan()
    pierwsze_uruchomienie = stan is None

    wynik = an.przeanalizuj(dane, stan or {})

    if pierwsze_uruchomienie:
        wynik["sygnal"] = "START"
        wynik["alarmowac"] = True
        log("Pierwsze uruchomienie - zapamiętuję punkt odniesienia")
    elif wymuszony:
        wynik["alarmowac"] = True
        log("Tryb testowy - wysyłam raport mimo braku zmian")

    for nazwa, wpis in wynik.get("paliwa", {}).items():
        opis = f"{nazwa}: {wpis['netto']:.3f} zł/l netto"
        if wpis.get("delta_netto") is not None:
            opis += f" (zmiana {wpis['delta_netto'] * 100:+.1f} gr)"
        log(opis)

    if wynik.get("brent"):
        log(f"Brent: {wynik['brent']['cena_usd']:.2f} USD/bbl")
    if wynik.get("koszt_surowca"):
        log(f"Wsad surowcowy: {wynik['koszt_surowca']:.3f} zł/l")

    log(f"Sygnał: {wynik['sygnal']}")

    if na_sucho:
        print("\n--- podgląd raportu ---")
        print(powiadomienia.zbuduj_tekst(wynik, problemy))
        return 0

    if wynik["alarmowac"]:
        for raport in powiadomienia.powiadom(wynik, problemy):
            log(raport)
    else:
        log("Nic istotnego się nie zmieniło, nie zawracam głowy")

    dopisz_historie(dane, wynik)
    zapisz_stan(an.nowy_stan(dane, stan))
    log("Gotowe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
