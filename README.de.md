# Citrinitas

Eine offene Lagebasis für eine Person oder eine kleine Gruppe: offene Quellen in einem Modell, geschnitten
nach Ort, Zeit und Domäne, auf einem kleinen Rechner. [English](README.md)

Citrinitas ist das Gelbwerden, die dritte Stufe des alchemistischen Opus zwischen Albedo und Rubedo: das
Licht, in dem Dinge sichtbar werden. Gebaut ist es als Leuchtturm, nicht als Wachturm. Es zeigt, wo etwas
ist; es beobachtet keine Personen.

## Was es tut

- **Ein Modell für jede Quelle.** Jede Zeile hat Ort (ISO-Land, erste Verwaltungsebene, H3-Zelle), Zeit
  (Bezug, Meldung, Abruf), eine von fünfzehn Domänen und ihre Herkunft mit Lizenz.
- **Vier Klassen, die nie gemischt werden.** `measured` (Messung), `official` (amtlich), `reported`
  (Berichterstattung), `expected` (Erwartung).
- **Fragen steuern die Sammlung.** Jede Quelle dient einer Frage; jede Frage hat Indikatoren mit Schwelle und
  Basisrate, die vorher feststehen.
- **Blinde Flecken sind gemessen.** Die Abdeckungsmatrix zeigt, wo keine Klasse, nur eine Quelle oder nur
  Berichterstattung vorliegt; eine Sonde reiht Orte mit dichter Berichterstattung ohne harte Fakten.
- **Zwei Zeitachsen.** Korrekturen sind neue Zeilen. `facta_asof(t)` sagt, was zum Zeitpunkt t bekannt war.
- **Einschätzungen werden geprüft.** Sieben feste Wahrscheinlichkeitswörter mit Zahl, jede Zahl durch eine
  Zeile belegt, mindestens zwei Hypothesen, dieselben Zahlen bei erneuter Rechnung.
- **Nur lesend.** Ein HTTP-Zugang mit Token. Vorlagen für Anzeigen, begrenztes lesendes SQL für die Analyse.
  Keine Meldungen: Indikatoren sind Zustand zum Nachlesen.

Erste Quellen sind Fama (GDELT 2.0) und der CISA-Katalog ausgenutzter Schwachstellen.

## Was es nicht tut

Es führt keine Personenprofile. Personennamen in Quelldaten entfallen beim Einlesen, Beiträge aus sozialen
Netzen werden nur gezählt, und das Datenmodell kennt kein Objekt für eine Privatperson. Siehe
[ETHICS.md](ETHICS.md).

## Installation auf Proxmox VE

Auf dem Proxmox-Host als root:

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/pajew-ski/citrinitas/main/deploy/pve-create.sh)
```

Das legt einen unprivilegierten Debian-13-Container an, installiert die Dienste unter systemd und gibt
Adresse und Token aus. Einzelheiten: [docs/OPERATIONS.md](docs/OPERATIONS.md), Anforderungen:
[SPEC.md](SPEC.md), Schnittstelle: [docs/API.md](docs/API.md).

## Lizenz

Code: [Apache-2.0](LICENSE). Von Citrinitas selbst abgeleitete Daten: CC0-1.0. Quelldaten behalten die
Lizenz ihrer Quelle; sie steht an jeder Zeile und entscheidet, was das System verlassen darf.
