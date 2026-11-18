# Responsible use

Citrinitas exists to make knowledge about the state of the world available to people who are not an agency
or a corporation. It is a lighthouse: it shows where things are. It is not built to watch persons, and its
data model is the place where that is decided.

## What the design rules out

- **No object for a private person.** Actors are states, organisations and persons in public office, and
  those only in relation to the office (SPEC C11, C35).
- **Names are dropped at the door.** Person names in source data are removed when a file is parsed. They are
  not stored and later hidden.
- **Social networks are counted, not read.** Posts enter only as counts by term, place and time, never by
  account (C11, C34).
- **Mechanism before motive.** Coordination, attention and anomalies are shown as counts and simultaneity. The
  system attributes no intent and names no culprit.
- **No alerts.** No value sends a message. A display that pushes on attention becomes a means of steering it
  (C15).
- **Reports are not events.** What media report is kept apart from what was measured or officially stated
  (C3), so that a loud topic is not mistaken for a large fact.

Turning this into a tool for watching people means rebuilding the data model. That is the safeguard; a licence
clause would not be one.

## What we ask of users

Citrinitas follows the principles of the Berkeley Protocol on Digital Open Source Investigations (OHCHR and
Human Rights Center, UC Berkeley, 2022): accountability, competence, objectivity, legality, security by
design, data minimisation, dignity, humility.

- Respect the licence of every source. It travels with every row.
- Collect for a question. A source without a question is removed.
- State uncertainty with a number, name alternatives, and keep assessments reproducible.
- Do not add sources that require circumventing access controls or terms of use.
- Do not add person-level data. Pull requests that do are declined.

## Licence and name

The code is under Apache-2.0, a licence without field-of-use restrictions, because such restrictions are
unenforceable in practice and exclude the public bodies and researchers who should be able to use this. The
licence does not grant the name: a product built on this code for watching people may not call itself
Citrinitas.
