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
# Część serwisów finansowych odrzuca ruch, który nie wygląda na przeglądarkę,
# ale wypada się przedstawić - stąd prefiks zgodny z konwencją plus nazwa projektu.
NAGLOWKI = {
    "User-Agent": "Mozilla/5.0 (compatible; Straznik-Paliwa/1.0; projekt edukacyjny)",
    "Accept": "application/json, text/csv, */*",
    "Accept-Language": "pl,en;q=0.8",
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

# Notowanie ropy pobieramy z łańcucha kandydatów, nie z jednego adresu.
#
# Powód jest praktyczny: w marcu 2026 Stooq zamknął darmowe pobieranie CSV
# za kluczem API i źródło, które działało od lat, przestało odpowiadać.
# Skoro jedno źródło może paść bez uprzedzenia, to Strażnik ma po prostu
# spróbować następnego, zamiast zgłaszać awarię.
#
# Kolejność ma znaczenie - pierwsze na liście są te, które wymagają
# najmniej i najrzadziej się psują.

ZRODLA_BRENT = [
    ("yahoo-1", "https://query1.finance.yahoo.com/v8/finance/chart/BZ=F?range=5d&interval=1d"),
    ("yahoo-2", "https://query2.finance.yahoo.com/v8/finance/chart/BZ=F?range=5d&interval=1d"),
    ("stooq-com", "https://stooq.com/q/l/?s=cb.f&f=sd2t2ohlcv&h&e=csv"),
]


def _brent_z_yahoo(tekst: str) -> dict:
    """Wyciąga notowanie z odpowiedzi Yahoo Finance."""
    dane = json.loads(tekst)
    wyniki = (dane.get("chart") or {}).get("result") or []

    if not wyniki:
        blad = (dane.get("chart") or {}).get("error")
        raise BladZrodla(f"Yahoo nie zwróciło notowania: {blad}")

    meta = wyniki[0].get("meta") or {}
    cena = meta.get("regularMarketPrice")

    if cena is None:
        raise BladZrodla("Brak ceny w odpowiedzi Yahoo")

    return {
        "cena_usd": float(cena),
        "otwarcie_usd": (
            float(meta["chartPreviousClose"])
            if meta.get("chartPreviousClose") is not None
            else None
        ),
        "data": "",
    }


def _brent_z_csv(tekst: str) -> dict:
    """Wyciąga notowanie z CSV w formacie Stooq."""
    wiersze = list(csv.DictReader(io.StringIO(tekst)))
    if not wiersze:
        raise BladZrodla("Puste CSV")

    wiersz = wiersze[0]

    def liczba(*nazwy):
        for nazwa in nazwy:
            wartosc = wiersz.get(nazwa)
            if wartosc not in (None, "", "N/D"):
                try:
                    return float(wartosc)
                except ValueError:
                    continue
        return None

    cena = liczba("Zamkniecie", "Zamknięcie", "Close")
    if cena is None:
        raise BladZrodla(f"Nie rozpoznano kolumn: {list(wiersz)}")

    return {
        "cena_usd": cena,
        "otwarcie_usd": liczba("Otwarcie", "Open"),
        "data": wiersz.get("Data") or wiersz.get("Date") or "",
    }


def pobierz_brent() -> dict:
    """
    Notowanie ropy Brent (kontrakt ICE), w dolarach za baryłkę.

    Brent stoi na początku łańcucha i reaguje najszybciej - dlatego jest
    wczesnym ostrzeżeniem, a nie prognozą. Prognozę daje hurt Orlenu.

    Próbuje kolejnych źródeł, dopóki któreś nie odpowie poprawnie.
    """
    napotkane = []

    for nazwa, url in ZRODLA_BRENT:
        try:
            tekst = _pobierz(url)
            parser = _brent_z_yahoo if "yahoo" in nazwa else _brent_z_csv
            wynik = parser(tekst)
            wynik["zrodlo"] = nazwa
            return wynik
        except Exception as blad:
            napotkane.append(f"{nazwa}: {blad}")

    raise BladZrodla("żadne źródło Brenta nie odpowiedziało - " + "; ".join(napotkane))


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
