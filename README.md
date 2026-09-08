# Strażnik Paliwa

Automat, który pilnuje, żebym nie zatankował dzień po podwyżce.

Sprawdza cennik hurtowy Orlenu, notowania ropy Brent i kurs dolara,
a gdy coś istotnego drgnie, pisze na Discorda i Telegrama — **zanim**
nowa cena pojawi się na pylonie.

Projekt na konkurs „Strażnik" (StormIT, Helion, inkBOOK, Dzień Programisty 2026).

---

## Problem

Cenę na stacji widzę dopiero wtedy, gdy już przy niej stoję. Wtedy jest za późno —
albo tankuję drożej, albo zawracam. A informacja, że będzie drożej, istnieje
publicznie **dzień wcześniej**. Tylko nikt jej nie czyta.

## Skąd wiadomo, co będzie jutro

Cena paliwa w Polsce powstaje w łańcuchu, w którym każdy element wyprzedza następny:

```
   ropa Brent            hurt Orlenu             pylon stacji
   USD/baryłkę    ──►    PLN/m³ netto     ──►    PLN/litr brutto
   reaguje w              publikowany            zmienia się
   minutach               codziennie             1–2 dni później
```

Kluczowa jest środkowa kolumna. **Cennik hurtowy Orlenu jest jawny i publikowany
codziennie**, a stacje przenoszą go na pylony z opóźnieniem mniej więcej doby.
W momencie publikacji cennika wiadomo więc, co będzie jutro na dystrybutorze.

Strażnik prognozuje **zmianę**, nie poziom:

```
zmiana na pylonie  ≈  zmiana hurtu netto  ×  1,23 (VAT)
```

To celowa decyzja. Bezwzględnej ceny nie da się przewidzieć, bo nie znam marży
konkretnej stacji — ale marża zmienia się wolno, więc w różnicy się skraca.
Prognoza zmiany jest odporna na to, czego nie wiem.

## Przykładowy alert

```
TANKUJ TERAZ

Rafineria podniosła cenę dla stacji.
Na pylonach zobaczysz to zwykle w ciągu 1-2 dni.

Pb95: hurt 6.44 zł/l netto (7.92 z VAT)
na pylonie: +22 gr/l (+11.07 zł za bak 50 l)

ON:   hurt 7.21 zł/l netto (8.87 z VAT)
na pylonie: +20 gr/l (+9.96 zł za bak 50 l)

Ropa Brent: 99.10 USD/bbl (+2.9%)
Kurs USD: 3.7080 zł
Sama ropa w litrze paliwa: 2.31 zł
```

Ostatnia linia to wsad surowcowy — ile w litrze paliwa kosztuje sama ropa,
bez rafinacji, akcyzy, opłaty paliwowej i VAT. Zwykle jest to około jednej
czwartej ceny na pylonie.

## Sygnały

| Sygnał | Kiedy | Co robić |
|---|---|---|
| **TANKUJ** | hurt w górę o ≥ 2 gr/l | zatankuj dziś, jutro będzie drożej |
| **CZEKAJ** | hurt w dół o ≥ 2 gr/l | odłóż tankowanie o dzień, dwa |
| **UWAGA** | Brent ±3%, hurt jeszcze śpi | wczesne ostrzeżenie |
| **SPOKÓJ** | ruchy poniżej progu | cisza, żadnego powiadomienia |

Próg 2 gr/l netto odsiewa szum. Ruchy mniejsze i tak nie docierają na pylon,
a Strażnik, który pisze codziennie „bez zmian", zostaje wyciszony po tygodniu.

## Źródła danych

Wyłącznie publiczne, oficjalne, bez kluczy API i bez rejestracji:

| Dane | Źródło | Format | Częstotliwość |
|---|---|---|---|
| Hurtowe ceny paliw | ORLEN S.A. — `tool.orlen.pl/api/wholesalefuelprices` | JSON | codziennie |
| Kurs USD/PLN | Narodowy Bank Polski — tabela A | JSON | dni robocze |
| Ropa Brent (ICE) | Stooq — symbol `cb.f` | CSV | na bieżąco |

Endpoint Orlenu to ten sam, z którego korzysta oficjalna strona
„Hurtowe ceny paliw". Ceny w PLN za m³, netto, z akcyzą i opłatą paliwową.

## Jak to jest zbudowane

```
zrodla.py          pobieranie z trzech API, każde źródło osobno
analiza.py         przeliczenia, progi, decyzja o sygnale
powiadomienia.py   Discord (embed) i Telegram (HTML), wysyłka równoległa
straznik.py        orkiestracja, pamięć stanu, zapis historii
test_straznik.py   14 testów jednostkowych, bez dostępu do sieci
```

Rozdzielenie na warstwy nie jest tu dla ozdoby: dzięki temu, że `analiza.py`
nie wie nic o internecie, całą logikę decyzyjną da się przetestować
deterministycznie, bez czekania na to, aż Orlen zmieni cennik.

Bez zewnętrznych zależności — sama biblioteka standardowa Pythona.
Nie ma `requirements.txt`, bo nie ma czego instalować.

## Odporność na awarie

Strażnik ma działać także wtedy, gdy coś nie działa:

- **padnięcie jednego źródła** nie przerywa pracy — raport powstaje
  z tego, co się udało pobrać, a brakujące źródła są wypisane w alercie;
- **stary punkt odniesienia nie ginie**, gdy źródło chwilowo nie odpowiada —
  inaczej po każdej awarii Strażnik zgłaszałby fałszywą wielką zmianę;
- **awaria jednego kanału** powiadomień nie blokuje drugiego;
- **brak konfiguracji kanału** powoduje jego pominięcie, nie wywrotkę;
- **uszkodzony plik stanu** jest wykrywany i odbudowywany od zera;
- `concurrency` w Actions pilnuje, żeby dwa uruchomienia nie nadpisały sobie stanu.

## Uruchamianie

Strażnik chodzi na GitHub Actions co godzinę między 5:00 a 21:00 — w nocy
cenniki i tak się nie zmieniają. Nie wymaga włączonego komputera.

Lokalnie:

```bash
python straznik.py           # normalne uruchomienie
python straznik.py --test    # wyślij raport niezależnie od zmian
python straznik.py --sucho   # pokaż raport w konsoli, nic nie wysyłaj
python -m unittest -v        # testy
```

Konfiguracja przez zmienne środowiskowe (w Actions: repository secrets).
Wystarczy jeden kanał, oba są opcjonalne:

```
DISCORD_WEBHOOK     adres webhooka kanału Discord
TELEGRAM_TOKEN      token bota od @BotFather
TELEGRAM_CHAT_ID    identyfikator rozmowy
```

Żaden sekret nie trafia do repozytorium — kod czyta je wyłącznie
ze środowiska.

## Efekt uboczny: otwarty zbiór danych

Przy każdym uruchomieniu Strażnik dopisuje wiersz do `historia.csv`
i commituje go z powrotem. Po kilku tygodniach powstaje z tego mały,
publiczny szereg czasowy: hurt trzech paliw, Brent, kurs dolara
i wyliczony wsad surowcowy, próbkowane co godzinę.

Nie planowałem tego jako celu, ale to najtrwalsza rzecz, jaka z tego zostanie.

## Ustawienia

Wszystkie progi siedzą na górze `analiza.py`:

```python
VAT = 0.23                # stawka VAT na paliwa
PROG_HURTU_ZL_L = 0.02    # od ilu groszy alarmować
PROG_BRENT_PROC = 3.0     # od ilu procent ostrzegać o ropie
POJEMNOSC_BAKU_L = 50     # do przeliczenia skutku na pełny bak
```

## Zastrzeżenie

Prognoza jest szacunkiem opartym na jawnym cenniku hurtowym. Cena na
konkretnej stacji zależy dodatkowo od lokalizacji, sieci i konkurencji.
To nie jest porada finansowa, tylko automat, który czyta za mnie
publiczne dane.

## Licencja

MIT.
