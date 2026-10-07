# Translink NI for Home Assistant

Departure boards for [Translink](https://www.translink.co.uk/) (Northern Ireland) bus, Glider
and rail stops: a **next departure** sensor, a **departures calendar**, and a
`translink_ni.get_departures` action.

> Uses the same (undocumented, key-free) endpoints as translink.co.uk's own stop search and
> departure boards. They may change without notice; if they do, the entities go unavailable
> rather than showing wrong times.

## Install

HACS → ⋮ → **Custom repositories** → add this repo as an *Integration* → install
**Translink NI** → restart Home Assistant.

## Set up a stop

**Settings → Devices & services → Add integration → Translink NI**

1. Type part of the stop name (e.g. `Cambria Street`).
2. Pick the stop from the list. Each direction is usually a separate stop (e.g. *Shankill,
   Cambria Street* is citybound; *Shankill, Flax Street* opposite is outbound).
3. Optionally limit to some services (e.g. `11e`, `11f`). You can type services that aren't
   running right now.

Options (⚙ on the entry): service filter, update interval (default 60 s).

## Entities (per stop)

| Entity | State | Attributes |
|---|---|---|
| `sensor.<stop>_next_departure` | **Expected (actual) departure time** of the next bus (timestamp) | `service`, `destination`, `scheduled`, `delay_minutes`, `transport_mode`, `stop_id`, `departures` (the board) |
| `calendar.<stop>_departures` | One event per upcoming departure, e.g. `11e → Belfast, CastleCourt (+5)` | standard calendar attributes |

- **Cancelled departures are dropped everywhere.** Translink's cancellation flag is rare and
  is sometimes withdrawn later; a cancelled bus is never shown as the next departure.
- The state is the **expected** time, so countdowns and automations follow the real bus. The
  timetabled time is in `scheduled`.
- The `departures` attribute (the board) is excluded from the recorder to keep the database small.
- Delays are whole minutes and never negative (Translink doesn't report early running).
- Translink's `IsRealTime` flag is not exposed: it is `true` for every departure, so it doesn't
  say whether a bus is actually being tracked.
- Only upcoming departures are available (the API ignores times in the past).

## Widget: next departure (scheduled, plus actual when late)

A Markdown card:

```yaml
type: markdown
content: >
  {% set s = 'sensor.shankill_cambria_street_next_departure' %}
  {% if has_value(s) %}
  {% set sched = as_local(as_datetime(state_attr(s, 'scheduled'))) %}
  {% set exp = as_local(as_datetime(states(s))) %}
  {% set late = state_attr(s, 'delay_minutes') | int(0) %}
  ## {{ state_attr(s, 'service') }} → {{ state_attr(s, 'destination') }}
  **{{ sched.strftime('%H:%M') }}**{% if late %} → **{{ exp.strftime('%H:%M') }}** (+{{ late }} min){% endif %}
  · {{ ((exp - now()).total_seconds() / 60) | round(0) | int }} min
  {% else %}
  No departures
  {% endif %}
```

Shows `11:46` normally and `11:46 → 11:51 (+5 min)` when the bus is late. A **Tile card** on the
sensor also works and shows a live "in N minutes".

### Departure board

```yaml
type: markdown
content: >
  {% set s = 'sensor.shankill_cambria_street_next_departure' %}
  | | To | Due |
  |:--|:--|--:|
  {% for d in state_attr(s, 'departures') or [] %}
  | **{{ d.service }}** | {{ d.destination }} | {{ as_local(as_datetime(d.planned)).strftime('%H:%M') }}{% if d.delay_minutes %} → {{ as_local(as_datetime(d.expected)).strftime('%H:%M') }} (+{{ d.delay_minutes }}){% endif %} |
  {% endfor %}
```

## Automations

**Leave-now reminder, 6 minutes before the next bus actually leaves:**

```yaml
triggers:
  - trigger: time
    at:
      entity_id: sensor.shankill_cambria_street_next_departure
      offset: "-00:06:00"
conditions:
  - condition: time
    weekday: [mon, tue, wed, thu, fri]
    after: "07:30:00"
    before: "09:30:00"
actions:
  - action: notify.notify
    data:
      message: >
        {{ state_attr('sensor.shankill_cambria_street_next_departure', 'service') }} leaves in 6 min
```

**Every departure, via the calendar** (fires for each bus, not just the next):

```yaml
triggers:
  - trigger: calendar
    event: start
    entity_id: calendar.shankill_cambria_street_departures
    offset: "-00:05:00"
```

**The list, via the action:**

```yaml
- action: translink_ni.get_departures
  data:
    config_entry_id: <the stop's config entry>
    count: 5
  response_variable: board
- if: "{{ board.departures[0].delay_minutes > 5 }}"
  then: ...
```

`get_departures` returns `stop_id`, `stop_name` and `departures`: a list of `service`,
`destination`, `planned`, `expected` (ISO timestamps, UTC), `delay_minutes` and `transport_mode`.
Optional `start` returns departures from a later time.

## Development

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python pytest-homeassistant-custom-component ruff
.venv/bin/python -m pytest
```

Tests use real responses captured from the API (`tests/fixtures/`), including a cancelled
departure and late running.
