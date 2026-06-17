# Seed Checker

Seed Checker helps review RunSignup seed times with past race results.

## Setting Up

1. Access the website at [seed-checker-rho.vercel.app](https://seed-checker-rho.vercel.app/).
2. Enter the RunSignup `API key` and `API secret`.
3. Enter the RunSignup race ID for the race you want to check seeds for.
4. Click `load` to load the race.
5. Choose the names of the event and seed-time question.
6. Click `use event` to load the event.
7. Click `sync` to load current participants from RunSignup, or click `upload` to load a spreadsheet of participants to check.
8. Click `import` to load the event's past results.
9. Choose a check pool:
   - `all` checks every loaded participant.
   - `fastest` checks the fastest number of participants entered.
   - `range` checks participants whose seed time falls inside the entered time range.
10. Enter the leeway in seconds. A participant is marked `GOOD` when the difference between their seed time and past best is ≤ the leeway.
11. Click `check` to see the results.

## Reviewing

After checking, each row shows the current RunSignup seed, status, past best, search links, done state, and update button. If participants were loaded from a spreadsheet, the uploaded seed is shown separately.

Click a row to open the detail view. The detail view shows matching race history and manual override buttons. The search links open Athlinks, general web search, MileSplit search, and Athletic.net search.

Large result sets are shown in batches. Click `show more` at the bottom of the table to display additional rows.

Statuses:

- `GOOD`: the seed looks supported by the event's past results.
- `LIAR`: the seed appears faster than supported by the selected leeway.
- `REVIEW`: no clear match was found or the result needs human judgment.
- `manual`: the status was manually overridden.

## Editing Seeds

1. Type the correct seed time in the `RunSignup seed` field in `H:MM:SS` format.
2. Press Enter or click `update` to write back to RunSignup.
3. Click `mark` in the `done` column after reviewing a participant to track who has already been reviewed.

## Filters

- `ALL`: every checked participant.
- `GOOD`: participants classified or manually marked good.
- `LIAR`: participants classified or manually marked liar.
- `REVIEW`: participants needing review.
- `OVERRIDDEN`: participants with a manual status.
- `DONE`: participants marked done.
- `NOT DONE`: participants not yet marked done.
- `NULL SEED`: participants without a readable seed time.

Custom time ranges show participant counts and can be clicked to filter the table.

## Notes

Done markers and manual overrides are saved by RunSignup registration ID.

The RunSignup `API key` and `API secret` are entered in the browser and sent to the backend for RunSignup requests. They are required for actions that change data, such as syncing, uploading, importing, updating seeds, marking done, changing manual statuses, and saving leeway. They are not saved in the app database.

The app database saves imported results, participants, manual overrides, done markers, and recent app settings. Therefore, past results for an event only need to be imported once.
