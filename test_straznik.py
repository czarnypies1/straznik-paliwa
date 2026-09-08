"""
Testy Strażnika.

Nie dotykają internetu - wszystkie dane są podstawione ręcznie.
Dzięki temu przechodzą zawsze i sprawdzają wyłącznie logikę.

Uruchomienie:
    python -m unittest -v
"""

import json
import unittest

import analiza as an
import powiadomienia
import zrodla


PRZYKLADOWE_DANE = {
    "orlen": {
        "ceny_netto_zl_l": {"Pb95": 6.262, "Pb98": 7.041, "ON": 7.047},
        "data": "2026-09-08",
    },
    "usd": {"kurs": 3.7080, "kurs_poprzedni": 3.7154, "data": "2026-09-07"},
    "brent": {"cena_usd": 96.28, "otwarcie_usd": 95.10, "data": "2026-09-08"},
}


class TestPrzeliczen(unittest.TestCase):

    def test_vat_dokladany_poprawnie(self):
        self.assertAlmostEqual(an.brutto(10.0), 12.30, places=2)

    def test_koszt_surowca(self):
        # 96.28 USD za baryłkę przy kursie 3.71 to około 2,25 zł na litr
        wynik = an.koszt_surowca_zl_l(96.28, 3.7080)
        self.assertAlmostEqual(wynik, 2.245, places=2)

    def test_zmiana_procentowa_bez_punktu_odniesienia(self):
        self.assertEqual(an.zmiana_procentowa(100, 0), 0.0)

    def test_skutek_dla_baku(self):
        # 15 groszy na litrze to 7,50 zł na baku 50-litrowym
        self.assertAlmostEqual(an.skutek_dla_baku(0.15), 7.50, places=2)


class TestAnalizy(unittest.TestCase):

    def test_bez_stanu_nie_ma_alarmu(self):
        wynik = an.przeanalizuj(PRZYKLADOWE_DANE, {})
        self.assertFalse(wynik["alarmowac"])
        self.assertEqual(wynik["sygnal"], "SPOKOJ")

    def test_wzrost_hurtu_daje_sygnal_tankuj(self):
        stan = {"hurt_netto": {"Pb95": 6.10, "Pb98": 7.041, "ON": 7.047}}
        wynik = an.przeanalizuj(PRZYKLADOWE_DANE, stan)

        self.assertTrue(wynik["alarmowac"])
        self.assertEqual(wynik["sygnal"], "TANKUJ")
        # 16,2 gr netto na litrze przechodzi na pylon jako około 20 gr brutto
        self.assertAlmostEqual(
            wynik["paliwa"]["Pb95"]["prognoza_pylon"], 0.199, places=2
        )

    def test_spadek_hurtu_daje_sygnal_czekaj(self):
        stan = {"hurt_netto": {"Pb95": 6.50, "Pb98": 7.041, "ON": 7.047}}
        wynik = an.przeanalizuj(PRZYKLADOWE_DANE, stan)

        self.assertEqual(wynik["sygnal"], "CZEKAJ")
        self.assertLess(wynik["paliwa"]["Pb95"]["delta_netto"], 0)

    def test_drobny_ruch_nie_budzi_straznika(self):
        # Jeden grosz na litrze to szum, nie powód do powiadomienia
        stan = {"hurt_netto": {"Pb95": 6.252, "Pb98": 7.041, "ON": 7.047}}
        wynik = an.przeanalizuj(PRZYKLADOWE_DANE, stan)
        self.assertFalse(wynik["alarmowac"])

    def test_skok_ropy_bez_ruchu_hurtu_daje_uwage(self):
        stan = {
            "hurt_netto": {"Pb95": 6.262, "Pb98": 7.041, "ON": 7.047},
            "brent_usd": 88.0,
        }
        wynik = an.przeanalizuj(PRZYKLADOWE_DANE, stan)

        self.assertTrue(wynik["alarmowac"])
        self.assertEqual(wynik["sygnal"], "UWAGA")

    def test_awaria_zrodla_nie_wywala_analizy(self):
        dane = {"orlen": None, "usd": None, "brent": PRZYKLADOWE_DANE["brent"]}
        wynik = an.przeanalizuj(dane, {})

        self.assertEqual(wynik["paliwa"], {})
        self.assertIsNotNone(wynik["brent"])


class TestStanu(unittest.TestCase):

    def test_stan_zapamietuje_wszystkie_wartosci(self):
        stan = an.nowy_stan(PRZYKLADOWE_DANE)
        self.assertEqual(stan["hurt_netto"]["Pb95"], 6.262)
        self.assertEqual(stan["brent_usd"], 96.28)
        self.assertEqual(stan["kurs_usd"], 3.7080)

    def test_padniete_zrodlo_nie_kasuje_starego_punktu_odniesienia(self):
        poprzedni = {"hurt_netto": {"Pb95": 6.10}, "brent_usd": 90.0}
        dane = {"orlen": None, "usd": None, "brent": PRZYKLADOWE_DANE["brent"]}

        stan = an.nowy_stan(dane, poprzedni)

        self.assertEqual(stan["hurt_netto"]["Pb95"], 6.10)  # zachowany
        self.assertEqual(stan["brent_usd"], 96.28)          # zaktualizowany


class TestPowiadomien(unittest.TestCase):

    def test_raport_zawiera_kluczowe_liczby(self):
        stan = {"hurt_netto": {"Pb95": 6.10, "Pb98": 7.041, "ON": 7.047}}
        wynik = an.przeanalizuj(PRZYKLADOWE_DANE, stan)
        tekst = powiadomienia.zbuduj_tekst(wynik)

        self.assertIn("TANKUJ", tekst)
        self.assertIn("Pb95", tekst)
        self.assertIn("Brent", tekst)

    def test_brak_konfiguracji_kanalu_nie_wywala_wysylki(self):
        wynik = an.przeanalizuj(PRZYKLADOWE_DANE, {})
        raporty = powiadomienia.powiadom(wynik)

        self.assertEqual(len(raporty), 2)
        self.assertTrue(all("pominięty" in r or "wysłano" in r for r in raporty))


class TestZrodelBrenta(unittest.TestCase):
    """Sprawdza parsery i łańcuch zapasowy, bez wychodzenia do sieci."""

    def test_parser_yahoo(self):
        odpowiedz = json.dumps({
            "chart": {"result": [{"meta": {
                "regularMarketPrice": 96.28,
                "chartPreviousClose": 95.10,
            }}]}
        })
        wynik = zrodla._brent_z_yahoo(odpowiedz)
        self.assertAlmostEqual(wynik["cena_usd"], 96.28)

    def test_parser_yahoo_zglasza_blad_gdy_pusto(self):
        with self.assertRaises(zrodla.BladZrodla):
            zrodla._brent_z_yahoo(json.dumps({"chart": {"result": []}}))

    def test_parser_csv(self):
        csv_tekst = (
            "Symbol,Data,Czas,Otwarcie,Najwyzszy,Najnizszy,Zamkniecie,Wolumen\n"
            "CB.F,2026-09-08,20:00:00,95.10,97.00,94.80,96.28,120000\n"
        )
        wynik = zrodla._brent_z_csv(csv_tekst)
        self.assertAlmostEqual(wynik["cena_usd"], 96.28)
        self.assertAlmostEqual(wynik["otwarcie_usd"], 95.10)

    def test_lancuch_przechodzi_do_kolejnego_zrodla(self):
        proby = []

        def udawane_pobranie(url):
            proby.append(url)
            if len(proby) == 1:
                raise zrodla.BladZrodla("HTTP 404")
            return json.dumps({
                "chart": {"result": [{"meta": {"regularMarketPrice": 99.0}}]}
            })

        oryginal = zrodla._pobierz
        zrodla._pobierz = udawane_pobranie
        try:
            wynik = zrodla.pobierz_brent()
        finally:
            zrodla._pobierz = oryginal

        self.assertEqual(len(proby), 2)          # pierwsze padło, drugie zadziałało
        self.assertAlmostEqual(wynik["cena_usd"], 99.0)

    def test_gdy_wszystkie_zrodla_pada_leci_wyjatek(self):
        oryginal = zrodla._pobierz
        zrodla._pobierz = lambda url: (_ for _ in ()).throw(
            zrodla.BladZrodla("padło")
        )
        try:
            with self.assertRaises(zrodla.BladZrodla):
                zrodla.pobierz_brent()
        finally:
            zrodla._pobierz = oryginal


if __name__ == "__main__":
    unittest.main(verbosity=2)
