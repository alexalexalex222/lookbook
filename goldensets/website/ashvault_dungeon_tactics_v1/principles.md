# Ashvault Dungeon Tactics - Design Principles

This is a native turn-based game anchor. It teaches how to make a compact
tactics loop readable and playable without turning the board into a dashboard
or spreadsheet.

## Board-first composition

- The tactical board is the primary experience in the first viewport.
- Status, objective, and event log support the board; they do not compete with
  it as equal cards.
- Movement and attack ranges use distinct, accessible signals. Player, enemy,
  obstacle, goal, selected, and reachable states must remain distinguishable
  without relying on color alone.
- The layout preserves the entire playable decision surface on desktop and
  keeps controls and state readable at 360px.

## Turn-system contract

- Player input is accepted only during the player phase.
- A valid player action advances the turn and triggers deterministic enemy
  behavior.
- Health, enemy state, objective progress, turn count, and event history update
  from the same authoritative game state.
- Victory, defeat, and restart are explicit states. Restart restores the exact
  initial board without a document reload.
- Keyboard and touch paths operate the same movement/action model.

## Visual system

- Use a restrained neutral field with one player color, one enemy color, one
  objective color, and one focus/accent color.
- Grid cells have stable dimensions and never resize when selected, damaged, or
  highlighted.
- Typography and state labels stay compact; the board, not oversized headings,
  owns visual priority.
- Use SVG or CSS icons where needed. Do not use emoji as game pieces or controls.

## Adaptation rules

Borrow the board hierarchy, deterministic turn state, range signaling, compact
status rail, event log, and restart model. Rebuild the world, map, units, rules,
palette, copy, and difficulty for the target game.
