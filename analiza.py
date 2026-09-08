"""
Mózg Strażnika.

Cała wiedza o tym, co znaczą pobrane liczby, siedzi tutaj - oddzielona
od pobierania danych i od wysyłania powiadomień. Dzięki temu tę część
da się przetestować bez dotykania internetu.

Założenie merytoryczne, na którym opiera się prognoza:

    Cena na pylonie = hurt Orlenu + marża stacji, wszystko powiększone o VAT.

Marża stacji zmienia się wolno, a VAT jest stały. Zmiana hurtu przekłada się
więc na pylon niemal jeden do jednego - tylko przemnożona przez VAT
i opóźniona o dobę lub dwie. Dlatego Strażnik prognozuje ZMIANĘ, a nie poziom:
zmiana jest odporna na to, czego nie znamy (marży konkretnej stacji).
"""

from __future__ import annotations

from zrodla import LITROW_W_BARYLCE

# Stawka VAT na paliwa. Od 1 września 2026 wróciła do 23% po wygaśnięciu
# obniżki w ramach programu "Ceny Paliwa Niżej".
VAT = 0.23

# Od ilu groszy na litrze uznajemy zmianę hurtu za wartą powiadomienia.
# Poniżej tego progu ruchy są szumem, który i tak nie dojdzie do pylonu.
PROG_HURTU_ZL_L = 0.02

# Od ilu procent zmiana ropy Brent jest sygnałem wczesnego ostrzegania.
PROG_BRENT_PROC = 3.0

# Ile średnio litrów mieści bak. Służy tylko do przeliczenia
# skutku podwyżki na kwotę, którą człowiek rozumie od ręki.
POJEMNOSC_BAKU_L = 50


def brutto(cena_netto: float) -> float:
    """Dokłada VAT do ceny netto."""
    return cena_netto * (1 + VAT)


def koszt_surowca_zl_l(brent_usd: float, kurs_usd: float) -> float:
    """
    Ile kosztuje sama ropa zawarta w jednym litrze paliwa.

    To nie jest cena paliwa - to wsad surowcowy, bez rafinacji, akcyzy,
    opłaty paliwowej, marż i VAT. Pokazanie tej liczby obok ceny na pylonie
    ładnie unaocznia, jak mała jej część to faktycznie ropa.
    """
    return brent_usd * kurs_usd / LITROW_W_BARYLCE


def zmiana_procentowa(teraz: float, poprzednio: float) -> float:
    """Zmiana w procentach. Zwraca 0.0, gdy nie ma z czym porównać."""
    if not poprzednio:
        return 0.0
    return (teraz - poprzednio) / poprzednio * 100.0


def przeanalizuj(dane: dict, stan: dict) -> dict:
    """
    Porównuje świeże dane z poprzednim uruchomieniem i buduje werdykt.

    Zwraca słownik z gotowymi liczbami i decyzją, czy alarmować.
    """
    wynik: dict = {
        "paliwa": {},
        "alarmowac": False,
        "powody": [],
        "sygnal": "SPOKOJ",
        "brent": None,
        "usd": None,
        "koszt_surowca": None,
    }

    poprzedni_hurt = (stan or {}).get("hurt_netto", {})

    # --- Hurt Orlenu: to on decyduje o sygnale ---------------------------
    orlen = dane.get("orlen")
    najwieksza_zmiana = 0.0

    if orlen:
        ceny = orlen["ceny_netto_zl_l"]
        # Kolejność od najpopularniejszego paliwa, nie alfabetyczna
        kolejnosc = [p for p in ("Pb95", "ON", "Pb98") if p in ceny]
        kolejnosc += [p for p in ceny if p not in kolejnosc]

        for paliwo in kolejnosc:
            cena_netto = ceny[paliwo]
            poprzednia = poprzedni_hurt.get(paliwo)
            delta_netto = None if poprzednia is None else cena_netto - poprzednia

            wpis = {
                "netto": cena_netto,
                "brutto": brutto(cena_netto),
                "delta_netto": delta_netto,
                # Zmiana hurtu netto przechodzi na pylon powiększona o VAT
                "prognoza_pylon": None if delta_netto is None else brutto(delta_netto),
            }
            wynik["paliwa"][paliwo] = wpis

            if delta_netto is not None and abs(delta_netto) > abs(najwieksza_zmiana):
                najwieksza_zmiana = delta_netto

        if abs(najwieksza_zmiana) >= PROG_HURTU_ZL_L:
            wynik["alarmowac"] = True
            wynik["sygnal"] = "TANKUJ" if najwieksza_zmiana > 0 else "CZEKAJ"
            kierunek = "w górę" if najwieksza_zmiana > 0 else "w dół"
            wynik["powody"].append(
                f"hurt Orlenu poszedł {kierunek} o "
                f"{abs(najwieksza_zmiana) * 100:.0f} gr/l netto"
            )

        wynik["najwieksza_zmiana_hurtu"] = najwieksza_zmiana
        wynik["data_cennika"] = orlen.get("data")

    # --- Ropa Brent: wczesne ostrzeganie ---------------------------------
    brent = dane.get("brent")
    if brent:
        poprzedni_brent = (stan or {}).get("brent_usd")
        zmiana = zmiana_procentowa(brent["cena_usd"], poprzedni_brent or 0)

        wynik["brent"] = {
            "cena_usd": brent["cena_usd"],
            "zmiana_proc": zmiana if poprzedni_brent else None,
        }

        if poprzedni_brent and abs(zmiana) >= PROG_BRENT_PROC:
            wynik["alarmowac"] = True
            wynik["powody"].append(f"ropa Brent zmieniła się o {zmiana:+.1f}%")
            # Ropa rusza się przed hurtem, więc jeśli hurt jeszcze śpi,
            # to i tak warto ostrzec - ale słabszym głosem.
            if wynik["sygnal"] == "SPOKOJ":
                wynik["sygnal"] = "UWAGA"

    # --- Kurs dolara -----------------------------------------------------
    usd = dane.get("usd")
    if usd:
        wynik["usd"] = {
            "kurs": usd["kurs"],
            "zmiana_proc": zmiana_procentowa(usd["kurs"], usd["kurs_poprzedni"]),
        }

    # --- Wsad surowcowy ---------------------------------------------------
    if brent and usd:
        wynik["koszt_surowca"] = koszt_surowca_zl_l(brent["cena_usd"], usd["kurs"])

    return wynik


def nowy_stan(dane: dict, poprzedni: dict | None = None) -> dict:
    """
    Buduje stan do zapamiętania na następne uruchomienie.

    Wartości ze źródeł, które akurat padły, przepisujemy ze starego stanu,
    żeby jedna nieudana próba nie skasowała punktu odniesienia.
    """
    poprzedni = poprzedni or {}
    stan = {
        "hurt_netto": dict(poprzedni.get("hurt_netto", {})),
        "brent_usd": poprzedni.get("brent_usd"),
        "kurs_usd": poprzedni.get("kurs_usd"),
    }

    if dane.get("orlen"):
        stan["hurt_netto"] = dict(dane["orlen"]["ceny_netto_zl_l"])
    if dane.get("brent"):
        stan["brent_usd"] = dane["brent"]["cena_usd"]
    if dane.get("usd"):
        stan["kurs_usd"] = dane["usd"]["kurs"]

    return stan


def skutek_dla_baku(delta_pylon_zl_l: float) -> float:
    """Ile złotych więcej lub mniej zapłacisz za pełny bak."""
    return delta_pylon_zl_l * POJEMNOSC_BAKU_L
