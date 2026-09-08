"""
Diagnostyka źródeł Strażnika.

Odpytuje po kolei każde źródło i wypisuje, co odpowiedziało. Nie wysyła
powiadomień, nie zmienia stanu - służy wyłącznie do sprawdzenia, czy
świat zewnętrzny nadal wygląda tak, jak zakładał kod.

Przydaje się, gdy Strażnik zgłasza problem ze źródłem: zamiast zgadywać,
uruchamiasz to i widzisz dokładnie, który adres padł i dlaczego.

    python diagnostyka.py
"""

from __future__ import annotations

import time

import zrodla


def sprawdz(nazwa: str, funkcja) -> bool:
    """Uruchamia jedno źródło i ładnie raportuje wynik."""
    print(f"\n{nazwa}")
    print("-" * len(nazwa))

    start = time.monotonic()
    try:
        wynik = funkcja()
        czas = (time.monotonic() - start) * 1000
        print(f"  OK ({czas:.0f} ms)")
        for klucz, wartosc in wynik.items():
            print(f"    {klucz}: {wartosc}")
        return True
    except Exception as blad:
        czas = (time.monotonic() - start) * 1000
        print(f"  BŁĄD ({czas:.0f} ms)")
        print(f"    {blad}")
        return False


def sprawdz_kandydatow_brenta() -> None:
    """
    Testuje każdy adres z listy Brenta osobno.

    Zwykłe pobieranie zatrzymuje się na pierwszym działającym źródle,
    a tutaj chcemy zobaczyć stan wszystkich naraz.
    """
    print("\nKandydaci na źródło Brenta")
    print("-" * 26)

    for nazwa, url in zrodla.ZRODLA_BRENT:
        start = time.monotonic()
        try:
            tekst = zrodla._pobierz(url)
            parser = (
                zrodla._brent_z_yahoo if "yahoo" in nazwa else zrodla._brent_z_csv
            )
            wynik = parser(tekst)
            czas = (time.monotonic() - start) * 1000
            print(f"  {nazwa:12s} OK    {wynik['cena_usd']:.2f} USD ({czas:.0f} ms)")
        except Exception as blad:
            czas = (time.monotonic() - start) * 1000
            print(f"  {nazwa:12s} BŁĄD  {str(blad)[:90]} ({czas:.0f} ms)")


def main() -> int:
    print("=" * 60)
    print("DIAGNOSTYKA ŹRÓDEŁ STRAŻNIKA")
    print("=" * 60)

    wyniki = [
        sprawdz("ORLEN - hurtowe ceny paliw", zrodla.pobierz_orlen),
        sprawdz("NBP - kurs USD/PLN", zrodla.pobierz_kurs_usd),
        sprawdz("Ropa Brent", zrodla.pobierz_brent),
    ]

    sprawdz_kandydatow_brenta()

    dziala = sum(wyniki)
    print("\n" + "=" * 60)
    print(f"Działające źródła: {dziala} z {len(wyniki)}")

    if dziala == 0:
        print("Żadne źródło nie odpowiada - Strażnik nie ma z czego liczyć.")
        return 1
    if dziala < len(wyniki):
        print("Strażnik zadziała, ale w okrojonym zakresie.")
        return 0

    print("Wszystko na swoim miejscu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
