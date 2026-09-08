"""
Źródła danych Strażnika.

Każda funkcja pobiera dane z jednego publicznego API i zwraca czysty słownik.
Żadna z nich nie wymaga klucza ani rejestracji.

Kolejność w łańcuchu cenowym:
    ropa Brent (USD/bbl)  ->  hurt Orlenu (PLN/m3)  ->  pylon stacji (PLN/l)
         globalnie                codziennie              1-2 dni później
"""

from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.request

# Ile litrów mieści baryłka ropy (baryłka amerykańska, standard naftowy)
LITROW_W_BARYLCE = 158.987

# Nagłówek przedstawiający Strażnika. Część serwisów odrzuca ruch bez User-Agent.
NAGLOWKI = {
    "User-Agent": "Straznik-Paliwa/1.0 (projekt edukacyjny; +github.com)",
    "Accept": "application/json, text/csv, */*",
}

CZAS_OCZEKIWANIA = 20


class BladZrodla(RuntimeError):
    """Rzucany, gdy źródło nie odpowiedziało albo zwróciło coś nieoczekiwanego."""


def _pobierz(url: str) -> str:
    """Pobiera treść spod adresu i zwraca ją jako tekst."""
    zapytanie = urllib.request.Request(url, headers=NAGLOWKI)
    try:
        with urllib.request.urlopen(zapytanie, timeout=CZAS_OCZEKIWANIA) as odpowiedz:
            return odpowiedz.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as blad:
        raise BladZrodla(f"{url} odpowiedziało kodem HTTP {blad.code}") from blad
    except Exception as blad:
        raise BladZrodla(f"Nie udało się pobrać {url}: {blad}") from blad


# ---------------------------------------------------------------------------
# ORLEN - hurtowe ceny paliw
# ---------------------------------------------------------------------------

URL_ORLEN = "https://tool.orlen.pl/api/wholesalefuelprices"

# Nazwy produktów w API Orlenu -> nasze czytelne etykiety
PALIWA_ORLEN = {
    "Pb95": "Pb95",
    "Pb98": "Pb98",
    "ONEkodiesel": "ON",
}


def pobierz_orlen() -> dict:
    """
    Hurtowy cennik Orlenu, czyli cena, po jakiej rafineria sprzedaje paliwo stacjom.

    To jest najważniejsze źródło Strażnika. Cennik zmienia się co kilka dni,
    a stacje przenoszą go na pylony z opóźnieniem około jednej doby -
    czyli w momencie publikacji wiemy już, co będzie jutro na dystrybutorze.

    Zwraca ceny w PLN za litr, netto (bez VAT, ale z akcyzą i opłatą paliwową).
    """
    surowe = json.loads(_pobierz(URL_ORLEN))

    if not isinstance(surowe, list) or not surowe:
        raise BladZrodla("API Orlenu zwróciło pustą listę")

    ceny = {}
    data_cennika = None

    for pozycja in surowe:
        nazwa = pozycja.get("productName")
        if nazwa not in PALIWA_ORLEN:
            continue
        # API podaje PLN za metr sześcienny, czyli za 1000 litrów
        ceny[PALIWA_ORLEN[nazwa]] = float(pozycja["value"]) / 1000.0
        data_cennika = data_cennika or (pozycja.get("effectiveDate") or "")[:10]

    if not ceny:
        raise BladZrodla("W cenniku Orlenu nie znaleziono żadnego znanego paliwa")

    return {"ceny_netto_zl_l": ceny, "data": data_cennika}


# ---------------------------------------------------------------------------
# NBP - kurs dolara
# ---------------------------------------------------------------------------

URL_NBP = "https://api.nbp.pl/api/exchangerates/rates/a/usd/last/2/?format=json"


def pobierz_kurs_usd() -> dict:
    """
    Średni kurs USD/PLN z tabeli A Narodowego Banku Polskiego.

    Ropa jest rozliczana w dolarach, więc słabszy złoty podnosi cenę paliwa
    nawet wtedy, gdy ropa stoi w miejscu. Bierzemy dwa ostatnie notowania,
    żeby móc pokazać kierunek zmiany.
    """
    dane = json.loads(_pobierz(URL_NBP))
    notowania = dane.get("rates", [])

    if not notowania:
        raise BladZrodla("NBP nie zwróciło żadnych notowań")

    aktualne = notowania[-1]
    poprzednie = notowania[-2] if len(notowania) > 1 else aktualne

    return {
        "kurs": float(aktualne["mid"]),
        "kurs_poprzedni": float(poprzednie["mid"]),
        "data": aktualne["effectiveDate"],
    }


# ---------------------------------------------------------------------------
# Stooq - notowania ropy Brent
# ---------------------------------------------------------------------------

URL_BRENT = "https://stooq.pl/q/l/?s=cb.f&f=sd2t2ohlcv&h&e=csv"


def pobierz_brent() -> dict:
    """
    Notowanie ropy Brent (kontrakt na giełdzie ICE), w dolarach za baryłkę.

    Brent jest przyczyną na początku łańcucha, ale reaguje najszybciej -
    dlatego traktujemy go jako wczesne ostrzeżenie, a nie jako prognozę.
    """
    tekst = _pobierz(URL_BRENT)
    wiersze = list(csv.DictReader(io.StringIO(tekst)))

    if not wiersze:
        raise BladZrodla("Stooq nie zwrócił notowania Brent")

    wiersz = wiersze[0]

    def liczba(*nazwy_kolumn):
        """Stooq bywa niekonsekwentny w nazwach kolumn, więc próbujemy kilku."""
        for nazwa in nazwy_kolumn:
            wartosc = wiersz.get(nazwa)
            if wartosc not in (None, "", "N/D"):
                try:
                    return float(wartosc)
                except ValueError:
                    continue
        return None

    zamkniecie = liczba("Zamkniecie", "Zamknięcie", "Close")
    otwarcie = liczba("Otwarcie", "Open")

    if zamkniecie is None:
        raise BladZrodla(f"Nie rozpoznano formatu danych ze Stooq: {wiersz}")

    return {
        "cena_usd": zamkniecie,
        "otwarcie_usd": otwarcie,
        "data": wiersz.get("Data") or wiersz.get("Date") or "",
    }


# ---------------------------------------------------------------------------
# Zbiorcze pobranie
# ---------------------------------------------------------------------------

def pobierz_wszystko() -> tuple[dict, list[str]]:
    """
    Odpytuje wszystkie źródła.

    Zwraca (dane, problemy). Awaria pojedynczego źródła nie przerywa pracy -
    Strażnik ma działać dalej na tym, co się udało pobrać, i zgłosić resztę.
    """
    dane: dict = {}
    problemy: list[str] = []

    for nazwa, funkcja in (
        ("orlen", pobierz_orlen),
        ("usd", pobierz_kurs_usd),
        ("brent", pobierz_brent),
    ):
        try:
            dane[nazwa] = funkcja()
        except Exception as blad:
            problemy.append(f"{nazwa}: {blad}")
            dane[nazwa] = None

    return dane, problemy
