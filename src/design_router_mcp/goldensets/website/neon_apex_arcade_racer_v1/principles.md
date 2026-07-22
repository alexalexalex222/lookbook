# Neon Apex Arcade Racer - Design Principles

This is a native browser-game anchor. Its primary lesson is not the literal
neon palette or the Neon Apex name. It is the composition of a playable first
screen: the game world owns the viewport, the HUD stays subordinate, and every
overlay preserves a direct path back to play.

## Gameplay-first composition

- The canvas is the product and fills the viewport. Do not place a marketing
  hero, feature grid, or explanatory landing page ahead of it.
- Keep persistent HUD information to the minimum needed for the current loop:
  lap, checkpoint, timer, and speed.
- Start, pause, victory, defeat, and restart are distinct states with explicit
  focus and pointer behavior. Hidden overlays must not intercept input.
- Keyboard and touch controls are equal product surfaces. Touch targets are at
  least 44px and remain clear of HUD content at 360px.

## Visual system

- Use a dark neutral field with two or three signal colors assigned to roles,
  not a rainbow gradient wash.
- Use monospaced numerals for timing, speed, and lap telemetry.
- Keep the track and car legible before adding glow. Effects may reinforce
  velocity but cannot obscure boundaries, checkpoints, or collision feedback.
- Motion belongs to gameplay. UI transitions stay short and respect reduced
  motion where they are not mechanically required.

## Interaction contract

- The car must steer, accelerate, remain bounded by the track model, trigger
  checkpoints in order, complete laps, and update time/speed state.
- Pause freezes the simulation. Resume continues it. Restart resets all
  gameplay state without reloading the document.
- Touch controls must produce observable steering and acceleration.
- Canvas pixels must be painted at desktop and mobile sizes, with no horizontal
  overflow or console errors.

## Adaptation rules

Borrow the full-viewport stage, compact HUD hierarchy, overlay state machine,
and touch-control ergonomics. Rebuild the game identity, track shape, palette,
copy, tuning, and progression for the new brief.
