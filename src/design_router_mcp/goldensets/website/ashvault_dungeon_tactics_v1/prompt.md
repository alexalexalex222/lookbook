# Native Turn-Based Tactics Build Contract

Build a complete playable browser tactics game as the first screen.

Required behavior:

- stable grid map with walls or blocked cells;
- player selection and legal movement;
- deterministic enemy turns;
- movement and attack-range feedback;
- health and defeat handling;
- visible objective or exit;
- turn counter and event log;
- victory, defeat, and restart states;
- keyboard and touch controls;
- responsive layout at 360px, 390px, and desktop widths;
- no console errors or horizontal overflow.

Use a proven rules/state library if the game requires established domain logic;
otherwise keep one authoritative deterministic state machine. Do not describe
features that are not implemented. Do not place a marketing landing page ahead
of the game, and do not copy the donor name, map, palette, characters, or prose.
